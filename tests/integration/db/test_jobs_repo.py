from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest

from scraper.db.repositories.jobs import JobsRepo

pytestmark = pytest.mark.integration


async def test_enqueue_returns_id(clean_pool: asyncpg.Pool) -> None:  # type: ignore[type-arg]
    repo = JobsRepo(clean_pool)
    job_id = await repo.enqueue("fetch_company", {"kbo": "0439401387"})
    assert isinstance(job_id, int)
    assert job_id > 0


async def test_pop_pending_returns_job(clean_pool: asyncpg.Pool) -> None:  # type: ignore[type-arg]
    repo = JobsRepo(clean_pool)
    job_id = await repo.enqueue("fetch_company", {"kbo": "0439401387"})
    job = await repo.pop_pending()
    assert job is not None
    assert job.id == job_id
    assert job.type == "fetch_company"
    assert job.status == "running"


async def test_pop_pending_empty_queue(clean_pool: asyncpg.Pool) -> None:  # type: ignore[type-arg]
    repo = JobsRepo(clean_pool)
    job = await repo.pop_pending()
    assert job is None


async def test_mark_done(clean_pool: asyncpg.Pool) -> None:  # type: ignore[type-arg]
    repo = JobsRepo(clean_pool)
    job_id = await repo.enqueue("fetch_company")
    await repo.pop_pending()
    await repo.mark_done(job_id)
    row = await clean_pool.fetchrow("SELECT status FROM jobs WHERE id = $1", job_id)
    assert row is not None
    assert row["status"] == "done"


async def test_mark_failed_requeues(clean_pool: asyncpg.Pool) -> None:  # type: ignore[type-arg]
    repo = JobsRepo(clean_pool)
    job_id = await repo.enqueue("fetch_company")
    await repo.pop_pending()
    retry_at = datetime.now(tz=UTC) + timedelta(seconds=60)
    await repo.mark_failed(job_id, "timeout", retry_at)
    row = await clean_pool.fetchrow("SELECT status, last_error FROM jobs WHERE id = $1", job_id)
    assert row is not None
    assert row["status"] == "pending"
    assert row["last_error"] == "timeout"


async def test_mark_dead(clean_pool: asyncpg.Pool) -> None:  # type: ignore[type-arg]
    repo = JobsRepo(clean_pool)
    job_id = await repo.enqueue("fetch_company")
    await repo.pop_pending()
    await repo.mark_dead(job_id, "max retries exceeded")
    row = await clean_pool.fetchrow("SELECT status FROM jobs WHERE id = $1", job_id)
    assert row is not None
    assert row["status"] == "dead"


async def test_concurrent_pops_no_double_delivery(clean_pool: asyncpg.Pool) -> None:  # type: ignore[type-arg]
    """Two concurrent workers must each get a distinct job (SKIP LOCKED)."""
    repo = JobsRepo(clean_pool)
    id1 = await repo.enqueue("task_a", priority=5)
    id2 = await repo.enqueue("task_b", priority=5)

    results = await asyncio.gather(repo.pop_pending(), repo.pop_pending())
    popped_ids = {j.id for j in results if j is not None}
    assert popped_ids == {id1, id2}
