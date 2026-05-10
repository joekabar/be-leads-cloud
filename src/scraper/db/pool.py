from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import asyncpg

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

_pool: asyncpg.Pool | None = None


async def _init_jsonb_codec(conn: asyncpg.Connection) -> None:
    await conn.set_type_codec(
        "jsonb",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )


async def init_pool(
    dsn: str,
    *,
    min_size: int = 1,
    max_size: int = 10,
) -> asyncpg.Pool:
    """Initialise the module-level pool. Call once at application startup."""
    global _pool
    pool = await asyncpg.create_pool(
        dsn,
        min_size=min_size,
        max_size=max_size,
        init=_init_jsonb_codec,
    )
    if pool is None:
        raise RuntimeError("asyncpg.create_pool returned None")
    _pool = pool
    return _pool


async def close_pool() -> None:
    """Close the module-level pool. Call once at application shutdown."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    """Return the active pool. Raises RuntimeError if init_pool has not been called."""
    if _pool is None:
        raise RuntimeError("DB pool is not initialised — call init_pool() first.")
    return _pool


@asynccontextmanager
async def acquire_conn() -> AsyncIterator[asyncpg.Connection]:
    """Acquire a connection from the pool as an async context manager."""
    pool = get_pool()
    async with pool.acquire() as conn:
        yield conn
