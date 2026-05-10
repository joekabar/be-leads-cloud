from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest

from scraper.db.models import Observation
from scraper.db.repositories.observations import ObservationsRepo
from scraper.db.repositories.runs import RunsRepo

pytestmark = pytest.mark.integration

_KBO = "0439401387"


async def _make_run(pool: asyncpg.Pool) -> uuid.UUID:  # type: ignore[type-arg]
    return await RunsRepo(pool).start_run(source="kbo_dump")


def _obs(run_id: uuid.UUID, **kwargs: object) -> Observation:
    defaults: dict[str, object] = {
        "kbo_number": _KBO,
        "field": "phone",
        "value": {"e164": "+3232361306"},
        "source": "kbo_dump",
        "confidence": 0.80,
        "run_id": run_id,
    }
    defaults.update(kwargs)
    return Observation(**defaults)  # type: ignore[arg-type]


async def test_insert_returns_id(clean_pool: asyncpg.Pool) -> None:  # type: ignore[type-arg]
    run_id = await _make_run(clean_pool)
    repo = ObservationsRepo(clean_pool)
    obs_id = await repo.insert(_obs(run_id))
    assert isinstance(obs_id, int)
    assert obs_id > 0


async def test_insert_many_returns_correct_count(clean_pool: asyncpg.Pool) -> None:  # type: ignore[type-arg]
    run_id = await _make_run(clean_pool)
    repo = ObservationsRepo(clean_pool)
    obs_list = [_obs(run_id) for _ in range(100)]
    ids = await repo.insert_many(obs_list)
    assert len(ids) == 100
    assert len(set(ids)) == 100  # all unique


async def test_current_best_returns_highest_confidence(clean_pool: asyncpg.Pool) -> None:  # type: ignore[type-arg]
    run_id = await _make_run(clean_pool)
    repo = ObservationsRepo(clean_pool)
    now = datetime.now(tz=UTC)
    await repo.insert(_obs(run_id, confidence=0.50, observed_at=now))
    await repo.insert(_obs(run_id, confidence=0.95, observed_at=now - timedelta(days=1)))
    best = await repo.current_best(_KBO, "phone")
    assert best is not None
    assert best.confidence == pytest.approx(0.95)


async def test_current_best_tie_broken_by_newest(clean_pool: asyncpg.Pool) -> None:  # type: ignore[type-arg]
    run_id = await _make_run(clean_pool)
    repo = ObservationsRepo(clean_pool)
    older = datetime.now(tz=UTC) - timedelta(hours=2)
    newer = datetime.now(tz=UTC)
    val_old = {"e164": "+3200000001"}
    val_new = {"e164": "+3200000002"}
    await repo.insert(_obs(run_id, confidence=0.80, observed_at=older, value=val_old))
    await repo.insert(_obs(run_id, confidence=0.80, observed_at=newer, value=val_new))
    best = await repo.current_best(_KBO, "phone")
    assert best is not None
    assert best.value == val_new


async def test_history_newest_first(clean_pool: asyncpg.Pool) -> None:  # type: ignore[type-arg]
    run_id = await _make_run(clean_pool)
    repo = ObservationsRepo(clean_pool)
    now = datetime.now(tz=UTC)
    await repo.insert(_obs(run_id, observed_at=now - timedelta(days=2)))
    await repo.insert(_obs(run_id, observed_at=now - timedelta(days=1)))
    await repo.insert(_obs(run_id, observed_at=now))
    history = await repo.history(_KBO, "phone")
    assert len(history) == 3
    assert history[0].observed_at >= history[1].observed_at >= history[2].observed_at  # type: ignore[operator]


async def test_current_best_none_when_empty(clean_pool: asyncpg.Pool) -> None:  # type: ignore[type-arg]
    repo = ObservationsRepo(clean_pool)
    result = await repo.current_best("0000000097", "phone")
    assert result is None


async def test_insert_many_empty_list(clean_pool: asyncpg.Pool) -> None:  # type: ignore[type-arg]
    repo = ObservationsRepo(clean_pool)
    ids = await repo.insert_many([])
    assert ids == []


async def test_current_all(clean_pool: asyncpg.Pool) -> None:  # type: ignore[type-arg]
    run_id = await _make_run(clean_pool)
    repo = ObservationsRepo(clean_pool)
    defaults: dict[str, object] = {
        "kbo_number": _KBO,
        "source": "kbo_dump",
        "confidence": 0.80,
        "run_id": run_id,
    }
    await repo.insert(Observation(**{**defaults, "field": "phone", "value": {"e164": "+32"}}))  # type: ignore[arg-type]
    await repo.insert(
        Observation(**{**defaults, "field": "email", "value": {"address": "a@b.com"}})
    )  # type: ignore[arg-type]
    results = await repo.current_all(_KBO)
    fields = {r.field for r in results}
    assert {"phone", "email"} <= fields


def test_repo_has_no_update_method() -> None:
    assert not hasattr(ObservationsRepo, "update")


def test_repo_has_no_delete_method() -> None:
    assert not hasattr(ObservationsRepo, "delete")
