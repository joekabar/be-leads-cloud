"""Unit tests for DB repositories using mocked asyncpg pools."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from scraper.db.repositories.jobs import JobsRepo
from scraper.db.repositories.observations import ObservationsRepo
from scraper.db.repositories.runs import RunsRepo


def _make_pool() -> AsyncMock:
    """Return a pool mock where pool.acquire() works as an async context manager."""
    pool = AsyncMock()
    pool.execute.return_value = None
    pool.fetch.return_value = []
    pool.fetchrow.return_value = None
    pool.executemany.return_value = None

    tx_cm = MagicMock()
    tx_cm.__aenter__ = AsyncMock(return_value=None)
    tx_cm.__aexit__ = AsyncMock(return_value=False)

    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value=None)
    conn.execute = AsyncMock(return_value=None)
    conn.transaction = MagicMock(return_value=tx_cm)

    acquire_cm = MagicMock()
    acquire_cm.__aenter__ = AsyncMock(return_value=conn)
    acquire_cm.__aexit__ = AsyncMock(return_value=False)
    # pool.acquire() must be a plain callable returning the context manager — NOT a coroutine
    pool.acquire = MagicMock(return_value=acquire_cm)
    pool._conn = conn  # expose for tests that need to control conn.fetchrow

    return pool


# ── RunsRepo ──────────────────────────────────────────────────────────────────


class TestRunsRepo:
    async def test_start_run_returns_uuid(self) -> None:
        pool = _make_pool()
        repo = RunsRepo(pool)
        run_id = await repo.start_run(source="kbopub", city_slug="antwerpen")
        assert isinstance(run_id, uuid.UUID)
        pool.execute.assert_called_once()

    async def test_start_run_with_all_args(self) -> None:
        pool = _make_pool()
        repo = RunsRepo(pool)
        run_id = await repo.start_run(
            source="nbb_authentic",
            sector_slug="elektriciens",
            city_slug="gent",
            notes="batch run",
        )
        assert isinstance(run_id, uuid.UUID)

    async def test_finish_run_calls_update(self) -> None:
        pool = _make_pool()
        repo = RunsRepo(pool)
        run_id = uuid.uuid4()
        await repo.finish_run(run_id, jobs_done=42, jobs_failed=1)
        pool.execute.assert_called_once()
        sql, *args = pool.execute.call_args[0]
        assert "UPDATE run_log" in sql
        assert run_id in args

    async def test_get_returns_none_when_not_found(self) -> None:
        pool = _make_pool()
        repo = RunsRepo(pool)
        result = await repo.get(uuid.uuid4())
        assert result is None

    async def test_get_returns_run_when_found(self) -> None:
        run_id = uuid.uuid4()
        now = datetime.now(tz=UTC)
        pool = _make_pool()
        pool.fetchrow.return_value = {
            "run_id": run_id,
            "started_at": now,
            "ended_at": now,
            "sector_slug": "elektriciens",
            "city_slug": "antwerpen",
            "source": "kbo_dump",
            "notes": None,
            "jobs_done": 10,
            "jobs_failed": 0,
        }
        repo = RunsRepo(pool)
        result = await repo.get(run_id)
        assert result is not None
        assert result.run_id == run_id
        assert result.source == "kbo_dump"
        assert result.jobs_done == 10


# ── ObservationsRepo ──────────────────────────────────────────────────────────


def _make_observation(**overrides: object) -> object:
    from scraper.db.models import Observation

    defaults: dict[str, object] = {
        "kbo_number": "9000000001",
        "field": "name",
        "value": {"text": "Test NV"},
        "source": "kbo_dump",
        "confidence": 0.95,
        "run_id": uuid.uuid4(),
    }
    defaults.update(overrides)
    return Observation(**defaults)  # type: ignore[arg-type]


class TestObservationsRepo:
    async def test_insert_returns_id(self) -> None:
        pool = _make_pool()
        pool.fetchrow.return_value = {"id": 99}
        repo = ObservationsRepo(pool)
        obs = _make_observation()
        result = await repo.insert(obs)  # type: ignore[arg-type]
        assert result == 99

    async def test_insert_raises_when_no_row_returned(self) -> None:
        pool = _make_pool()
        pool.fetchrow.return_value = None
        repo = ObservationsRepo(pool)
        obs = _make_observation()
        with pytest.raises(RuntimeError, match="INSERT INTO observations returned no row"):
            await repo.insert(obs)  # type: ignore[arg-type]

    async def test_insert_many_empty_list_returns_empty(self) -> None:
        pool = _make_pool()
        repo = ObservationsRepo(pool)
        result = await repo.insert_many([])
        assert result == []
        pool.acquire.assert_not_called()

    async def test_insert_many_returns_ids(self) -> None:
        pool = _make_pool()
        pool._conn.fetchrow.return_value = {"id": 7}
        repo = ObservationsRepo(pool)
        obs = _make_observation()
        result = await repo.insert_many([obs])  # type: ignore[arg-type]
        assert result == [7]

    async def test_insert_many_raises_when_no_row(self) -> None:
        pool = _make_pool()
        pool._conn.fetchrow.return_value = None
        repo = ObservationsRepo(pool)
        obs = _make_observation()
        with pytest.raises(RuntimeError, match="INSERT INTO observations returned no row"):
            await repo.insert_many([obs])  # type: ignore[arg-type]

    async def test_current_best_returns_none_when_not_found(self) -> None:
        pool = _make_pool()
        repo = ObservationsRepo(pool)
        result = await repo.current_best("0123456789", "name")
        assert result is None

    async def test_current_all_returns_empty_list(self) -> None:
        pool = _make_pool()
        pool.fetch.return_value = []
        repo = ObservationsRepo(pool)
        result = await repo.current_all("0123456789")
        assert result == []

    async def test_history_returns_empty_list(self) -> None:
        pool = _make_pool()
        pool.fetch.return_value = []
        repo = ObservationsRepo(pool)
        result = await repo.history("0123456789", "name")
        assert result == []


# ── JobsRepo ──────────────────────────────────────────────────────────────────


class TestJobsRepo:
    async def test_enqueue_returns_id(self) -> None:
        pool = _make_pool()
        pool.fetchrow.return_value = {"id": 42}
        repo = JobsRepo(pool)
        result = await repo.enqueue("scrape_kbo", {"kbo": "0123456789"})
        assert result == 42

    async def test_enqueue_raises_when_no_row(self) -> None:
        pool = _make_pool()
        pool.fetchrow.return_value = None
        repo = JobsRepo(pool)
        with pytest.raises(RuntimeError, match="INSERT INTO jobs returned no row"):
            await repo.enqueue("scrape_kbo")

    async def test_pop_pending_returns_none_when_empty(self) -> None:
        pool = _make_pool()
        pool.fetchrow.return_value = None
        repo = JobsRepo(pool)
        result = await repo.pop_pending()
        assert result is None

    async def test_pop_pending_returns_job_when_available(self) -> None:
        pool = _make_pool()
        pool.fetchrow.return_value = {
            "id": 5,
            "type": "scrape_kbo",
            "payload": {"kbo": "0123456789"},
            "status": "running",
            "attempts": 1,
            "priority": 5,
            "last_error": None,
            "parent_job_id": None,
        }
        repo = JobsRepo(pool)
        job = await repo.pop_pending()
        assert job is not None
        assert job.id == 5
        assert job.type == "scrape_kbo"

    async def test_mark_done_calls_execute(self) -> None:
        pool = _make_pool()
        repo = JobsRepo(pool)
        await repo.mark_done(5)
        pool.execute.assert_called_once()

    async def test_mark_failed_calls_execute(self) -> None:
        pool = _make_pool()
        repo = JobsRepo(pool)
        retry_at = datetime.now(tz=UTC)
        await repo.mark_failed(5, "timeout", retry_at)
        pool.execute.assert_called_once()

    async def test_mark_dead_calls_execute(self) -> None:
        pool = _make_pool()
        repo = JobsRepo(pool)
        await repo.mark_dead(5, "max retries exceeded")
        pool.execute.assert_called_once()
