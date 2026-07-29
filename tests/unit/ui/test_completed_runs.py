"""Unit tests for fetch_completed_runs.

The search page previously rendered results only from st.session_state, so a batch
run finished on the CLI (or in another browser session) was invisible in the UI —
you had to re-run the whole pipeline to see leads that already existed.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

from scraper.ui.data import fetch_completed_runs

_A = datetime(2026, 7, 26, 19, 43, 2, tzinfo=UTC)
_B = datetime(2026, 7, 25, 7, 34, 49, tzinfo=UTC)


def _rec(**kw: object) -> dict[str, object]:
    base: dict[str, object] = {
        "run_id": uuid4(),
        "sector_slug": "tuinaanleggers",
        "city_slug": "oostende",
        "source": "goudengids",
        "started_at": _A,
        "ended_at": _A,
        "jobs_done": 62,
    }
    base.update(kw)
    return base


class TestFetchCompletedRuns:
    def test_returns_rows_newest_first(self) -> None:
        pool = AsyncMock()
        pool.fetch.return_value = [_rec(), _rec(started_at=_B, sector_slug="elektriciens")]
        rows = asyncio.run(fetch_completed_runs(pool))
        assert [r["sector_slug"] for r in rows] == ["tuinaanleggers", "elektriciens"]
        assert rows[0]["city_slug"] == "oostende"
        assert rows[0]["jobs_done"] == 62

    def test_empty_when_no_runs(self) -> None:
        pool = AsyncMock()
        pool.fetch.return_value = []
        assert asyncio.run(fetch_completed_runs(pool)) == []

    def test_limit_is_passed_to_query(self) -> None:
        pool = AsyncMock()
        pool.fetch.return_value = []
        asyncio.run(fetch_completed_runs(pool, limit=5))
        assert pool.fetch.await_args.args[-1] == 5

    def test_only_finished_runs_requested(self) -> None:
        """A run still in flight has no ended_at and must not be offered."""
        pool = AsyncMock()
        pool.fetch.return_value = []
        asyncio.run(fetch_completed_runs(pool))
        sql = pool.fetch.await_args.args[0]
        assert "ended_at IS NOT NULL" in sql

    def test_requires_city_only(self) -> None:
        """City scopes a run; sector does not.

        A NACE-only run (manual codes, no sector selected) writes sector_slug NULL but
        still has a city. Requiring a sector would hide exactly the searches the new
        NACE input makes possible. Enrichment runs (kbopub/nbb) have neither and stay
        excluded by the city requirement alone.
        """
        pool = AsyncMock()
        pool.fetch.return_value = []
        asyncio.run(fetch_completed_runs(pool))
        sql = pool.fetch.await_args.args[0]
        assert "city_slug IS NOT NULL" in sql
        assert "sector_slug IS NOT NULL" not in sql

    def test_nace_only_run_is_returned(self) -> None:
        pool = AsyncMock()
        pool.fetch.return_value = [_rec(sector_slug=None, source="kbo_dump", jobs_done=1811)]
        rows = asyncio.run(fetch_completed_runs(pool))
        assert rows[0]["sector_slug"] is None
        assert rows[0]["city_slug"] == "oostende"
