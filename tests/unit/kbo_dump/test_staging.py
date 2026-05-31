"""Unit tests for kbo_dump staging helpers (pure-Python, no DB)."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from scraper.sources.kbo_dump.staging import (
    StagingReport,
    _pg_text_escape,
    cleanup_old_snapshots,
    list_staged_snapshots,
)


class TestPgTextEscape:
    def test_none_returns_null_sentinel(self) -> None:
        assert _pg_text_escape(None) == r"\N"

    def test_plain_string_unchanged(self) -> None:
        assert _pg_text_escape("hello") == "hello"

    def test_tab_escaped(self) -> None:
        assert _pg_text_escape("a\tb") == "a\\tb"

    def test_newline_escaped(self) -> None:
        assert _pg_text_escape("a\nb") == "a\\nb"

    def test_carriage_return_escaped(self) -> None:
        assert _pg_text_escape("a\rb") == "a\\rb"

    def test_backslash_doubled(self) -> None:
        assert _pg_text_escape("a\\b") == "a\\\\b"

    def test_empty_string_unchanged(self) -> None:
        assert _pg_text_escape("") == ""

    def test_combined_special_chars(self) -> None:
        assert _pg_text_escape("a\t\n\\b") == "a\\t\\n\\\\b"


class TestStagingReport:
    def test_defaults(self) -> None:
        r = StagingReport(snapshot_date=date(2026, 4, 15))
        assert r.skipped is False
        assert r.rows_enterprise == 0
        assert r.rows_address == 0
        assert r.rows_denomination == 0
        assert r.rows_contact == 0
        assert r.rows_activity == 0
        assert r.duration_s == 0.0
        assert r.errors == []

    def test_skipped_flag(self) -> None:
        r = StagingReport(snapshot_date=date(2026, 4, 15), skipped=True)
        assert r.skipped is True

    def test_row_counts(self) -> None:
        r = StagingReport(
            snapshot_date=date(2026, 4, 15),
            rows_enterprise=100,
            rows_address=200,
            rows_denomination=50,
            rows_contact=30,
            rows_activity=120,
        )
        assert r.rows_enterprise == 100
        assert r.rows_address == 200
        assert r.rows_denomination == 50
        assert r.rows_contact == 30
        assert r.rows_activity == 120


def _make_pool(fetch_return=None, fetchval_return=None) -> MagicMock:
    pool = MagicMock()
    pool.fetch = AsyncMock(return_value=fetch_return or [])
    pool.fetchval = AsyncMock(return_value=fetchval_return)
    return pool


class TestListStagedSnapshots:
    async def test_empty_returns_empty_list(self) -> None:
        pool = _make_pool(fetch_return=[])
        result = await list_staged_snapshots(pool)
        assert result == []

    async def test_rows_returned_as_dicts(self) -> None:
        row = MagicMock()
        row.__getitem__ = lambda self, k: date(2026, 4, 15) if k == "snapshot_date" else 100
        pool = _make_pool(fetch_return=[row])
        result = await list_staged_snapshots(pool)
        assert len(result) == 1
        assert result[0]["snapshot_date"] == date(2026, 4, 15)
        assert result[0]["enterprise_count"] == 100

    async def test_multiple_rows_ordered_by_caller(self) -> None:
        rows = []
        for d, n in [(date(2026, 5, 1), 200), (date(2026, 4, 1), 150)]:
            r = MagicMock()
            r.__getitem__ = lambda self, k, _d=d, _n=n: _d if k == "snapshot_date" else _n
            rows.append(r)
        pool = _make_pool(fetch_return=rows)
        result = await list_staged_snapshots(pool)
        assert len(result) == 2
        assert result[0]["enterprise_count"] == 200


class TestCleanupOldSnapshots:
    async def test_keep_n_lt_1_raises_value_error(self) -> None:
        pool = _make_pool()
        with pytest.raises(ValueError, match="keep_n must be >= 1"):
            await cleanup_old_snapshots(pool, keep_n=0)

    async def test_fewer_snapshots_than_keep_n_returns_zeros(self) -> None:
        row1 = MagicMock()
        row1.__getitem__ = lambda self, k: date(2026, 4, 15)
        pool = _make_pool(fetch_return=[row1])
        deleted = await cleanup_old_snapshots(pool, keep_n=3)
        assert all(v == 0 for v in deleted.values())

    async def test_excess_snapshots_deleted(self) -> None:
        rows = [MagicMock(), MagicMock()]
        rows[0].__getitem__ = lambda self, k: date(2026, 5, 1)
        rows[1].__getitem__ = lambda self, k: date(2026, 4, 1)
        pool = _make_pool(fetch_return=rows)

        conn = AsyncMock()
        conn.execute = AsyncMock(return_value="DELETE 5")

        tx = MagicMock()
        tx.__aenter__ = AsyncMock(return_value=None)
        tx.__aexit__ = AsyncMock(return_value=False)
        conn.transaction = MagicMock(return_value=tx)

        acquire_cm = MagicMock()
        acquire_cm.__aenter__ = AsyncMock(return_value=conn)
        acquire_cm.__aexit__ = AsyncMock(return_value=False)
        pool.acquire = MagicMock(return_value=acquire_cm)

        deleted = await cleanup_old_snapshots(pool, keep_n=1)
        assert all(v == 5 for v in deleted.values())
