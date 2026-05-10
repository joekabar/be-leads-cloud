from __future__ import annotations

import asyncpg
import pytest

from scraper.db.repositories.runs import RunsRepo

pytestmark = pytest.mark.integration


async def test_start_finish_roundtrip(clean_pool: asyncpg.Pool) -> None:  # type: ignore[type-arg]
    repo = RunsRepo(clean_pool)
    run_id = await repo.start_run(source="kbo_dump", notes="test run")

    run = await repo.get(run_id)
    assert run is not None
    assert run.run_id == run_id
    assert run.source == "kbo_dump"
    assert run.notes == "test run"
    assert run.ended_at is None
    assert run.jobs_done == 0

    await repo.finish_run(run_id, jobs_done=42, jobs_failed=3)

    run = await repo.get(run_id)
    assert run is not None
    assert run.ended_at is not None
    assert run.jobs_done == 42
    assert run.jobs_failed == 3


async def test_start_run_returns_uuid(clean_pool: asyncpg.Pool) -> None:  # type: ignore[type-arg]
    repo = RunsRepo(clean_pool)
    r1 = await repo.start_run()
    r2 = await repo.start_run()
    assert r1 != r2


async def test_get_missing_run_returns_none(clean_pool: asyncpg.Pool) -> None:  # type: ignore[type-arg]
    import uuid

    repo = RunsRepo(clean_pool)
    result = await repo.get(uuid.uuid4())
    assert result is None
