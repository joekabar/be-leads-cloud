"""Loading a past run must be scoped by run_id, not by city.

Without a sector, KBO discovery fell back to "every company whose address city matches"
— for Antwerpen that is tens of thousands of companies, all aggregated in Python. The
run itself knows exactly which KBOs it touched, so it is both cheaper and more correct.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

from scraper.ui.data import fetch_results_for_run

_STARTED = datetime(2026, 7, 27, 6, 19, 0, tzinfo=UTC)


class TestRunIdScoping:
    def test_run_id_discovers_kbos_by_run_not_city(self) -> None:
        run_id = uuid4()
        pool = AsyncMock()
        pool.fetch.return_value = []

        asyncio.run(fetch_results_for_run(pool, _STARTED, run_id=run_id, city="antwerpen"))

        sql = pool.fetch.await_args_list[0].args[0]
        assert "run_id" in sql
        assert "ILIKE" not in sql, "must not fall back to the city-wide scan"
        assert run_id in pool.fetch.await_args_list[0].args

    def test_without_run_id_behaviour_is_unchanged(self) -> None:
        """The live-run path (no run_id) still discovers by city."""
        pool = AsyncMock()
        pool.fetch.return_value = []

        asyncio.run(fetch_results_for_run(pool, _STARTED, city="antwerpen"))

        sql = pool.fetch.await_args_list[0].args[0]
        assert "ILIKE" in sql

    def test_no_kbos_returns_empty_without_further_queries(self) -> None:
        pool = AsyncMock()
        pool.fetch.return_value = []
        rows = asyncio.run(fetch_results_for_run(pool, _STARTED, run_id=uuid4()))
        assert rows == []
