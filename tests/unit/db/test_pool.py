"""Unit tests for db/pool.py — init_pool, close_pool, get_pool, acquire_conn."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import scraper.db.pool as pool_module
from scraper.db.pool import (
    _friendly_db_error,
    check_reachable,
    close_pool,
    get_pool,
    init_pool,
)


def _reset_pool() -> None:
    pool_module._pool = None


class TestInitPool:
    async def test_returns_pool_and_sets_global(self) -> None:
        _reset_pool()
        mock_pool = MagicMock()

        with patch("scraper.db.pool.asyncpg.create_pool", new=AsyncMock(return_value=mock_pool)):
            result = await init_pool("postgresql://localhost/test")

        assert result is mock_pool
        assert pool_module._pool is mock_pool
        _reset_pool()

    async def test_raises_when_create_pool_returns_none(self) -> None:
        _reset_pool()

        with (
            patch("scraper.db.pool.asyncpg.create_pool", new=AsyncMock(return_value=None)),
            pytest.raises(RuntimeError, match="returned None"),
        ):
            await init_pool("postgresql://localhost/test")

        _reset_pool()


class TestClosePool:
    async def test_closes_pool_and_clears_global(self) -> None:
        mock_pool = MagicMock()
        mock_pool.close = AsyncMock()
        pool_module._pool = mock_pool

        await close_pool()

        mock_pool.close.assert_called_once()
        assert pool_module._pool is None

    async def test_noop_when_pool_is_none(self) -> None:
        _reset_pool()
        await close_pool()
        assert pool_module._pool is None


class TestGetPool:
    def test_raises_when_not_initialised(self) -> None:
        _reset_pool()
        with pytest.raises(RuntimeError, match="not initialised"):
            get_pool()

    def test_returns_pool_when_initialised(self) -> None:
        mock_pool = MagicMock()
        pool_module._pool = mock_pool

        result = get_pool()

        assert result is mock_pool
        _reset_pool()


class TestAcquireConn:
    async def test_yields_connection_from_pool(self) -> None:
        from scraper.db.pool import acquire_conn

        mock_conn = MagicMock()
        acquire_cm = MagicMock()
        acquire_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        acquire_cm.__aexit__ = AsyncMock(return_value=False)

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=acquire_cm)
        pool_module._pool = mock_pool

        async with acquire_conn() as conn:
            assert conn is mock_conn

        _reset_pool()


class TestFriendlyDbError:
    def test_connection_refused_mentions_docker(self) -> None:
        msg = _friendly_db_error(ConnectionRefusedError(1225, "refused"))
        assert "refused" in msg.lower()
        assert "docker compose up -d pg" in msg

    def test_winerror_1225_string_maps_to_refused(self) -> None:
        # On Windows asyncpg surfaces an OSError whose text contains WinError 1225.
        msg = _friendly_db_error(OSError("[WinError 1225] connection was refused"))
        assert "docker compose up -d pg" in msg

    def test_timeout_mentions_reachable(self) -> None:
        msg = _friendly_db_error(TimeoutError())
        assert "timed out" in msg.lower()

    def test_generic_error_is_passed_through(self) -> None:
        msg = _friendly_db_error(RuntimeError("password authentication failed"))
        assert "password authentication failed" in msg


class TestCheckReachable:
    async def test_returns_none_on_success(self) -> None:
        mock_conn = MagicMock()
        mock_conn.close = AsyncMock()

        with patch("scraper.db.pool.asyncpg.connect", new=AsyncMock(return_value=mock_conn)):
            result = await check_reachable("postgresql://localhost/test")

        assert result is None
        mock_conn.close.assert_called_once()

    async def test_returns_friendly_message_on_connection_refused(self) -> None:
        with patch(
            "scraper.db.pool.asyncpg.connect",
            new=AsyncMock(side_effect=ConnectionRefusedError(1225, "refused")),
        ):
            result = await check_reachable("postgresql://localhost/test")

        assert result is not None
        assert "docker compose up -d pg" in result

    async def test_returns_friendly_message_on_timeout(self) -> None:
        # asyncpg raises TimeoutError itself once its native timeout= elapses.
        with patch("scraper.db.pool.asyncpg.connect", new=AsyncMock(side_effect=TimeoutError())):
            result = await check_reachable("postgresql://localhost/test", timeout_s=0.01)

        assert result is not None
        assert "timed out" in result.lower()

    async def test_timeout_is_passed_natively_to_asyncpg(self) -> None:
        """Not wrapped in asyncio.wait_for: cancelling asyncpg from outside can itself
        hang on the very socket this preflight exists to test."""
        mock_conn = MagicMock()
        mock_conn.close = AsyncMock()
        connect = AsyncMock(return_value=mock_conn)

        with patch("scraper.db.pool.asyncpg.connect", new=connect):
            await check_reachable("postgresql://localhost/test", timeout_s=1.5)

        assert connect.call_args.kwargs["timeout"] == 1.5
