from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import AsyncGenerator
from pathlib import Path

import asyncpg
import pytest

from scraper.db.migrations.runner import apply_pending

_MIGRATIONS_DIR = Path(__file__).parents[2] / "src" / "scraper" / "db" / "migrations"


async def _init_jsonb(conn: asyncpg.Connection) -> None:  # type: ignore[type-arg]
    await conn.set_type_codec(
        "jsonb",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )


def _admin_dsn(base_url: str) -> str:
    return base_url.rsplit("/", 1)[0] + "/postgres"


def _test_dsn(base_url: str, db_name: str) -> str:
    return base_url.rsplit("/", 1)[0] + f"/{db_name}"


@pytest.fixture(scope="session")
def test_db_dsn() -> str:
    """Create a disposable leads_test_<ts> database, run migrations, yield its DSN."""
    base_url = os.environ.get("DATABASE_URL", "postgresql://leads:leads@localhost:5432/leads")
    test_db_name = f"leads_test_{int(time.time())}"
    admin_url = _admin_dsn(base_url)
    dsn = _test_dsn(base_url, test_db_name)

    async def _create() -> None:
        conn: asyncpg.Connection = await asyncpg.connect(admin_url)  # type: ignore[type-arg]
        try:
            await conn.execute(f'CREATE DATABASE "{test_db_name}"')
        finally:
            await conn.close()
        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=5, init=_init_jsonb)
        assert pool is not None
        try:
            await apply_pending(pool, _MIGRATIONS_DIR)
        finally:
            await pool.close()

    asyncio.run(_create())

    yield dsn

    async def _drop() -> None:
        conn: asyncpg.Connection = await asyncpg.connect(admin_url)  # type: ignore[type-arg]
        try:
            await conn.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                f"WHERE datname = '{test_db_name}'"
            )
            await conn.execute(f'DROP DATABASE IF EXISTS "{test_db_name}"')
        finally:
            await conn.close()

    asyncio.run(_drop())


@pytest.fixture()
async def pg_pool(test_db_dsn: str) -> AsyncGenerator[asyncpg.Pool, None]:  # type: ignore[type-arg]
    """Function-scoped pool for the disposable test database."""
    pool = await asyncpg.create_pool(test_db_dsn, min_size=1, max_size=5, init=_init_jsonb)
    assert pool is not None
    yield pool
    await pool.close()


@pytest.fixture()
async def clean_pool(pg_pool: asyncpg.Pool) -> AsyncGenerator[asyncpg.Pool, None]:  # type: ignore[type-arg]
    """pg_pool with all data tables truncated before each test.

    consolidation_state must be included: it makes the consolidation pass incremental,
    so a placeholder left behind by an earlier test would be skipped as "already
    processed" and that test would silently see zero matches.
    """
    await pg_pool.execute("TRUNCATE observations, jobs, run_log RESTART IDENTITY CASCADE")
    await pg_pool.execute("TRUNCATE prospect_scores")
    await pg_pool.execute("TRUNCATE consolidation_state")
    yield pg_pool
