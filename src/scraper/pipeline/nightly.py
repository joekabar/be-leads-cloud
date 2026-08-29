"""Nightly scrape orchestration: city, sectors, batch, verdict.

This logic lived in scripts/nightly_scrape.ps1, where no test could reach it and
where every silent-failure incident of 2026-08 originated. PowerShell keeps only
OS glue (Docker preflight, scheduling); the decisions live here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

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
