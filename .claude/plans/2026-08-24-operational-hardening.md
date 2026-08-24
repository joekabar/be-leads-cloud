# Operational Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make silent failure impossible in the nightly pipeline: a health check that answers "is data flowing?", verdict logic moved from untested PowerShell into tested Python, and the config/coupling seams that produced four incidents closed.

**Architecture:** The Python core (parsing, scoring, provenance) has produced zero incidents; all four production failures happened in the operational shell — PowerShell verdict logic, unvalidated config, silent externals. This plan moves decision logic down into Python where TDD reaches it, adds a `be-leads-health` command over the signals every incident would have tripped, and leaves PowerShell only what is genuinely OS glue (Docker preflight, scheduling). No new subsystems, no queue activation, no rewrites.

**Tech Stack:** Python 3.12, asyncpg, structlog, pytest (asyncio_mode=auto), Windows PowerShell 5.1 (pure-ASCII scripts), uv.

**Spec:** No separate spec file — the design was approved in-chat (session 2026-08-24): ranked improvements 1–4 of the architecture review; item 5 (export.py relocation) cut after research showed `_aggregate_row`/`_financial_amount` are a shared UI/export family whose home is correct.

## Global Constraints

- Every change to `src/scraper/**` MUST touch `tests/**` in the same commit (TDD hooks enforce this).
- `uv run pytest --cov=src/scraper --cov-fail-under=85 -m "not network and not slow and not integration"` must pass before every commit.
- `uv run ruff check` and `uv run ruff format --check` clean on changed files; `uv run mypy --strict` clean on changed src files.
- `asyncio_mode = "auto"` — `async def` tests run as-is; NEVER add `@pytest.mark.asyncio`.
- `scripts/*.ps1` MUST stay pure ASCII (PS 5.1 reads BOM-less UTF-8 as ANSI).
- Never `UPDATE observations`; never add update/delete to ObservationsRepo.
- Commits end with:
  `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>` and
  `Claude-Session: https://claude.ai/code/session_01JQLr8u31mUv8vP8t1KPGgN`
  Write multi-line messages to a temp file and use `git commit -F` (quoting inside `-m` breaks in this shell).
- Branch: `fix/silent-nightly-failures`. Do not push until the final task.
- CHANGELOG entries are consolidated in the final task (one section per feature), not per commit.

## Existing interfaces this plan builds on (verified 2026-08-24)

- `orchestrator.py:33` — `_SECTOR_NACE_PREFIXES: dict[str, list[str]]` (sector slug → NACE prefixes).
- `sector_queue.py` — `load_rotation_cities() -> list[str]`; `fetch_completed_by_city(pool, cities, *, within_hours=None) -> dict[str, set[str]]`; `fetch_completed_sectors(pool, city, *, within_hours=None) -> set[str]`; `select_next_city(cities, all_sectors, completed_by_city, *, unscrapeable=frozenset()) -> str | None`; `select_pending_sectors(all_sectors, *, done, limit, cycle, unscrapeable) -> list[str]`; `goudengids_unscrapeable_sectors(all_sectors) -> set[str]`.
- `batch.py` — `BatchConfig` (fields incl. `city`, `sectors: list[str]`, `do_kbo_dump: bool`, `brave_subscription_key`, `nbb_subscription_key`, `database_url`, `goudengids_skip_recent_hours: int = 720`); `BatchReport` (fields incl. `sectors: list[str]`, `sources_failed: dict[str, str]`, `goudengids_per_sector: dict[str, int]`); `run_batch(config, pool, polite_client) -> BatchReport`; `_run_goudengids_sector(...) -> int` whose `except Exception` at ~line 516 logs `goudengids_sector_failed` and returns 0 — the caller at ~line 642 does `report.goudengids_per_sector[sector_slug] = obs_count`.
- `batch_cli.py` — `_resolve_api_keys(brave_arg, nbb_arg) -> tuple[str | None, str | None]` (call AFTER `load_settings()`); pool setup pattern with jsonb codec; `PoliteClient(inner=http_client, limiter=load_from_toml(PER_HOST_TOML))`.
- `db/migrations/runner.py` — migrations live in `Path(runner.__file__).parent`, files match `^\d{3}_.*\.sql`; `schema_version(version int)` table.
- `lib/config.py` — `project_root() -> Path`, `database_url() -> str` (non-raising), `load_settings()`.
- State-log line format (must stay grep-compatible): `[2026-08-24T02:30:02] END exit=0 ...`, written UTF-8 via append.
- Existing wrapper exit codes: 0 ok, 1 unhandled, 3 database unavailable, 4 sector failures, 5 source failed. This plan adds 6 = data preflight failed.

---

### Task 1: Promote `_SECTOR_NACE_PREFIXES` to a public home in `lib/`

Six modules — including CLIs and (indirectly) UI — import a private name from `orchestrator.py`. Give the data a public owner; orchestrator keeps a back-compat alias so nothing else changes behaviourally.

**Files:**
- Create: `src/scraper/lib/sector_nace.py`
- Modify: `src/scraper/pipeline/orchestrator.py:33` (replace dict literal with import + alias)
- Modify: `src/scraper/pipeline/batch.py:30`, `src/scraper/pipeline/batch_cli.py`, `src/scraper/pipeline/next_city_cli.py`, `src/scraper/pipeline/sector_queue_cli.py` (import sites)
- Test: `tests/unit/lib/test_sector_nace.py`

