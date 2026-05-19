"""Integration tests for refresh_prospect_scores against a real Postgres instance."""

from __future__ import annotations

from datetime import UTC, datetime

import asyncpg
import pytest

from scraper.db.models import Observation
from scraper.db.repositories.observations import ObservationsRepo
from scraper.db.repositories.runs import RunsRepo
from scraper.scoring.prospect import refresh_prospect_scores

pytestmark = pytest.mark.integration


async def _insert_observations(
    pool: asyncpg.Pool,  # type: ignore[type-arg]
    kbo: str,
    nace_code: str,
    *,
    active: bool = True,
    has_phone: bool = False,
    has_financial: bool = False,
) -> None:
    runs_repo = RunsRepo(pool)
    obs_repo = ObservationsRepo(pool)
    run_id = await runs_repo.start_run(source="kbo_dump")
    now = datetime.now(tz=UTC)

    obs: list[Observation] = [
        Observation(
            kbo_number=kbo,
            field="name",
            value={"text": f"Company {kbo}"},
            raw_value=None,
            source="kbo_dump",
            source_url=None,
            observed_at=now,
            confidence=0.95,
            run_id=run_id,
        ),
        Observation(
            kbo_number=kbo,
            field="nace_code",
            value={"code": nace_code, "description": "test"},
            raw_value=None,
            source="kbo_dump",
            source_url=None,
            observed_at=now,
            confidence=1.00,
            run_id=run_id,
        ),
    ]
    if active:
        obs.append(
            Observation(
                kbo_number=kbo,
                field="status",
                value={"text": "Actief"},
                raw_value=None,
                source="kbo_dump",
                source_url=None,
                observed_at=now,
                confidence=1.00,
                run_id=run_id,
            )
        )
    if has_phone:
        obs.append(
            Observation(
                kbo_number=kbo,
                field="phone",
                value={"e164": "+3290000000", "raw": "090000000"},
                raw_value=None,
                source="kbo_dump",
                source_url=None,
                observed_at=now,
                confidence=0.90,
                run_id=run_id,
            )
        )
    if has_financial:
        obs.append(
            Observation(
                kbo_number=kbo,
                field="revenue_2023",
                value={"eur": 1000000},
                raw_value=None,
                source="nbb_authentic",
                source_url=None,
                observed_at=now,
                confidence=1.00,
                run_id=run_id,
            )
        )

    await obs_repo.insert_many(obs)
    await runs_repo.finish_run(run_id, jobs_done=len(obs))
    await pool.execute("SELECT refresh_companies_current()")


async def test_refresh_populates_one_row_per_kbo(
    clean_pool: asyncpg.Pool,  # type: ignore[type-arg]
) -> None:
    kbos = ["0000000196", "0000000295", "0000000394"]
    for i, kbo in enumerate(kbos):
        await _insert_observations(clean_pool, kbo, f"2010{i}")

    n = await refresh_prospect_scores(clean_pool)
    assert n == len(kbos)

    rows = await clean_pool.fetch("SELECT kbo_number FROM prospect_scores ORDER BY kbo_number")
    db_kbos = {str(r["kbo_number"]).strip() for r in rows}
    assert db_kbos == set(kbos)


async def test_t1_kbo_outranks_t4_with_same_completeness(
    clean_pool: asyncpg.Pool,  # type: ignore[type-arg]
) -> None:
    # T1: electricity generation (3511x)
    await _insert_observations(
        clean_pool, "0000000493", "35110", active=True, has_phone=True, has_financial=True
    )
    # T4: electricians (4321x)
    await _insert_observations(
        clean_pool, "0000000592", "43211", active=True, has_phone=True, has_financial=True
    )

    await refresh_prospect_scores(clean_pool)

    t1_row = await clean_pool.fetchrow(
        "SELECT overall_prospect FROM prospect_scores WHERE kbo_number = '0000000493'"
    )
    t4_row = await clean_pool.fetchrow(
        "SELECT overall_prospect FROM prospect_scores WHERE kbo_number = '0000000592'"
    )

    assert t1_row is not None and t4_row is not None
    assert float(t1_row["overall_prospect"]) > float(t4_row["overall_prospect"])


async def test_refresh_is_idempotent(
    clean_pool: asyncpg.Pool,  # type: ignore[type-arg]
) -> None:
    await _insert_observations(clean_pool, "0000000691", "35110")

    n1 = await refresh_prospect_scores(clean_pool)
    n2 = await refresh_prospect_scores(clean_pool)

    assert n1 == n2 == 1

    rows = await clean_pool.fetch("SELECT * FROM prospect_scores WHERE kbo_number = '0000000691'")
    assert len(rows) == 1


async def test_refresh_updates_changed_score(
    clean_pool: asyncpg.Pool,  # type: ignore[type-arg]
) -> None:
    kbo = "0000000790"
    await _insert_observations(clean_pool, kbo, "35110", active=False, has_phone=False)

    await refresh_prospect_scores(clean_pool)
    before = await clean_pool.fetchrow(
        "SELECT overall_prospect FROM prospect_scores WHERE kbo_number = $1", kbo
    )

    # Add phone + active status → score should increase on next refresh
    runs_repo = RunsRepo(clean_pool)
    obs_repo = ObservationsRepo(clean_pool)
    run_id = await runs_repo.start_run(source="kbo_dump")
    await obs_repo.insert_many(
        [
            Observation(
                kbo_number=kbo,
                field="status",
                value={"text": "Actief"},
                raw_value=None,
                source="kbo_dump",
                source_url=None,
                observed_at=datetime.now(tz=UTC),
                confidence=1.00,
                run_id=run_id,
            ),
        ]
    )
    await runs_repo.finish_run(run_id, jobs_done=1)
    await clean_pool.execute("SELECT refresh_companies_current()")

    await refresh_prospect_scores(clean_pool)
    after = await clean_pool.fetchrow(
        "SELECT overall_prospect FROM prospect_scores WHERE kbo_number = $1", kbo
    )

    assert before is not None and after is not None
    assert float(after["overall_prospect"]) > float(before["overall_prospect"])
