"""Unit tests for pipeline/progress.py — ProgressReporter."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

from scraper.pipeline.progress import ProgressReporter


async def test_progress_report_success() -> None:
    """Normal path: pool.execute called once, no exception raised."""
    pool = AsyncMock()
    pool.execute = AsyncMock()
    reporter = ProgressReporter(pool=pool, run_id=uuid.uuid4())
    await reporter.report("phase_a", "test", message="ok")
    pool.execute.assert_called_once()


async def test_progress_report_exception_is_swallowed() -> None:
    """Lines 58-59: pool.execute raising is caught and logged, not re-raised."""
    pool = AsyncMock()
    pool.execute = AsyncMock(side_effect=RuntimeError("db offline"))
    reporter = ProgressReporter(pool=pool, run_id=uuid.uuid4())
    await reporter.report("phase_a", "test", message="fail")
