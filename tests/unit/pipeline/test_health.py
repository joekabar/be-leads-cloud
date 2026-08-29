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
    HealthCheck,
    check_dead_slugs,
    check_export_freshness,
    check_migrations,
    check_scrape_freshness,
    check_source_freshness,
    check_staging,
    render,
    run_health,
)


def _pool(
    fetchrow: dict[str, Any] | None = None, fetch: list[dict[str, Any]] | None = None
) -> MagicMock:
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


class TestRunHealth:
    """Locks the roster of checks run_health assembles, not their pass/fail verdicts:
    a future check silently dropped (or a duplicate silently added) from this list
    would not be caught by any single check_* test, since each of those exercises
    its function in isolation."""

    async def test_returns_exactly_the_six_named_checks(self, tmp_path: Path) -> None:
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        export_dir = tmp_path / "exports"
        export_dir.mkdir()

        pool = _pool(fetchrow=None, fetch=[])

        checks = await run_health(pool, migrations_dir=migrations_dir, export_dir=export_dir)

        assert len(checks) == 6
        assert {c.name for c in checks} == {
            "staging",
            "migrations",
            "scrape",
            "source:brave",
            "exports",
            "dead-slugs",
        }
