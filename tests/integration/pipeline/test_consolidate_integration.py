"""Integration tests for the consolidation pass against a real test DB."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from scraper.db.models import Observation
from scraper.db.repositories.observations import ObservationsRepo
from scraper.db.repositories.runs import RunsRepo
from scraper.pipeline.consolidate import consolidate

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 5, 13, 12, 0, 0, tzinfo=UTC)


async def _seed_obs(pool, kbo: str, field: str, value: dict, source: str, run_id) -> None:
    repo = ObservationsRepo(pool)
    await repo.insert(
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


async def test_consolidate_matches_placeholder_to_real(clean_pool) -> None:
    """Placeholder with Bellock name+postal matches real KBO 0439401387."""
    runs_repo = RunsRepo(clean_pool)
    run_id = await runs_repo.start_run(source="goudengids")

    # Seed real KBO observations
    await _seed_obs(
        clean_pool,
        "0439401387",
        "name",
        {"text": "Bellock NV", "lang": "nl"},
        "kbo_dump",
        run_id,
    )
    await _seed_obs(
        clean_pool,
        "0439401387",
        "address",
        {
            "street": "Lange Van Bloerstraat",
            "postal_code": "2060",
            "city": "Antwerpen",
            "country": "BE",
        },
        "kbo_dump",
        run_id,
    )
    await _seed_obs(
        clean_pool,
        "0439401387",
        "founding_date",
        {"iso": "1989-12-28"},
        "kbo_dump",
        run_id,
    )

    # Seed placeholder KBO with phone (should be re-emitted under real KBO)
    placeholder = "9439401387"
    await _seed_obs(
        clean_pool,
        placeholder,
        "name",
        {"text": "Bellock", "lang": "nl"},
        "goudengids",
        run_id,
    )
    await _seed_obs(
        clean_pool,
        placeholder,
        "address",
        {"street": "Lange Van Bloer", "postal_code": "2060", "city": "Antwerpen", "country": "BE"},
        "goudengids",
        run_id,
    )
    await _seed_obs(
        clean_pool,
        placeholder,
        "phone",
        {"e164": "+3232361306", "raw": "03 236 13 06", "type": "landline"},
        "goudengids",
        run_id,
    )

    await clean_pool.execute("SELECT refresh_companies_current()")

    matches = await consolidate(clean_pool)

    assert len(matches) == 1
    assert matches[0].placeholder_kbo == placeholder
    assert matches[0].real_kbo == "0439401387"
    assert matches[0].score >= 80.0

    # Phone should be re-emitted under real KBO with confidence * 0.9
    rows = await clean_pool.fetch(
        "SELECT confidence, kbo_number FROM observations "
        "WHERE kbo_number = $1 AND field = 'phone' AND source = 'goudengids'",
        "0439401387",
    )
    assert len(rows) >= 1
    assert all(float(r["confidence"]) <= 0.85 * 0.9 + 0.01 for r in rows)


async def test_consolidate_no_match_different_names(clean_pool) -> None:
    runs_repo = RunsRepo(clean_pool)
    run_id = await runs_repo.start_run(source="kbo_dump")

    await _seed_obs(
        clean_pool, "0439401387", "name", {"text": "Bellock NV", "lang": "nl"}, "kbo_dump", run_id
    )
    await _seed_obs(
        clean_pool,
        "0439401387",
        "address",
        {"postal_code": "2060", "city": "Antwerpen", "country": "BE", "street": ""},
        "kbo_dump",
        run_id,
    )

    placeholder = "9000000001"
    await _seed_obs(
        clean_pool,
        placeholder,
        "name",
        {"text": "Totally Different SA", "lang": "nl"},
        "goudengids",
        run_id,
    )
    await _seed_obs(
        clean_pool,
        placeholder,
        "address",
        {"postal_code": "2060", "city": "Antwerpen", "country": "BE", "street": ""},
        "goudengids",
        run_id,
    )

    await clean_pool.execute("SELECT refresh_companies_current()")
    matches = await consolidate(clean_pool)

    assert not any(m.placeholder_kbo == placeholder for m in matches)


async def test_consolidate_re_emits_under_real_kbo_after_matview_refresh(clean_pool) -> None:
    runs_repo = RunsRepo(clean_pool)
    run_id = await runs_repo.start_run(source="kbo_dump")

    await _seed_obs(
        clean_pool, "0439401387", "name", {"text": "Bellock NV", "lang": "nl"}, "kbo_dump", run_id
    )
    await _seed_obs(
        clean_pool,
        "0439401387",
        "address",
        {"postal_code": "2060", "city": "Antwerpen", "country": "BE", "street": ""},
        "kbo_dump",
        run_id,
    )
    await _seed_obs(
        clean_pool, "0439401387", "founding_date", {"iso": "1989-12-28"}, "kbo_dump", run_id
    )

    placeholder = "9439401388"
    await _seed_obs(
        clean_pool, placeholder, "name", {"text": "Bellock", "lang": "nl"}, "goudengids", run_id
    )
    await _seed_obs(
        clean_pool,
        placeholder,
        "address",
        {"postal_code": "2060", "city": "Antwerpen", "country": "BE", "street": ""},
        "goudengids",
        run_id,
    )

    await clean_pool.execute("SELECT refresh_companies_current()")
    await consolidate(clean_pool)
    await clean_pool.execute("SELECT refresh_companies_current()")

    fields_row = await clean_pool.fetch(
        "SELECT DISTINCT field FROM companies_current WHERE kbo_number = $1",
        "0439401387",
    )
    fields = {r["field"] for r in fields_row}
    assert "name" in fields
    assert "founding_date" in fields
    assert "address" in fields