**Interfaces:**
- Consumes: the existing dict literal in `orchestrator.py`.
- Produces: `from scraper.lib.sector_nace import SECTOR_NACE_PREFIXES` — `dict[str, list[str]]`, same contents. `orchestrator._SECTOR_NACE_PREFIXES` remains as an alias (`_SECTOR_NACE_PREFIXES = SECTOR_NACE_PREFIXES`) so unknown importers keep working. Later tasks import the NEW name.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/lib/test_sector_nace.py
"""SECTOR_NACE_PREFIXES has a public home.

It was a private constant in pipeline/orchestrator.py imported by six modules across
layers — the same two-owners drift pattern that let city_map.toml and postcodes.toml
diverge until 13 of 15 cities were wrong.
"""

from __future__ import annotations

import re

from scraper.lib.sector_nace import SECTOR_NACE_PREFIXES


class TestSectorNacePrefixes:
    def test_is_nonempty_mapping(self) -> None:
        assert len(SECTOR_NACE_PREFIXES) > 50
        assert SECTOR_NACE_PREFIXES["elektriciens"] == ["4321"]

    def test_orchestrator_alias_is_the_same_object(self) -> None:
        """Back-compat: the old private name must not become a second copy."""
        from scraper.pipeline.orchestrator import _SECTOR_NACE_PREFIXES

        assert _SECTOR_NACE_PREFIXES is SECTOR_NACE_PREFIXES

    def test_prefixes_are_dotless_digits(self) -> None:
        """KBO Open Data stores NACE without dots: '4321', never '43.21'."""
        for slug, prefixes in SECTOR_NACE_PREFIXES.items():
            assert prefixes, f"{slug} maps to no prefixes"
            for p in prefixes:
                assert re.fullmatch(r"[0-9]{2,7}", p), f"{slug}: bad prefix {p!r}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/lib/test_sector_nace.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scraper.lib.sector_nace'`

- [ ] **Step 3: Create the module by moving the dict**

Cut the entire `_SECTOR_NACE_PREFIXES: dict[str, list[str]] = { ... }` literal (orchestrator.py, starts line 33 — take the whole dict with its inline comments verbatim) into the new file:

```python
# src/scraper/lib/sector_nace.py
"""Sector slug -> NACE prefix mapping, the vocabulary of the whole pipeline.

Formerly a private constant in pipeline/orchestrator.py imported by six modules.
KBO Open Data stores NACE codes WITHOUT dots ("4321", never "43.21"); every prefix
here must match that format — enforced by tests/unit/lib/test_sector_nace.py.
"""

from __future__ import annotations

SECTOR_NACE_PREFIXES: dict[str, list[str]] = {
    # ... the moved dict body, verbatim including comments ...
}
```

In `orchestrator.py`, where the literal was:

```python
from scraper.lib.sector_nace import SECTOR_NACE_PREFIXES

# Back-compat alias: six modules imported the private name before it had a public
# home. New code imports scraper.lib.sector_nace directly.
_SECTOR_NACE_PREFIXES = SECTOR_NACE_PREFIXES
```

- [ ] **Step 4: Update the direct importers**

In `batch.py`, `batch_cli.py`, `next_city_cli.py`, `sector_queue_cli.py`, replace
`from scraper.pipeline.orchestrator import _SECTOR_NACE_PREFIXES`
with
`from scraper.lib.sector_nace import SECTOR_NACE_PREFIXES`
and rename usages (`grep -n "_SECTOR_NACE_PREFIXES" <file>` per file; it is a plain rename). Leave test files that import the old name untouched — the alias serves them.

- [ ] **Step 5: Run the full unit suite**

Run: `uv run pytest -q -m "not network and not slow and not integration"`
Expected: PASS (previous count plus the 3 new tests)

- [ ] **Step 6: Gates and commit**

Run: `uv run ruff check src/scraper tests && uv run ruff format --check src/scraper tests && uv run mypy --strict src/scraper/lib/sector_nace.py src/scraper/pipeline/orchestrator.py src/scraper/pipeline/batch.py`
Then commit: `refactor(pipeline): give SECTOR_NACE_PREFIXES a public home in lib/`

---

### Task 2: `BatchReport` records per-sector goudengids errors

The DNS incident was invisible because `_run_goudengids_sector`'s `except Exception` logs and `return 0` — indistinguishable from an empty sector. The report must carry the difference.

**Files:**
- Modify: `src/scraper/pipeline/batch.py` (~line 103 `BatchReport`, ~line 469 `_run_goudengids_sector`, ~line 642 caller)
- Modify: `src/scraper/pipeline/batch_cli.py` (~line 212 `result` dict)
- Test: `tests/unit/pipeline/test_batch.py` (append), `tests/unit/pipeline/test_batch_cli.py` (append)

**Interfaces:**
- Consumes: `BatchReport`, `_run_goudengids_sector`, `_describe(exc)` (exists in batch.py, renders `Type: message`).
- Produces: `BatchReport.goudengids_sector_errors: dict[str, str]` (sector slug → error string); `_run_goudengids_sector` returns `tuple[int, str | None]` (observations, error-or-None). Task 5's verdict logic reads `goudengids_sector_errors`. `batch_cli` summary JSON gains key `"goudengids_sector_errors"`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/pipeline/test_batch.py` (reuse that file's existing fake-pool/monkeypatch idioms — read its header first):

