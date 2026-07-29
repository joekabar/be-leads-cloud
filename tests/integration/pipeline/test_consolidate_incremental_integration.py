"""Consolidation must not redo work on every run — verified against a real DB.

Before this, a second run re-matched the same placeholders and re-inserted the same
observations under the real KBO. Two consecutive production runs both logged
"matches=2797, observations_re_emitted=43466": ~43k duplicate rows in an append-only
table, plus ~40 min of matching, every single run.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from scraper.db.models import Observation
from scraper.db.repositories.observations import ObservationsRepo
from scraper.db.repositories.runs import RunsRepo
from scraper.pipeline.consolidate import consolidate

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 5, 13, 12, 0, 0, tzinfo=UTC)
_REAL = "0439401387"
_PLACEHOLDER = "9439401387"


async def _seed(pool, kbo: str, field: str, value: dict, source: str, run_id) -> None:
    await ObservationsRepo(pool).insert(
        Observation(
            kbo_number=kbo,
            field=field,
            value=value,
            source=source,
            observed_at=_NOW,
            confidence=0.85,
            run_id=run_id,
        )
    )


async def _seed_matching_pair(pool) -> None:
    run_id = await RunsRepo(pool).start_run(source="goudengids")
    addr = {"postal_code": "2060", "city": "Antwerpen", "country": "BE"}
    await _seed(pool, _REAL, "name", {"text": "Bellock NV", "lang": "nl"}, "kbo_dump", run_id)
    await _seed(
        pool, _REAL, "address", {"street": "Lange Van Bloerstraat", **addr}, "kbo_dump", run_id
    )
    await _seed(pool, _PLACEHOLDER, "name", {"text": "Bellock", "lang": "nl"}, "goudengids", run_id)
    await _seed(
        pool, _PLACEHOLDER, "address", {"street": "Lange Van Bloer", **addr}, "goudengids", run_id
    )
    await _seed(
        pool,
        _PLACEHOLDER,
        "phone",
        {"e164": "+3232361306", "raw": "03 236 13 06", "type": "landline"},
        "goudengids",
        run_id,
    )
    await pool.execute("SELECT refresh_companies_current()")


async def _reemitted_phone_count(pool) -> int:
    return await pool.fetchval(
        "SELECT count(*) FROM observations "
        "WHERE kbo_number = $1 AND field = 'phone' AND source = 'goudengids'",
        _REAL,
    )


async def test_second_run_does_no_work_and_emits_no_duplicates(clean_pool) -> None:
    await _seed_matching_pair(clean_pool)

    first = await consolidate(clean_pool)
    assert len(first) == 1
    after_first = await _reemitted_phone_count(clean_pool)
    assert after_first == 1, "first run should re-emit the placeholder's phone once"

    second = await consolidate(clean_pool)

    assert second == [], "an already-matched placeholder must not be reprocessed"
    assert await _reemitted_phone_count(clean_pool) == after_first, (
        "second run duplicated observations under the real KBO"
    )


async def test_match_is_recorded_in_consolidation_state(clean_pool) -> None:
    await _seed_matching_pair(clean_pool)
    await consolidate(clean_pool)

    row = await clean_pool.fetchrow(
        "SELECT real_kbo, score, matched_on FROM consolidation_state WHERE placeholder_kbo = $1",
        _PLACEHOLDER,
    )
    assert row is not None, "processed placeholders must be recorded"
    assert row["real_kbo"].strip() == _REAL
    assert float(row["score"]) >= 80.0
    assert row["matched_on"] == "name+postal"


async def test_unmatched_placeholder_is_recorded_with_null_real_kbo(clean_pool) -> None:
    """Recording non-matches is what stops the expensive name-only pass repeating."""
    run_id = await RunsRepo(clean_pool).start_run(source="goudengids")
    await _seed(clean_pool, _REAL, "name", {"text": "Bellock NV", "lang": "nl"}, "kbo_dump", run_id)
    await _seed(
        clean_pool,
        "9000000001",
        "name",
        {"text": "Completely Unrelated Widgets", "lang": "nl"},
        "goudengids",
        run_id,
    )
    await clean_pool.execute("SELECT refresh_companies_current()")

    assert await consolidate(clean_pool) == []

    row = await clean_pool.fetchrow(
        "SELECT real_kbo FROM consolidation_state WHERE placeholder_kbo = $1", "9000000001"
    )
    assert row is not None, "a non-match must still be recorded"
    assert row["real_kbo"] is None


async def test_force_reprocesses_an_already_matched_placeholder(clean_pool) -> None:
    await _seed_matching_pair(clean_pool)
    assert len(await consolidate(clean_pool)) == 1
    assert await consolidate(clean_pool) == []

    forced = await consolidate(clean_pool, force=True)
    assert len(forced) == 1, "force must redo the whole population"
