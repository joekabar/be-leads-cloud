"""Unit tests for ui.queries.snapshots (mock pool — no DB required)."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock

from scraper.ui.queries.snapshots import (
    count_new_kbos_between,
    count_new_kbos_since,
    fetch_new_kbo_details_between,
    fetch_new_kbo_details_since,
    get_latest_progress,
    list_staged_snapshots,
)

_D1 = date(2026, 3, 1)
_D2 = date(2026, 4, 1)
_D3 = date(2026, 5, 1)


def _mock_pool(fetch_return=None, fetchval_return=None, fetchrow_return=None):
    pool = MagicMock()
    pool.fetch = AsyncMock(return_value=fetch_return or [])
    pool.fetchval = AsyncMock(return_value=fetchval_return)
    pool.fetchrow = AsyncMock(return_value=fetchrow_return)
    return pool


class TestListStagedSnapshots:
    async def test_empty_returns_empty_list(self) -> None:
        pool = _mock_pool(fetch_return=[])
        result = await list_staged_snapshots(pool)
        assert result == []

    async def test_single_snapshot_returned(self) -> None:
        row = MagicMock()
        row.__getitem__ = lambda self, k: _D2 if k == "snapshot_date" else 42
        pool = _mock_pool(fetch_return=[row])
        result = await list_staged_snapshots(pool)
        assert len(result) == 1
        assert result[0]["snapshot_date"] == _D2
        assert result[0]["enterprise_count"] == 42

    async def test_multiple_snapshots_ordered(self) -> None:
        rows = []
        for d, n in [(_D3, 100), (_D2, 80), (_D1, 60)]:
            r = MagicMock()
            r.__getitem__ = lambda self, k, _d=d, _n=n: _d if k == "snapshot_date" else _n
            rows.append(r)
        pool = _mock_pool(fetch_return=rows)
        result = await list_staged_snapshots(pool)
        assert len(result) == 3
        assert result[0]["enterprise_count"] == 100


class TestCountNewKbosBetween:
    async def test_returns_zero_when_none(self) -> None:
        pool = _mock_pool(fetchval_return=None)
        result = await count_new_kbos_between(pool, _D1, _D2)
        assert result == 0

    async def test_returns_count(self) -> None:
        pool = _mock_pool(fetchval_return=57)
        result = await count_new_kbos_between(pool, _D1, _D2)
        assert result == 57

    async def test_passes_correct_date_order(self) -> None:
        pool = _mock_pool(fetchval_return=10)
        await count_new_kbos_between(pool, _D1, _D2)
        call_args = pool.fetchval.call_args
        # latest_date=$1, prior_date=$2 per the query
        assert _D2 in call_args.args
        assert _D1 in call_args.args


class TestCountNewKbosSince:
    async def test_returns_zero_when_none(self) -> None:
        pool = _mock_pool(fetchval_return=None)
        result = await count_new_kbos_since(pool, _D1)
        assert result == 0

    async def test_returns_count(self) -> None:
        pool = _mock_pool(fetchval_return=123)
        result = await count_new_kbos_since(pool, _D2)
        assert result == 123


class TestFetchNewKboDetailsBetween:
    async def test_empty_returns_empty_list(self) -> None:
        pool = _mock_pool(fetch_return=[])
        result = await fetch_new_kbo_details_between(pool, _D1, _D2)
        assert result == []

    async def test_rows_converted_to_dicts(self) -> None:
        row = MagicMock()
        row.keys = MagicMock(return_value=["entity_number", "name"])
        row.__iter__ = MagicMock(return_value=iter(["0439401387", "Bellock"]))
        # Use dict() conversion as in the real code
        row_dict = {"entity_number": "0439401387", "name": "Bellock"}
        pool = _mock_pool(fetch_return=[row_dict])
        pool.fetch = AsyncMock(return_value=[row_dict])
        result = await fetch_new_kbo_details_between(pool, _D1, _D2)
        assert len(result) == 1
        assert result[0]["entity_number"] == "0439401387"

    async def test_custom_limit_passed(self) -> None:
        pool = _mock_pool(fetch_return=[])
        await fetch_new_kbo_details_between(pool, _D1, _D2, limit=50)
        call_args = pool.fetch.call_args
        assert 50 in call_args.args


class TestFetchNewKboDetailsSince:
    async def test_returns_empty_when_no_snapshots_after_date(self) -> None:
        pool = _mock_pool(fetchval_return=None)
        result = await fetch_new_kbo_details_since(pool, _D1)
        assert result == []

    async def test_returns_rows_when_snapshot_exists(self) -> None:
        row_dict = {"entity_number": "0439401387", "name": "Bellock"}
        pool = MagicMock()
        pool.fetchval = AsyncMock(return_value=_D2)
        pool.fetch = AsyncMock(return_value=[row_dict])
        result = await fetch_new_kbo_details_since(pool, _D1)
        assert len(result) == 1


class TestGetLatestProgress:
    async def test_returns_none_when_no_row(self) -> None:
        pool = _mock_pool(fetchrow_return=None)
        result = await get_latest_progress(pool)
        assert result is None

    async def test_returns_dict_when_row_present(self) -> None:
        row = {
            "run_id": "abc",
            "phase": "phase_a",
            "stage": "enterprise",
            "current_val": 1000,
            "total_val": 5000,
            "message": "staging",
            "updated_at": None,
            "source": "kbo_dump",
            "started_at": None,
        }
        pool = _mock_pool(fetchrow_return=row)
        result = await get_latest_progress(pool)
        assert result is not None
        assert result["phase"] == "phase_a"