```python
class TestSectorErrorsReachTheReport:
    """A sector that FAILED must be distinguishable from one that found nothing.

    On 2026-08-22/23, DNS failures made all ten sectors of four consecutive runs raise
    inside _run_goudengids_sector, whose `except Exception` returned 0 — the same value
    an empty sector returns. Four runs reported exit=0; two days produced zero
    observations with no alarm.
    """

    async def test_ingest_exception_is_recorded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def _boom(*args: object, **kwargs: object) -> object:
            raise RuntimeError("net::ERR_NAME_NOT_RESOLVED at https://www.goudengids.be/")

        import scraper.sources.goudengids.ingester as ingester_mod

        monkeypatch.setattr(ingester_mod, "ingest_sector_city", _boom)

        from scraper.pipeline.batch import _run_goudengids_sector

        obs, err = await _run_goudengids_sector(
            "hotels", "brugge", "nl", 25, _fake_pool(), _fake_polite_client(),
            structlog.get_logger(),
        )
        assert obs == 0
        assert err is not None and "ERR_NAME_NOT_RESOLVED" in err

    async def test_no_results_is_not_an_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """ValueError = sector not indexed / empty: expected, must stay err=None."""
        async def _empty(*args: object, **kwargs: object) -> object:
            raise ValueError("no results")

        import scraper.sources.goudengids.ingester as ingester_mod

        monkeypatch.setattr(ingester_mod, "ingest_sector_city", _empty)

        from scraper.pipeline.batch import _run_goudengids_sector

        obs, err = await _run_goudengids_sector(
            "hotels", "brugge", "nl", 25, _fake_pool(), _fake_polite_client(),
            structlog.get_logger(),
        )
        assert (obs, err) == (0, None)
```

`_fake_pool()` / `_fake_polite_client()`: use the file's existing fakes if present; otherwise `MagicMock()` suffices — the monkeypatched ingest raises before either is touched. Note `_run_goudengids_sector` imports the ingester *inside* the function (`from scraper.sources.goudengids.ingester import ingest_sector_city`), so the monkeypatch target is the source module attribute, as shown.

Append to `tests/unit/pipeline/test_batch_cli.py`, class `TestSummaryJson`:

```python
    def test_summary_includes_sector_errors(self, tmp_path: Path) -> None:
        target = tmp_path / "s.json"
        _write_summary(str(target), {"goudengids_sector_errors": {"hotels": "boom"}})
        assert json.loads(target.read_text(encoding="utf-8"))["goudengids_sector_errors"] == {
            "hotels": "boom"
        }
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/pipeline/test_batch.py -q -k SectorErrors`
Expected: FAIL — `_run_goudengids_sector` returns `int`, cannot unpack.

- [ ] **Step 3: Implement**

In `BatchReport` (after `goudengids_per_sector`):

```python
    #: sector slug -> error string, for sectors whose scrape RAISED (DNS down, browser
    #: dead). Empty for sectors that merely found nothing — those are not failures.
    goudengids_sector_errors: dict[str, str] = field(default_factory=dict)
```

`_run_goudengids_sector`: change return type to `tuple[int, str | None]`; `return report.observations_inserted, None` on success; `return 0, None` for the not-indexed and `ValueError` branches; the final handler becomes:

```python
    except Exception as exc:
        log.error("goudengids_sector_failed", sector_slug=sector_slug, error=str(exc))
        return 0, _describe(exc)
```

Caller (~line 642): unpack and record —

```python
            obs_count, sector_error = await _run_goudengids_sector(...)
            report.goudengids_per_sector[sector_slug] = obs_count
            if sector_error is not None:
                report.goudengids_sector_errors[sector_slug] = sector_error
```

`batch_cli.py` `result` dict: add `"goudengids_sector_errors": report.goudengids_sector_errors,` after the `goudengids_sectors_scraped` entry.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/pipeline/test_batch.py tests/unit/pipeline/test_batch_cli.py -q`
Expected: PASS, including all pre-existing tests (the unpack change may break existing callers in tests — fix those call sites to unpack the tuple, keeping their assertions).

- [ ] **Step 5: Gates and commit**

Run: full unit suite + ruff + `mypy --strict src/scraper/pipeline/batch.py src/scraper/pipeline/batch_cli.py`
Commit: `feat(batch): record per-sector goudengids errors in the report`

---

### Task 3: Health checks — `pipeline/health.py`

One module answering "is data flowing?", built from the exact signals of the five incidents: wiped staging, dead scrape, dead source (Brave 402), stale exports, unapplied migrations, dead sector slugs.

**Files:**
- Create: `src/scraper/pipeline/health.py`
- Test: `tests/unit/pipeline/test_health.py`

**Interfaces:**
- Consumes: asyncpg pool protocol (only `.fetchrow`/`.fetch` — fakes suffice); `Path` for filesystem checks.
- Produces (Task 4's CLI and Task 6's preflight use these exactly):

```python
@dataclass(frozen=True, slots=True)
class HealthCheck:
    name: str
    ok: bool
    detail: str

