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
from scraper.pipeline.nightly import judge_batch, write_state


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
