"""Verdict logic for the nightly scrape, formerly ~60 lines of untested PowerShell.

The PowerShell version judged a night by grepping the log for goudengids_sector_done —
sectors ATTEMPTED. Four DNS-dead runs on 2026-08-22/23 therefore logged
'END exit=0 sectors_done=0': two days, zero observations, no alarm. Here the verdict
reads the batch's own report, and lives where pytest can reach it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from scraper.pipeline.batch import BatchReport
from scraper.pipeline.nightly import judge_batch, run_nightly, write_state


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
            _mk_pool(),
            MagicMock(),
            city="brugge",
            limit=10,
            within_hours=None,
            state_log=state,
            log_path=str(tmp_path / "run.log"),
            brave_key=None,
            nbb_key=None,
            dsn="postgresql://x",
            migrations_dir=tmp_path,
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
            _mk_pool(),
            MagicMock(),
            city="brugge",
            limit=10,
            within_hours=None,
            state_log=state,
            log_path=str(tmp_path / "run.log"),
            brave_key=None,
            nbb_key=None,
            dsn="postgresql://x",
            migrations_dir=tmp_path,
        )
        assert code == 0
        assert "fully covered" in state.read_text(encoding="utf-8")

    async def test_batch_verdict_reaches_the_state_log(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from datetime import UTC, datetime

        import scraper.pipeline.nightly as mod
        from scraper.pipeline.batch import BatchReport
        from scraper.pipeline.health import HealthCheck

        async def _ok(*a: object, **k: object) -> object:
            return HealthCheck("x", True, "fine")

        async def _none_done(pool: object, city: str, **k: object) -> set[str]:
            return set()

        async def _batch(config: object, pool: object, client: object) -> BatchReport:
            return BatchReport(
                city="brugge",
                sectors=["hotels"],
                snapshot_date=None,
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
            _mk_pool(),
            MagicMock(),
            city="brugge",
            limit=1,
            within_hours=None,
            state_log=state,
            log_path=str(tmp_path / "run.log"),
            brave_key=None,
            nbb_key=None,
            dsn="postgresql://x",
            migrations_dir=tmp_path,
        )
        assert code == 4
        text = state.read_text(encoding="utf-8")
        assert "SCRAPE 1 sectors" in text
        assert "reason=sector-failures :: RuntimeError: ERR_NAME_NOT_RESOLVED" in text


class TestCliMainUnhandledTrap:
    def test_setup_failure_before_asyncio_run_still_logs_and_exits_1(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A missing DATABASE_URL used to crash cli_main with a raw traceback before
        execution ever reached the try/except around asyncio.run: no state-log line,
        no exit-code contract, just a bare stack trace. After Task 7 this CLI is the
        only nightly entry point, so a setup failure (load_settings et al.) must land
        the same END exit=1 line a mid-run failure does."""
        import sys

        from scraper.lib.errors import ConfigError

        def _raise_config_error(*_a: object, **_k: object) -> None:
            raise ConfigError("DATABASE_URL is not set.")

        # cli_main imports load_settings from scraper.lib.config *inside* the function
        # body, so the patch target is the source module, not scraper.pipeline.nightly.
        monkeypatch.setattr("scraper.lib.config.load_settings", _raise_config_error)

        state = tmp_path / "state.log"
        monkeypatch.setattr(sys, "argv", ["be-leads-nightly", "--state-log", str(state)])

        from scraper.pipeline.nightly import cli_main

        with pytest.raises(SystemExit) as exc_info:
            cli_main()
        assert exc_info.value.code == 1
        assert "END exit=1 reason=unhandled" in state.read_text(encoding="utf-8")