async def check_staging(pool: Any) -> HealthCheck
async def check_migrations(pool: Any, migrations_dir: Path) -> HealthCheck
async def check_scrape_freshness(pool: Any, *, max_age_hours: int = 26) -> HealthCheck
async def check_source_freshness(pool: Any, source: str, *, max_age_hours: int) -> HealthCheck
def check_export_freshness(export_dir: Path, *, max_age_hours: int = 26) -> HealthCheck
async def check_dead_slugs(pool: Any, *, min_runs: int = 3, min_cities: int = 2) -> HealthCheck
async def run_health(pool: Any, *, migrations_dir: Path, export_dir: Path) -> list[HealthCheck]
```

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/pipeline/test_health.py
"""Health checks over the signals every recent incident would have tripped.

Five incidents in two weeks shared one shape: a component failed, reported success,
and nothing noticed until the data went stale. Each check below corresponds to one:
staging (UNLOGGED tables wiped by the 2026-08-13 crash recovery, found five days
later), scrape freshness (the uv-stderr and DNS outages), source freshness (Brave
dead on HTTP 402 since 2026-08-21), export freshness (the exporter pinned to
oostende), migrations (009 sat unapplied), dead slugs (four sectors marked done
forever having never returned a card).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from scraper.pipeline.health import (
    check_dead_slugs,
    check_export_freshness,
    check_migrations,
    check_scrape_freshness,
    check_source_freshness,
    check_staging,
)


def _pool(fetchrow: dict[str, Any] | None = None, fetch: list[dict[str, Any]] | None = None) -> MagicMock:
    pool = MagicMock()
    pool.fetchrow = AsyncMock(return_value=fetchrow)
    pool.fetch = AsyncMock(return_value=fetch or [])
    return pool


class TestStaging:
    async def test_populated_staging_is_ok(self) -> None:
        r = await check_staging(_pool(fetchrow={"n": 1948736, "snapshot_date": "2026-05-14"}))
        assert r.ok
        assert "1948736" in r.detail

    async def test_empty_staging_fails(self) -> None:
        """UNLOGGED tables are truncated by crash recovery; this is the detector."""
        r = await check_staging(_pool(fetchrow={"n": 0, "snapshot_date": None}))
        assert not r.ok

    async def test_no_row_fails(self) -> None:
        r = await check_staging(_pool(fetchrow=None))
        assert not r.ok


class TestMigrations:
    async def test_current_schema_is_ok(self, tmp_path: Path) -> None:
        (tmp_path / "001_initial.sql").write_text("--")
        (tmp_path / "009_suppression_list.sql").write_text("--")
        r = await check_migrations(_pool(fetchrow={"v": 9}), tmp_path)
        assert r.ok

    async def test_pending_migration_fails(self, tmp_path: Path) -> None:
        (tmp_path / "009_suppression_list.sql").write_text("--")
        r = await check_migrations(_pool(fetchrow={"v": 8}), tmp_path)
        assert not r.ok
        assert "9" in r.detail


class TestScrapeFreshness:
    async def test_recent_productive_run_is_ok(self) -> None:
        recent = datetime.now(UTC) - timedelta(hours=2)
        r = await check_scrape_freshness(_pool(fetchrow={"last": recent}))
        assert r.ok

    async def test_stale_scrape_fails(self) -> None:
        old = datetime.now(UTC) - timedelta(hours=50)
        r = await check_scrape_freshness(_pool(fetchrow={"last": old}))
        assert not r.ok

    async def test_never_scraped_fails(self) -> None:
        r = await check_scrape_freshness(_pool(fetchrow={"last": None}))
        assert not r.ok


class TestSourceFreshness:
    async def test_stale_brave_fails(self) -> None:
        """Brave returned HTTP 402 from 2026-08-21 on; nothing said so for three days."""
        old = datetime.now(UTC) - timedelta(hours=100)
        r = await check_source_freshness(_pool(fetchrow={"last": old}), "brave", max_age_hours=72)
        assert not r.ok
        assert "brave" in r.name


class TestExportFreshness:
    def test_fresh_export_is_ok(self, tmp_path: Path) -> None:
        (tmp_path / "leads_brugge_2026-08-24.csv").write_text("h\n")
        assert check_export_freshness(tmp_path).ok

    def test_no_exports_fails(self, tmp_path: Path) -> None:
        assert not check_export_freshness(tmp_path).ok


class TestDeadSlugs:
    async def test_flags_never_productive_slugs(self) -> None:
        rows = [{"sector_slug": "informaticabedrijven", "runs": 14, "cities": 2}]
        r = await check_dead_slugs(_pool(fetch=rows))
        assert not r.ok
        assert "informaticabedrijven" in r.detail

    async def test_clean_queue_is_ok(self) -> None:
        r = await check_dead_slugs(_pool(fetch=[]))
        assert r.ok
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/pipeline/test_health.py -q`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement `health.py`**

```python
# src/scraper/pipeline/health.py
"""Data-health checks: is data actually flowing, end to end?

Each check maps to a real incident that reported success while producing nothing.
Exit-code contract for callers: ok=False on any check means the pipeline is running
blind and the nightly should not pretend otherwise.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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
            "staging", False,
            "kbo_stage_enterprise is EMPTY - unclean DB restart wipes UNLOGGED staging; "
            "run: uv run be-leads-kbo-stage KBO_zip/KboOpenData_*.zip",
        )
    return HealthCheck("staging", True, f"{n} entities staged (snapshot {row['snapshot_date']})")


async def check_migrations(pool: Any, migrations_dir: Path) -> HealthCheck:
    available = max(
        (int(m.group(1)) for f in migrations_dir.iterdir() if (m := _MIGRATION_RE.match(f.name))),
        default=0,
    )
    row = await pool.fetchrow("SELECT COALESCE(MAX(version), 0) AS v FROM schema_version")
    applied = int(row["v"]) if row else 0
    if applied < available:
        return HealthCheck(
            "migrations", False,
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
        "SELECT max(started_at) AS last FROM run_log "
        "WHERE source = 'goudengids' AND jobs_done > 0"
    )
    age = _hours_since(row["last"] if row else None)
    if age is None:
        return HealthCheck("scrape", False, "no productive goudengids run on record")
    if age > max_age_hours:
        return HealthCheck("scrape", False, f"last productive scrape {age:.0f}h ago (max {max_age_hours}h)")
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
        return HealthCheck(name, False, f"{source} last productive {age:.0f}h ago (max {max_age_hours}h)")
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/pipeline/test_health.py -q`
Expected: PASS (15 tests)

- [ ] **Step 5: Gates and commit**

ruff + `mypy --strict src/scraper/pipeline/health.py` + full unit suite.
Commit: `feat(health): data-health checks over every recent incident signal`

---

### Task 4: `be-leads-health` CLI

