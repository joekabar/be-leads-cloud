from __future__ import annotations

from pathlib import Path

import asyncpg
import pytest

from scraper.db.migrations.runner import apply_pending

_MIGRATIONS_DIR = Path(__file__).parents[3] / "src" / "scraper" / "db" / "migrations"

pytestmark = pytest.mark.integration


async def test_migrations_idempotent(pg_pool: asyncpg.Pool) -> None:  # type: ignore[type-arg]
    """Applying migrations twice returns the same version and raises no errors."""
    v1 = await apply_pending(pg_pool, _MIGRATIONS_DIR)
    v2 = await apply_pending(pg_pool, _MIGRATIONS_DIR)
    assert v1 == v2
    assert v1 >= 2


async def test_all_tables_exist(pg_pool: asyncpg.Pool) -> None:  # type: ignore[type-arg]
    rows = await pg_pool.fetch(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
    )
    names = {r["tablename"] for r in rows}
    assert {"schema_version", "run_log", "observations", "jobs"} <= names


async def test_matview_exists(pg_pool: asyncpg.Pool) -> None:  # type: ignore[type-arg]
    rows = await pg_pool.fetch("SELECT matviewname FROM pg_matviews WHERE schemaname = 'public'")
    names = {r["matviewname"] for r in rows}
    assert "companies_current" in names


async def test_matview_unique_index_exists(pg_pool: asyncpg.Pool) -> None:  # type: ignore[type-arg]
    row = await pg_pool.fetchrow(
        """
        SELECT indexname FROM pg_indexes
        WHERE schemaname = 'public'
          AND tablename = 'companies_current'
          AND indexname = 'uniq_companies_current'
        """
    )
    assert row is not None, "unique index uniq_companies_current not found"
