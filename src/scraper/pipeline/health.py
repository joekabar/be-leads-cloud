"""Data-health checks: is data actually flowing, end to end?

Each check maps to a real incident that reported success while producing nothing.
Exit-code contract for callers: ok=False on any check means the pipeline is running
blind and the nightly should not pretend otherwise.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

_MIGRATION_RE = re.compile(r"^(\d{3})_.*\.sql$")


@dataclass(frozen=True, slots=True)
class HealthCheck:
    name: str
    ok: bool
    detail: str


async def check_staging(pool: Any) -> HealthCheck:
    """kbo_stage_* are UNLOGGED: Postgres truncates them during crash recovery.

    The 2026-08-13 container restart wiped 43.5M staged rows; every scrape then failed
    for days on "No staged KBO data found". This is the detector that did not exist.
    """
    row = await pool.fetchrow(
        "SELECT count(*) AS n, max(snapshot_date) AS snapshot_date FROM kbo_stage_enterprise"
    )
    n = int(row["n"]) if row and row["n"] is not None else 0
    if n <= 0:
        return HealthCheck(
            "staging",
            False,
            "kbo_stage_enterprise is EMPTY - unclean DB restart wipes UNLOGGED staging; "
            "run: uv run be-leads-kbo-stage KBO_zip/KboOpenData_*.zip",
        )
    return HealthCheck("staging", True, f"{n} entities staged (snapshot {row['snapshot_date']})")


async def check_migrations(pool: Any, migrations_dir: Path) -> HealthCheck:
    # Blocking iterdir() in an async function (ASYNC240): migrations_dir holds ~10
    # .sql files, so this is a handful of stat-free directory-entry reads - too small
    # to justify a thread-pool hop, and it runs once per health check, not per request.
    available = max(
        (int(m.group(1)) for f in migrations_dir.iterdir() if (m := _MIGRATION_RE.match(f.name))),  # noqa: ASYNC240
        default=0,
    )
    row = await pool.fetchrow("SELECT COALESCE(MAX(version), 0) AS v FROM schema_version")
    applied = int(row["v"]) if row else 0
    if applied < available:
        return HealthCheck(
            "migrations",
            False,
            f"schema at {applied}, migration {available} on disk - run: uv run be-leads-migrate",
        )
    return HealthCheck("migrations", True, f"schema at {applied}")


def _hours_since(ts: datetime | None) -> float | None:
    if ts is None:
        return None
    return (datetime.now(UTC) - ts).total_seconds() / 3600


async def check_scrape_freshness(pool: Any, *, max_age_hours: int = 26) -> HealthCheck:
    """Runs are scheduled twice daily; >26h without a PRODUCTIVE goudengids run means
    the pipeline is dead or every run is failing - both worth an alarm. (When the whole
    rotation is genuinely complete this fires too; that state is months away and would
    deserve a look anyway.)"""
    row = await pool.fetchrow(
        "SELECT max(started_at) AS last FROM run_log WHERE source = 'goudengids' AND jobs_done > 0"
    )
    age = _hours_since(row["last"] if row else None)
    if age is None:
        return HealthCheck("scrape", False, "no productive goudengids run on record")
    if age > max_age_hours:
        msg = f"last productive scrape {age:.0f}h ago (max {max_age_hours}h)"
        return HealthCheck("scrape", False, msg)
    return HealthCheck("scrape", True, f"last productive scrape {age:.1f}h ago")


async def check_source_freshness(pool: Any, source: str, *, max_age_hours: int) -> HealthCheck:
    row = await pool.fetchrow(
        "SELECT max(started_at) AS last FROM run_log WHERE source = $1 AND jobs_done > 0",
        source,
    )
    age = _hours_since(row["last"] if row else None)
    name = f"source:{source}"
    if age is None:
        return HealthCheck(name, False, f"{source} has never produced anything")
    if age > max_age_hours:
        msg = f"{source} last productive {age:.0f}h ago (max {max_age_hours}h)"
        return HealthCheck(name, False, msg)
    return HealthCheck(name, True, f"{source} last productive {age:.1f}h ago")


def check_export_freshness(export_dir: Path, *, max_age_hours: int = 26) -> HealthCheck:
    """The exporter ran green for weeks while pinned to a city the rotation had left."""
    newest: float | None = None
    if export_dir.is_dir():
        mtimes = [p.stat().st_mtime for p in export_dir.glob("leads_*.csv")]
        newest = max(mtimes, default=None)
    if newest is None:
        return HealthCheck("exports", False, f"no leads_*.csv in {export_dir}")
    age = (datetime.now(UTC) - datetime.fromtimestamp(newest, UTC)).total_seconds() / 3600
    if age > max_age_hours:
        return HealthCheck("exports", False, f"newest export {age:.0f}h old (max {max_age_hours}h)")
    return HealthCheck("exports", True, f"newest export {age:.1f}h old")


async def check_dead_slugs(pool: Any, *, min_runs: int = 3, min_cities: int = 2) -> HealthCheck:
    """Sectors repeatedly attempted across cities that never yielded one observation
    are almost certainly wrong goudengids slugs; the queue marks them done and never
    looks again. Four such slugs burned ~34 runs before anyone noticed."""
    rows = await pool.fetch(
        """
        SELECT rl.sector_slug, count(*) AS runs, count(DISTINCT rl.city_slug) AS cities
        FROM run_log rl
        WHERE rl.source = 'goudengids' AND rl.sector_slug IS NOT NULL
        GROUP BY rl.sector_slug
        HAVING count(*) >= $1 AND count(DISTINCT rl.city_slug) >= $2
           AND NOT EXISTS (
                SELECT 1 FROM run_log r2
                JOIN observations o ON o.run_id = r2.run_id
                WHERE r2.sector_slug = rl.sector_slug AND r2.source = 'goudengids'
           )
        ORDER BY 1
        """,
        min_runs,
        min_cities,
    )
    if rows:
        slugs = ", ".join(str(r["sector_slug"]) for r in rows)
        return HealthCheck("dead-slugs", False, f"never-productive sector slugs: {slugs}")
    return HealthCheck("dead-slugs", True, "no suspect sector slugs")


async def run_health(pool: Any, *, migrations_dir: Path, export_dir: Path) -> list[HealthCheck]:
    return [
        await check_staging(pool),
        await check_migrations(pool, migrations_dir),
        await check_scrape_freshness(pool),
        await check_source_freshness(pool, "brave", max_age_hours=72),
        check_export_freshness(export_dir),
        await check_dead_slugs(pool),
    ]


def render(checks: list[HealthCheck]) -> tuple[str, int]:
    """Failures first — the terminal shows the top of the output, not the bottom."""
    ordered = sorted(checks, key=lambda c: c.ok)
    lines = [f"{'OK  ' if c.ok else 'FAIL'} {c.name}: {c.detail}" for c in ordered]
    return "\n".join(lines), 0 if all(c.ok for c in checks) else 1


def cli_main() -> None:  # pragma: no cover
    import argparse
    import asyncio
    import sys
    from pathlib import Path

    import asyncpg

    from scraper.lib.config import database_url, project_root

    parser = argparse.ArgumentParser(description="Is data flowing? One answer, exit 0/1.")
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--export-dir", default=None)
    args = parser.parse_args()

    dsn = args.database_url or database_url()
    if not dsn:
        print("DATABASE_URL is not set", file=sys.stderr)
        sys.exit(2)
    export_dir = Path(args.export_dir) if args.export_dir else project_root() / "exports"

    from scraper.db.migrations import runner as _runner

    migrations_dir = Path(_runner.__file__).parent

    async def _run() -> list[HealthCheck]:
        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
        if pool is None:
            raise RuntimeError("asyncpg.create_pool returned None")
        try:
            return await run_health(pool, migrations_dir=migrations_dir, export_dir=export_dir)
        finally:
            await pool.close()

    try:
        checks = asyncio.run(_run())
    except (OSError, asyncpg.PostgresError, TimeoutError) as exc:
        print(f"cannot reach the database: {exc}", file=sys.stderr)
        sys.exit(2)

    text, code = render(checks)
    print(text)
    sys.exit(code)