**Files:**
- Modify: `src/scraper/pipeline/health.py` (append `cli_main`)
- Modify: `pyproject.toml` `[project.scripts]`
- Test: `tests/unit/pipeline/test_health.py` (append)

**Interfaces:**
- Consumes: `run_health` from Task 3; `database_url()` from `lib/config`.
- Produces: console script `be-leads-health`; helper `render(checks: list[HealthCheck]) -> tuple[str, int]` (text, exit code) — pure, tested. Exit: 0 all ok, 1 any failure, 2 cannot check (no DSN / DB unreachable).

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/unit/pipeline/test_health.py
from scraper.pipeline.health import HealthCheck, render


class TestRender:
    def test_all_ok_exits_zero(self) -> None:
        text, code = render([HealthCheck("staging", True, "fine")])
        assert code == 0
        assert "OK   staging: fine" in text

    def test_any_failure_exits_one_and_is_listed_first(self) -> None:
        text, code = render(
            [HealthCheck("staging", True, "fine"), HealthCheck("scrape", False, "dead 50h")]
        )
        assert code == 1
        lines = text.splitlines()
        assert lines[0] == "FAIL scrape: dead 50h"
```

- [ ] **Step 2: Verify failure** — `uv run pytest tests/unit/pipeline/test_health.py -q -k Render` → FAIL (no `render`).

- [ ] **Step 3: Implement**

Append to `health.py`:

```python
def render(checks: list[HealthCheck]) -> tuple[str, int]:
    """Failures first — the terminal shows the top of the output, not the bottom."""
    ordered = sorted(checks, key=lambda c: c.ok)
    lines = [f"{'OK  ' if c.ok else 'FAIL'} {c.name}: {c.detail}" for c in ordered]
    return "\n".join(lines), 0 if all(c.ok for c in checks) else 1


def cli_main() -> None:  # pragma: no cover
    import argparse
    import asyncio
    import sys

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
    except OSError as exc:
        print(f"cannot reach the database: {exc}", file=sys.stderr)
        sys.exit(2)

    text, code = render(checks)
    print(text)
    sys.exit(code)
```

pyproject `[project.scripts]`, after `be-leads-export-cities`:
`be-leads-health = "scraper.pipeline.health:cli_main"`

- [ ] **Step 4: Verify pass + live smoke**

Run: `uv run pytest tests/unit/pipeline/test_health.py -q` → PASS.
Then `uv sync` and `uv run be-leads-health` against the dev DB — expect FAIL lines for `source:brave` (dead since 08-21) and `dead-slugs` (4 known), exit 1. That is the check working, not a defect. Record actual output in the commit message body.

- [ ] **Step 5: Gates and commit** — `feat(health): be-leads-health CLI, exit 0/1/2`

---

### Task 5: Nightly verdict + state-line writer (pure logic)

**Files:**
- Create: `src/scraper/pipeline/nightly.py`
- Test: `tests/unit/pipeline/test_nightly.py`

**Interfaces:**
- Consumes: `BatchReport` (with Task 2's `goudengids_sector_errors`).
- Produces (Task 6 uses these):

```python
@dataclass(frozen=True, slots=True)
class Verdict:
    exit_code: int          # 0 ok, 4 sector failures, 5 source failed
    state_line: str         # "END exit=... scraped=a/b failed=n log=..." same grammar as before
    notes: list[str]        # extra "NOTE ..." state lines

def judge_batch(report: BatchReport, *, log_path: str) -> Verdict
def write_state(path: Path, msg: str) -> None   # appends "[<iso-seconds>] <msg>", UTF-8
```

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/pipeline/test_nightly.py
"""Verdict logic for the nightly scrape, formerly ~60 lines of untested PowerShell.

The PowerShell version judged a night by grepping the log for goudengids_sector_done —
sectors ATTEMPTED. Four DNS-dead runs on 2026-08-22/23 therefore logged
'END exit=0 sectors_done=0': two days, zero observations, no alarm. Here the verdict
reads the batch's own report, and lives where pytest can reach it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from scraper.pipeline.batch import BatchReport
from scraper.pipeline.nightly import Verdict, judge_batch, write_state


def _report(**kw: object) -> BatchReport:
    base: dict[str, object] = {
        "city": "brugge",
        "sectors": ["hotels", "kappers"],
        "snapshot_date": None,
        "started_at": datetime.now(UTC),
    }
    base.update(kw)
    return BatchReport(**base)  # type: ignore[arg-type]


class TestJudgeBatch:
    def test_healthy_run_is_zero(self) -> None:
        r = _report(goudengids_per_sector={"hotels": 800, "kappers": 615})
        v = judge_batch(r, log_path="x.log")
        assert v.exit_code == 0
        assert "scraped=2/2" in v.state_line and "failed=0" in v.state_line

    def test_sector_failures_are_exit_4_with_reason(self) -> None:
        """The DNS night must not look like 'nothing left to scrape'."""
        r = _report(
            goudengids_per_sector={"hotels": 0, "kappers": 0},
            goudengids_sector_errors={
                "hotels": "RuntimeError: net::ERR_NAME_NOT_RESOLVED",
                "kappers": "RuntimeError: net::ERR_NAME_NOT_RESOLVED",
            },
        )
        v = judge_batch(r, log_path="x.log")
        assert v.exit_code == 4
        assert "scraped=0/2" in v.state_line and "failed=2" in v.state_line
        assert "ERR_NAME_NOT_RESOLVED" in v.state_line

    def test_source_failure_is_exit_5(self) -> None:
        r = _report(
            goudengids_per_sector={"hotels": 10, "kappers": 5},
            sources_failed={"ddg_brave": "terminal HTTP 402"},
        )
        v = judge_batch(r, log_path="x.log")
        assert v.exit_code == 5
        assert any("ddg_brave" in n for n in v.notes)

    def test_sector_failures_outrank_source_failures(self) -> None:
        r = _report(
            goudengids_per_sector={"hotels": 0},
            goudengids_sector_errors={"hotels": "boom"},
            sources_failed={"ddg_brave": "terminal HTTP 402"},
        )
        assert judge_batch(r, log_path="x.log").exit_code == 4

    def test_empty_but_error_free_night_is_zero(self) -> None:
        """All sectors deduped/empty with no errors = a quiet night, not a failure."""
        r = _report(goudengids_per_sector={"hotels": 0, "kappers": 0})
        assert judge_batch(r, log_path="x.log").exit_code == 0


class TestWriteState:
    def test_appends_bracketed_utf8_line(self, tmp_path: Path) -> None:
        p = tmp_path / "state.log"
        write_state(p, "START city=brugge limit=10")
        write_state(p, "END exit=0")
        lines = p.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        assert lines[0].endswith("] START city=brugge limit=10")
        assert lines[0].startswith("[20")
```

