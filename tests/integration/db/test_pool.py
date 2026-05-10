from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


async def test_init_and_close_pool(test_db_dsn: str) -> None:
    from scraper.db.pool import close_pool, get_pool, init_pool

    pool = await init_pool(test_db_dsn, min_size=1, max_size=2)
    assert pool is not None
    retrieved = get_pool()
    assert retrieved is pool
    await close_pool()


async def test_get_pool_before_init_raises() -> None:
    from scraper.db import pool as pool_mod
    from scraper.db.pool import get_pool

    pool_mod._pool = None
    with pytest.raises(RuntimeError, match="not initialised"):
        get_pool()


async def test_acquire_conn(test_db_dsn: str) -> None:
    from scraper.db.pool import acquire_conn, close_pool, init_pool

    await init_pool(test_db_dsn, min_size=1, max_size=2)
    try:
        async with acquire_conn() as conn:
            row = await conn.fetchrow("SELECT 1 AS val")
            assert row is not None
            assert row["val"] == 1
    finally:
        await close_pool()
