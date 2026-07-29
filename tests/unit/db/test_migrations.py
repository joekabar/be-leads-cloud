"""Unit tests for db/migrations/runner.py — apply_pending."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from scraper.db.migrations.runner import apply_pending


def _make_pool(current_version: int = 0) -> tuple[MagicMock, MagicMock]:
    conn = MagicMock()
    conn.execute = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={"v": current_version})

    tx_cm = MagicMock()
    tx_cm.__aenter__ = AsyncMock(return_value=None)
    tx_cm.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=tx_cm)

    acquire_cm = MagicMock()
    acquire_cm.__aenter__ = AsyncMock(return_value=conn)
    acquire_cm.__aexit__ = AsyncMock(return_value=False)

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=acquire_cm)

    return pool, conn


class TestApplyPending:
    async def test_empty_dir_returns_zero(self) -> None:
        pool, _conn = _make_pool()

        with tempfile.TemporaryDirectory() as tmpdir:
            result = await apply_pending(pool, Path(tmpdir))

        assert result == 0

    async def test_applies_new_migration_file(self) -> None:
        pool, conn = _make_pool(current_version=0)

        with tempfile.TemporaryDirectory() as tmpdir:
            sql_file = Path(tmpdir) / "001_create_test.sql"
            sql_file.write_text("CREATE TABLE test (id INT);")

            result = await apply_pending(pool, Path(tmpdir))

        assert result == 1
        assert conn.execute.call_count >= 2

    async def test_skips_already_applied_version(self) -> None:
        pool, conn = _make_pool(current_version=5)

        with tempfile.TemporaryDirectory() as tmpdir:
            for v in (1, 2, 3):
                (Path(tmpdir) / f"00{v}_migration.sql").write_text(f"SELECT {v};")

            result = await apply_pending(pool, Path(tmpdir))

        assert result == 5
        # The only execute is the schema_version bootstrap — no migration SQL ran,
        # since every file on disk is at or below the current version.
        assert conn.execute.call_count == 1

    async def test_applies_only_newer_versions(self) -> None:
        pool, _conn = _make_pool(current_version=2)

        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "001_old.sql").write_text("SELECT 1;")
            (Path(tmpdir) / "002_also_old.sql").write_text("SELECT 2;")
            (Path(tmpdir) / "003_new.sql").write_text("SELECT 3;")

            result = await apply_pending(pool, Path(tmpdir))

        assert result == 3

    async def test_non_sql_files_ignored(self) -> None:
        pool, _conn = _make_pool()

        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "README.md").write_text("# migrations")
            (Path(tmpdir) / "schema.txt").write_text("some text")

            result = await apply_pending(pool, Path(tmpdir))

        assert result == 0

    async def test_multiple_migrations_applied_in_order(self) -> None:
        pool, _conn = _make_pool(current_version=0)

        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "001_first.sql").write_text("SELECT 1;")
            (Path(tmpdir) / "002_second.sql").write_text("SELECT 2;")

            result = await apply_pending(pool, Path(tmpdir))

        assert result == 2
