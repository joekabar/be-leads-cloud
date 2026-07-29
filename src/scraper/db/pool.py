from __future__ import annotations

import asyncio
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


def _friendly_db_error(exc: BaseException) -> str:
    """Map a raw connection failure to an actionable message for the UI.

    ``WinError 1225`` / ``ConnectionRefusedError`` means nothing is listening on the
    Postgres port — almost always a stopped database container.
    """
    text = str(exc)
    if isinstance(exc, ConnectionRefusedError) or "1225" in text or "refused" in text.lower():
        return (
            "Cannot reach Postgres — connection refused. Is the database running? "
            "Start Docker Desktop, then run `docker compose up -d pg`."
        )
    if isinstance(exc, asyncio.TimeoutError):
        return (
            "Cannot reach Postgres — connection timed out. Is the database running and reachable?"
        )
    return f"Cannot reach Postgres: {text}"


async def check_reachable(dsn: str, *, timeout_s: float = 3.0) -> str | None:
    """Preflight check: return ``None`` if Postgres accepts a connection, else a reason.

    Used by the Streamlit UI before launching a run so a stopped database surfaces as a
    clear message instead of a raw ``OSError`` / ``WinError 1225`` mid-pipeline.

    The timeout is passed natively to asyncpg rather than wrapping the call in
    ``asyncio.wait_for``: cancelling asyncpg from outside makes it take its generic
    cancel path, which can hang on the same unreachable socket we are testing for.
    """
    try:
        conn = await asyncpg.connect(dsn, timeout=timeout_s)
    except (TimeoutError, OSError, asyncpg.PostgresError) as exc:
        return _friendly_db_error(exc)
    await conn.close()
    return None


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