- [ ] **Step 2: Verify failure** — `uv run pytest tests/unit/pipeline/test_nightly.py -q` → FAIL (no module).

- [ ] **Step 3: Implement**

```python
# src/scraper/pipeline/nightly.py
"""Nightly scrape orchestration: city, sectors, batch, verdict.

This logic lived in scripts/nightly_scrape.ps1, where no test could reach it and
where every silent-failure incident of 2026-08 originated. PowerShell keeps only
OS glue (Docker preflight, scheduling); the decisions live here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scraper.pipeline.batch import BatchReport

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
```

- [ ] **Step 4: Verify pass** — `uv run pytest tests/unit/pipeline/test_nightly.py -q` → PASS (7 tests).

- [ ] **Step 5: Gates and commit** — `feat(nightly): batch verdict as tested Python, exit-code contract kept`

---

### Task 6: `run_nightly` + `be-leads-nightly` CLI

**Files:**
- Modify: `src/scraper/pipeline/nightly.py` (append `select_city`, `run_nightly`, `cli_main`)
- Modify: `pyproject.toml` `[project.scripts]`
- Test: `tests/unit/pipeline/test_nightly.py` (append)

**Interfaces:**
- Consumes: Task 5's `Verdict`/`write_state`; `sector_queue` functions; `SECTOR_NACE_PREFIXES` (Task 1); `BatchConfig`/`run_batch`; `check_staging`/`check_migrations` (Task 3); `_resolve_api_keys` from `batch_cli`; `PoliteClient`, `load_from_toml`, `PER_HOST_TOML`.
- Produces: console script `be-leads-nightly`; `async def run_nightly(pool, polite_client, *, city, limit, within_hours, state_log, log_path, brave_key, nbb_key, dsn, migrations_dir) -> int` — testable with fakes; `async def select_city(pool, cities, *, within_hours) -> str | None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/pipeline/test_nightly.py`:

```python
from unittest.mock import AsyncMock, MagicMock

import pytest

from scraper.pipeline.nightly import run_nightly


def _mk_pool() -> MagicMock:
    pool = MagicMock()
    pool.fetch = AsyncMock(return_value=[])
    pool.fetchrow = AsyncMock(return_value=None)
    return pool


class TestRunNightly:
    async def test_empty_staging_exits_6_before_touching_the_network(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Aug 18-20: staging wiped, every run burned WAF budget to fail in 1s.
        The preflight must stop the night before the browser ever starts."""
        import scraper.pipeline.nightly as mod

        async def _staging_dead(pool: object) -> object:
            from scraper.pipeline.health import HealthCheck

            return HealthCheck("staging", False, "kbo_stage_enterprise is EMPTY")

        batch = AsyncMock()  # must never be awaited
        monkeypatch.setattr(mod, "check_staging", _staging_dead)
        monkeypatch.setattr(mod, "run_batch", batch)

        state = tmp_path / "state.log"
        code = await run_nightly(
            _mk_pool(), MagicMock(), city="brugge", limit=10, within_hours=None,
            state_log=state, log_path=str(tmp_path / "run.log"),
            brave_key=None, nbb_key=None, dsn="postgresql://x", migrations_dir=tmp_path,
        )
        assert code == 6
        assert "reason=preflight" in state.read_text(encoding="utf-8")
        batch.assert_not_awaited()

    async def test_no_pending_sectors_is_a_clean_zero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import scraper.pipeline.nightly as mod
        from scraper.pipeline.health import HealthCheck

        async def _ok(*a: object, **k: object) -> object:
            return HealthCheck("x", True, "fine")

        async def _all_done(pool: object, city: str, **k: object) -> set[str]:
            from scraper.lib.sector_nace import SECTOR_NACE_PREFIXES

            return set(SECTOR_NACE_PREFIXES)

        monkeypatch.setattr(mod, "check_staging", _ok)
        monkeypatch.setattr(mod, "check_migrations", _ok)
        monkeypatch.setattr(mod, "fetch_completed_sectors", _all_done)

        state = tmp_path / "state.log"
        code = await run_nightly(
            _mk_pool(), MagicMock(), city="brugge", limit=10, within_hours=None,
            state_log=state, log_path=str(tmp_path / "run.log"),
            brave_key=None, nbb_key=None, dsn="postgresql://x", migrations_dir=tmp_path,
        )
        assert code == 0
        assert "fully covered" in state.read_text(encoding="utf-8")

    async def test_batch_verdict_reaches_the_state_log(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import scraper.pipeline.nightly as mod
        from datetime import UTC, datetime
        from scraper.pipeline.batch import BatchReport
        from scraper.pipeline.health import HealthCheck

        async def _ok(*a: object, **k: object) -> object:
            return HealthCheck("x", True, "fine")

        async def _none_done(pool: object, city: str, **k: object) -> set[str]:
            return set()

        async def _batch(config: object, pool: object, client: object) -> BatchReport:
            return BatchReport(
                city="brugge", sectors=["hotels"], snapshot_date=None,
                started_at=datetime.now(UTC),
                goudengids_per_sector={"hotels": 0},
                goudengids_sector_errors={"hotels": "RuntimeError: ERR_NAME_NOT_RESOLVED"},
            )

        monkeypatch.setattr(mod, "check_staging", _ok)
        monkeypatch.setattr(mod, "check_migrations", _ok)
        monkeypatch.setattr(mod, "fetch_completed_sectors", _none_done)
        monkeypatch.setattr(mod, "run_batch", _batch)

        state = tmp_path / "state.log"
        code = await run_nightly(
            _mk_pool(), MagicMock(), city="brugge", limit=1, within_hours=None,
            state_log=state, log_path=str(tmp_path / "run.log"),
            brave_key=None, nbb_key=None, dsn="postgresql://x", migrations_dir=tmp_path,
        )
        assert code == 4
        text = state.read_text(encoding="utf-8")
        assert "SCRAPE 1 sectors" in text
        assert "reason=sector-failures :: RuntimeError: ERR_NAME_NOT_RESOLVED" in text
```

