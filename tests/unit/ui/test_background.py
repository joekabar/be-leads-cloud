"""Tests for ui/background.py — daemon-thread async job + queue polling."""

from __future__ import annotations

import time
from typing import Any

from scraper.ui.background import poll_job, start_async_job


def _drain(q: Any, timeout: float = 2.0) -> dict[str, Any]:
    """Poll until the job posts a result or the timeout elapses."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        msg = poll_job(q)
        if msg is not None:
            return msg
        time.sleep(0.01)
    raise AssertionError("background job did not finish within timeout")


class TestStartAsyncJob:
    def test_success_delivers_result(self) -> None:
        async def _job() -> int:
            return 42

        q = start_async_job(_job)
        msg = _drain(q)
        assert msg == {"status": "success", "result": 42}

    def test_exception_delivers_error_string(self) -> None:
        async def _job() -> None:
            raise RuntimeError("boom")

        q = start_async_job(_job)
        msg = _drain(q)
        assert msg["status"] == "error"
        assert "boom" in msg["error"]


class TestPollJob:
    def test_poll_none_queue_returns_none(self) -> None:
        assert poll_job(None) is None

    def test_poll_empty_queue_returns_none(self) -> None:
        async def _slow() -> int:
            import asyncio

            await asyncio.sleep(0.5)
            return 1

        q = start_async_job(_slow)
        # Immediately after start the queue is still empty.
        assert poll_job(q) is None
