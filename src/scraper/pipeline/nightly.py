"""Nightly scrape orchestration: city, sectors, batch, verdict.

This logic lived in scripts/nightly_scrape.ps1, where no test could reach it and
where every silent-failure incident of 2026-08 originated. PowerShell keeps only
OS glue (Docker preflight, scheduling); the decisions live here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from scraper.lib.sector_nace import SECTOR_NACE_PREFIXES
from scraper.pipeline.batch import BatchConfig, BatchReport, run_batch
from scraper.pipeline.health import check_migrations, check_staging
from scraper.pipeline.sector_queue import (
    fetch_completed_by_city,
    fetch_completed_sectors,
    goudengids_unscrapeable_sectors,
    load_rotation_cities,
    select_next_city,
    select_pending_sectors,
)

#: Exit codes shared with scripts/nightly_scrape.ps1 - keep the two lists in step:
#: 0 ok, 1 unhandled, 3 db unavailable (PS preflight), 4 sector failures,
#: 5 source failed, 6 data preflight failed (health check).
EXIT_OK = 0
EXIT_SECTOR_FAILURES = 4
EXIT_SOURCE_FAILED = 5
EXIT_PREFLIGHT = 6


@dataclass(frozen=True, slots=True)
class Verdict:
    exit_code: int
    state_line: str
    notes: list[str]


def write_state(path: Path, msg: str) -> None:
    """Append one state line, same grammar the PowerShell wrapper used, so the
    history in nightly_scrape.log stays grep-compatible across the handover."""
    stamp = datetime.now(UTC).astimezone().strftime("%Y-%m-%dT%H:%M:%S")
    with path.open("a", encoding="utf-8") as fh:
        fh.write(f"[{stamp}] {msg}\n")


def judge_batch(report: BatchReport, *, log_path: str) -> Verdict:
    """A sector that found nothing is a quiet night; a sector that RAISED is not."""
    attempted = len(report.sectors)
    scraped = sum(1 for v in report.goudengids_per_sector.values() if v > 0)
    failed = len(report.goudengids_sector_errors)
    notes = [f"NOTE source failed: {src}={err}" for src, err in report.sources_failed.items()]

    if failed:
        first = next(iter(report.goudengids_sector_errors.values()))[:160]
        line = (
            f"END exit={EXIT_SECTOR_FAILURES} scraped={scraped}/{attempted} "
            f"failed={failed} log={log_path} reason=sector-failures :: {first}"
        )
        return Verdict(EXIT_SECTOR_FAILURES, line, notes)

    if report.sources_failed:
        joined = ", ".join(f"{k}={v}" for k, v in report.sources_failed.items())
        line = (
            f"END exit={EXIT_SOURCE_FAILED} scraped={scraped}/{attempted} "
            f"failed=0 log={log_path} reason=source-failed :: {joined}"
        )
        return Verdict(EXIT_SOURCE_FAILED, line, notes)

    line = f"END exit={EXIT_OK} scraped={scraped}/{attempted} failed=0 log={log_path}"
    return Verdict(EXIT_OK, line, notes)


async def select_city(pool: object, cities: list[str], *, within_hours: int | None) -> str | None:
    all_sectors = sorted(SECTOR_NACE_PREFIXES)
    unscrapeable = goudengids_unscrapeable_sectors(all_sectors)
    completed = await fetch_completed_by_city(pool, cities, within_hours=within_hours)
    return select_next_city(cities, all_sectors, completed, unscrapeable=unscrapeable)


async def run_nightly(
    pool: object,
    polite_client: object,
    *,
    city: str,
    limit: int,
    within_hours: int | None,
    state_log: Path,
    log_path: str,
    brave_key: str | None,
    nbb_key: str | None,
    dsn: str,
    migrations_dir: Path,
) -> int:
    # Data preflight: Aug 18-20 every run spent WAF budget only to fail on wiped
    # staging one second in. Refuse to start the browser against a dead foundation.
    for check in (await check_staging(pool), await check_migrations(pool, migrations_dir)):
        if not check.ok:
            write_state(state_log, f"END exit={EXIT_PREFLIGHT} reason=preflight :: {check.detail}")
            return EXIT_PREFLIGHT

    all_sectors = sorted(SECTOR_NACE_PREFIXES)
    done = await fetch_completed_sectors(pool, city, within_hours=within_hours)
    sectors = select_pending_sectors(
        all_sectors,
        done=done,
        limit=limit,
        cycle=False,
        unscrapeable=goudengids_unscrapeable_sectors(all_sectors),
    )
    if not sectors:
        write_state(state_log, f"DONE city={city} is fully covered, nothing to scrape tonight")
        return EXIT_OK

    write_state(state_log, f"SCRAPE {len(sectors)} sectors: {', '.join(sectors)}")

    config = BatchConfig(
        city=city,
        sectors=sectors,
        do_kbo_dump=False,  # staging is loaded; spend the night on discovery
        brave_subscription_key=brave_key,
        nbb_subscription_key=nbb_key,
        database_url=dsn,
    )
    report = await run_batch(config, pool, polite_client)  # type: ignore[arg-type]

    verdict = judge_batch(report, log_path=log_path)
    write_state(state_log, verdict.state_line)
    for note in verdict.notes:
        write_state(state_log, note)
    return verdict.exit_code


def cli_main() -> None:  # pragma: no cover
    import argparse
    import asyncio
    import json as _json
    import sys

    import asyncpg
    import httpx

    from scraper.lib.config import load_settings, project_root
    from scraper.lib.data_paths import PER_HOST_TOML
    from scraper.lib.http.client import PoliteClient
    from scraper.lib.http.limiter import load_from_toml
    from scraper.pipeline.batch_cli import _resolve_api_keys

    parser = argparse.ArgumentParser(
        description="One scheduled nightly scrape: city, sectors, batch, verdict."
    )
    parser.add_argument("--city", default="", help="Pin a city; empty = rotation")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--within-hours", type=int, default=None)
    parser.add_argument("--state-log", default=None, help="default: <repo>/logs/nightly_scrape.log")
    parser.add_argument("--database-url", default=None)
    args = parser.parse_args()

    settings = load_settings()  # loads .env; key reads MUST come after (see batch_cli)
    dsn = args.database_url or settings.database_url
    brave_key, nbb_key = _resolve_api_keys(None, None)

    log_dir = project_root() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    state_log = Path(args.state_log) if args.state_log else log_dir / "nightly_scrape.log"
    stamp = datetime.now(UTC).astimezone().strftime("%Y-%m-%d-%H%M")

    from scraper.db.migrations import runner as _runner

    migrations_dir = Path(_runner.__file__).parent

    async def _run() -> int:
        async def _init_jsonb(conn: asyncpg.Connection) -> None:
            await conn.set_type_codec(
                "jsonb", encoder=_json.dumps, decoder=_json.loads, schema="pg_catalog"
            )

        pool = await asyncpg.create_pool(dsn, min_size=2, max_size=10, init=_init_jsonb)
        if pool is None:
            raise RuntimeError("asyncpg.create_pool returned None")
        try:
            city = args.city.strip().lower()
            if not city:
                cities = load_rotation_cities()
                selected = await select_city(pool, cities, within_hours=args.within_hours)
                if selected is None:
                    write_state(state_log, "END exit=0 reason=all-cities-complete")
                    print("Nothing to scrape: every configured city is complete.")
                    return EXIT_OK
                city = selected
                write_state(state_log, f"CITY {city} (from rotation)")

            limiter = load_from_toml(PER_HOST_TOML)
            async with httpx.AsyncClient(follow_redirects=True) as http_client:
                polite_client = PoliteClient(inner=http_client, limiter=limiter)
                return await run_nightly(
                    pool,
                    polite_client,
                    city=city,
                    limit=args.limit,
                    within_hours=args.within_hours,
                    state_log=state_log,
                    log_path=str(log_dir / f"nightly_run_{stamp}.log"),
                    brave_key=brave_key,
                    nbb_key=nbb_key,
                    dsn=dsn,
                    migrations_dir=migrations_dir,
                )
        finally:
            await pool.close()

    try:
        code = asyncio.run(_run())
    except Exception as exc:
        write_state(state_log, f"END exit=1 reason=unhandled :: {exc}")
        print(f"Nightly error: {exc}", file=sys.stderr)
        sys.exit(1)
    sys.exit(code)