- [ ] **Step 2: Verify failure** — `-k RunNightly` → FAIL (`run_nightly` missing).

- [ ] **Step 3: Implement**

Append to `nightly.py` (module-level imports so monkeypatching module attributes works — import `check_staging`, `check_migrations`, `fetch_completed_sectors`, `fetch_completed_by_city`, `select_next_city`, `select_pending_sectors`, `goudengids_unscrapeable_sectors`, `load_rotation_cities`, `run_batch`, `BatchConfig`, `SECTOR_NACE_PREFIXES` at top of file; drop the `TYPE_CHECKING` guard for `BatchReport` if now imported directly):

```python
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
```

Then `cli_main()` (marked `# pragma: no cover`, mirroring `batch_cli` conventions exactly):

```python
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

    parser = argparse.ArgumentParser(description="One scheduled nightly scrape: city, sectors, batch, verdict.")
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
                    pool, polite_client, city=city, limit=args.limit,
                    within_hours=args.within_hours, state_log=state_log,
                    log_path=str(log_dir / f"nightly_run_{stamp}.log"),
                    brave_key=brave_key, nbb_key=nbb_key, dsn=dsn,
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
```

pyproject: `be-leads-nightly = "scraper.pipeline.nightly:cli_main"`.

NOTE: verify `load_from_toml`'s import path and signature against `batch_cli.py` before writing (it is used there around line 200); copy that call verbatim. Also confirm `_resolve_api_keys(None, None)` matches its signature in `batch_cli.py:97`.

- [ ] **Step 4: Verify** — full `tests/unit/pipeline/test_nightly.py` PASS; `uv sync`; smoke: `uv run be-leads-nightly --help` prints usage.

- [ ] **Step 5: Gates and commit** — `feat(nightly): be-leads-nightly entry point owning the whole night`

---

### Task 7: Slim `nightly_scrape.ps1` to OS glue

**Files:**
- Modify: `scripts/nightly_scrape.ps1`

**Interfaces:**
- Consumes: `be-leads-nightly` (Task 6) — its exit codes 0/1/4/5/6 pass through; PS adds 3 (db unavailable) itself.
- Produces: same scheduled-task contract (path and parameters unchanged; Task Scheduler needs no edit).

- [ ] **Step 1: Rewrite the tail of the script**

Keep unchanged: header comment (update the exit-codes list to add `6  data preflight failed (health check inside be-leads-nightly)`), `param(...)`, repo/LogDir resolution, `Write-State`, `Invoke-Uv`, the `START` line, the `trap`, the whole Database-preflight section, and the `-CheckOnly` exit. DELETE everything from the comment `# Which city is the rotation on?` to the end of the file, and replace with:

```powershell
# Everything from here down - city selection, sector queue, batch, verdict - lives in
# Python now (src/scraper/pipeline/nightly.py), where pytest reaches it. This script
# is OS glue: scheduling, Docker preflight, and relaying an exit code. The Python side
# appends to the same state log in the same format, so the history stays greppable.
$runLog = Join-Path $LogDir "nightly_run_${stamp}.log"

$argList = @('run', 'be-leads-nightly', '--limit', $Limit, '--state-log', $state)
if ($City) { $argList += @('--city', $City) }

$prevEap = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
try {
    & uv @argList *>> $runLog
    $code = $LASTEXITCODE
} finally {
    $ErrorActionPreference = $prevEap
}

exit $code
```

- [ ] **Step 2: Verify ASCII and syntax**

Run (Bash): `LC_ALL=C grep -c '[^ -~]' scripts/nightly_scrape.ps1` → expect `0`.
Run (PowerShell): `$null = [System.Management.Automation.PSParser]::Tokenize((Get-Content -Raw 'scripts/nightly_scrape.ps1'), [ref]$null); 'syntax ok'` → `syntax ok`.

- [ ] **Step 3: Live dry-run**

Run: `powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\nightly_scrape.ps1 -CheckOnly` → `Preflight OK: database reachable.` exit 0.
Then confirm the state log gained `START` + `END exit=0 reason=check-only` lines and NOTHING else.

- [ ] **Step 4: Commit** — `refactor(scripts): nightly_scrape.ps1 is OS glue; decisions moved to be-leads-nightly`

