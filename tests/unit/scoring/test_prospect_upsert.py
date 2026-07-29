"""refresh_prospect_scores must not send ~2M parameter tuples in one executemany.

Observed in production: Phase F wedged for 25+ minutes on a single
``INSERT INTO prospect_scores`` — Postgres sat in state=active/ClientRead while the
client burned 0% CPU and held 4.3 GB. The same call had taken 110 s on earlier runs, so
it was stuck, not slow. Unbounded single calls also have no timeout, so they hang
indefinitely instead of failing fast.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from scraper.lib.errors import ScoringTimeoutError
from scraper.scoring.prospect import _chunked, refresh_prospect_scores


class TestChunked:
    def test_splits_into_even_chunks(self) -> None:
        assert list(_chunked([1, 2, 3, 4], 2)) == [[1, 2], [3, 4]]

    def test_last_chunk_may_be_short(self) -> None:
        assert list(_chunked([1, 2, 3], 2)) == [[1, 2], [3]]

    def test_empty_input_yields_nothing(self) -> None:
        assert list(_chunked([], 10)) == []

    def test_chunk_larger_than_input(self) -> None:
        assert list(_chunked([1, 2], 100)) == [[1, 2]]

    def test_rejects_non_positive_chunk_size(self) -> None:
        with pytest.raises(ValueError, match="chunk_size"):
            list(_chunked([1, 2], 0))


def _pool_with_rows(n: int) -> AsyncMock:
    """A pool returning n distinct KBOs, each with one 'status' field row."""
    pool = AsyncMock()
    pool.fetch.return_value = [
        {"kbo_number": f"{i:010d}", "field": "status", "value": {"value": "active"}}
        for i in range(n)
    ]

    conn = AsyncMock()
    acquire_cm = MagicMock()
    acquire_cm.__aenter__ = AsyncMock(return_value=conn)
    acquire_cm.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=acquire_cm)

    pool._conn = conn  # type: ignore[attr-defined]
    return pool


class TestChunkedUpsert:
    def test_upsert_is_split_into_bounded_batches(self) -> None:
        pool = _pool_with_rows(25)
        n = asyncio.run(refresh_prospect_scores(pool, chunk_size=10))

        assert n == 25
        calls = pool._conn.executemany.await_args_list
        assert len(calls) == 3, "25 rows at chunk_size=10 must be 3 batches"
        assert [len(c.args[1]) for c in calls] == [10, 10, 5]

    def test_every_batch_carries_a_timeout(self) -> None:
        """Without a timeout a wedged connection hangs forever, as it did in production."""
        pool = _pool_with_rows(5)
        asyncio.run(refresh_prospect_scores(pool, chunk_size=10, timeout_s=30.0))

        for call in pool._conn.executemany.await_args_list:
            assert call.kwargs.get("timeout") == 30.0

    def test_timeout_raises_typed_error_naming_the_table(self) -> None:
        pool = _pool_with_rows(5)
        pool._conn.executemany.side_effect = TimeoutError()

        with pytest.raises(ScoringTimeoutError, match="prospect_scores"):
            asyncio.run(refresh_prospect_scores(pool, chunk_size=10, timeout_s=1.0))

    def test_no_rows_issues_no_upsert(self) -> None:
        pool = _pool_with_rows(0)
        assert asyncio.run(refresh_prospect_scores(pool)) == 0
        pool._conn.executemany.assert_not_awaited()