The first scheduled run (02:30/14:30) is the real end-to-end verification; check `logs/nightly_scrape.log` after it fires and confirm a `CITY`/`SCRAPE`/`END exit=` sequence written by Python.

---

### Task 8: Config-vs-reality tests

The postcode-map incident happened because config files were never checked against anything. Same treatment for the two remaining config surfaces.

**Files:**
- Create: `tests/unit/pipeline/test_config_reality.py`

**Interfaces:**
- Consumes: `load_rotation_cities`, `get_postal_codes`, `SECTOR_NACE_PREFIXES`, `goudengids_unscrapeable_sectors`, `SECTORS_TOML`.

- [ ] **Step 1: Write the tests (they should PASS against current config — they are regression guards)**

```python
# tests/unit/pipeline/test_config_reality.py
"""Config files checked against each other and against the code that consumes them.

city_map.toml drifted unvalidated until 13 of 15 cities were wrong. These tests give
the remaining config surfaces the same guard the postcode map now has: a slug that
resolves to nothing, a duplicate, or a NACE prefix in the wrong format fails the
build instead of silently producing empty scrapes.
"""

from __future__ import annotations

import tomllib

from scraper.lib.data_paths import SECTORS_TOML
from scraper.lib.sector_nace import SECTOR_NACE_PREFIXES
from scraper.pipeline.city_map import get_postal_codes
from scraper.pipeline.sector_queue import goudengids_unscrapeable_sectors, load_rotation_cities


def _sectors_toml() -> dict[str, dict[str, str]]:
    with SECTORS_TOML.open("rb") as fh:
        return tomllib.load(fh)


class TestRotationCities:
    def test_every_rotation_city_resolves_to_postcodes(self) -> None:
        """A rotation city with no postcodes scrapes with the filter silently OFF."""
        missing = [c for c in load_rotation_cities() if not get_postal_codes(c)]
        assert missing == [], f"rotation cities with no postcodes: {missing}"

    def test_rotation_is_nonempty_and_unique(self) -> None:
        cities = load_rotation_cities()
        assert cities, "empty rotation means the nightly does nothing forever"
        assert len(set(cities)) == len(cities)


class TestSectorConfig:
    def test_every_nace_sector_is_scrapeable_or_declared_unscrapeable(self) -> None:
        """A sector in the NACE map but absent from sectors.toml can be selected by
        the queue yet never resolves to a goudengids slug - it burns a queue slot
        every night without a single request succeeding."""
        toml_keys = set(_sectors_toml())
        unscrapeable = goudengids_unscrapeable_sectors(sorted(SECTOR_NACE_PREFIXES))
        orphans = [
            s for s in SECTOR_NACE_PREFIXES if s not in toml_keys and s not in unscrapeable
        ]
        assert orphans == [], f"sectors with NACE codes but no goudengids mapping: {orphans}"

    def test_sectors_toml_slugs_are_unique_and_wellformed(self) -> None:
        seen: dict[str, str] = {}
        for key, entry in _sectors_toml().items():
            nl = entry.get("nl_slug", "")
            assert nl, f"{key} has no nl_slug"
            assert nl == nl.strip().lower(), f"{key}: nl_slug {nl!r} not normalised"
            assert nl not in seen, f"nl_slug {nl!r} used by both {seen[nl]} and {key}"
            seen[nl] = key
```

- [ ] **Step 2: Run them**

Run: `uv run pytest tests/unit/pipeline/test_config_reality.py -q`
Expected: PASS. If `test_every_nace_sector_is_scrapeable_or_declared_unscrapeable` FAILS, that is a real pre-existing config hole: report the orphan list in the commit message and fix the config (add the sectors.toml entry or the unscrapeable declaration), not the test.

- [ ] **Step 3: Commit** — `test(config): rotation and sector config checked against reality`

---

### Task 9: CHANGELOG, full gates, push

**Files:**
- Modify: `CHANGELOG.md` (one `### Added — the pipeline now notices when it is failing` section under `## [Unreleased]` covering: be-leads-health; be-leads-nightly + slimmed ps1 with exit-code table; BatchReport.goudengids_sector_errors; sector_nace promotion; config-reality tests. State the incident each piece prevents, in the style of the existing entries.)

- [ ] **Step 1: Full suite including integration** — `uv run pytest -q -m "not network"` (needs live Postgres) → all pass.
- [ ] **Step 2: Coverage gate** — `uv run pytest --cov=src/scraper --cov-fail-under=85 -q -m "not network and not slow and not integration"` → ≥85%.
- [ ] **Step 3: Repo-wide gates on changed files** — ruff check, ruff format --check, `mypy --strict src/scraper/pipeline/health.py src/scraper/pipeline/nightly.py src/scraper/pipeline/batch.py src/scraper/lib/sector_nace.py`.
- [ ] **Step 4: Live smoke** — `uv run be-leads-health` (expect FAIL lines for brave + dead-slugs, exit 1 — the known open issues, correctly reported).
- [ ] **Step 5: Commit CHANGELOG, push** — `git push origin fix/silent-nightly-failures`; confirm `git rev-list --left-right --count @{u}...HEAD` → `0 0`.

---

## Out of scope (decided, do not drift into)

- **export.py relocation** — cut: `_aggregate_row`/`_financial_amount` are a shared UI/export family; the current boundary is where the shared code lives.
- **jobs table activation, queues, containers** — YAGNI.
- **Brave 402** — account/billing action for the operator, not code; `be-leads-health` and exit 5 now surface it.
- **Deleting `orchestrator.py`** — it still owns the single-run `be-leads-pipeline` path; only its config-ownership was removed.
- **Scheduled-task changes** — none needed; the ps1 path and parameters are unchanged.
