"""Scale integration tests for the kbo_dump ingester.

All tests use the 10k-enterprise fixture (large_zip) and are marked @pytest.mark.slow.
Run explicitly: uv run pytest -q -m slow tests/integration/sources/kbo_dump/test_ingester_scale.py
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from scraper.sources.kbo_dump.ingester import ingest_zip

pytestmark = [pytest.mark.integration, pytest.mark.slow]


@pytest.fixture()
async def fresh_pool(clean_pool):  # type: ignore[no-untyped-def]
    await clean_pool.execute("SELECT refresh_companies_current()")
    return clean_pool


@pytest.mark.slow
async def test_10k_fixture_ingests_under_60_seconds(large_zip: Path, fresh_pool) -> None:
    t0 = time.monotonic()
    report = await ingest_zip(large_zip, fresh_pool, month_label="2026-04", truncate_first=True)
    elapsed = time.monotonic() - t0
    assert elapsed < 60.0, f"10k ingest took {elapsed:.1f}s (limit 60s)"
    assert report.enterprises_processed == 10_000
    assert report.observations_inserted > 30_000


@pytest.mark.slow
async def test_sector_filter_reduces_emissions(large_zip: Path, fresh_pool) -> None:
    unfiltered = await ingest_zip(large_zip, fresh_pool, month_label="2026-04", truncate_first=True)
    filtered = await ingest_zip(
        large_zip,
        fresh_pool,
        month_label="2026-04",
        sector_filter=["43"],
        truncate_first=True,
    )
    assert filtered.observations_inserted < unfiltered.observations_inserted
    assert filtered.observations_inserted > 0


@pytest.mark.slow
async def test_city_filter_reduces_emissions(large_zip: Path, fresh_pool) -> None:
    unfiltered = await ingest_zip(large_zip, fresh_pool, month_label="2026-04", truncate_first=True)
    filtered = await ingest_zip(
        large_zip,
        fresh_pool,
        month_label="2026-04",
        city_filter=["Antwerpen"],
        truncate_first=True,
    )
    assert 0 < filtered.observations_inserted < unfiltered.observations_inserted


@pytest.mark.slow
async def test_reingest_with_truncate_first_is_idempotent(large_zip: Path, fresh_pool) -> None:
    first = await ingest_zip(large_zip, fresh_pool, month_label="2026-04", truncate_first=True)
    second = await ingest_zip(large_zip, fresh_pool, month_label="2026-04", truncate_first=True)
    assert first.observations_inserted == second.observations_inserted

    count = await fresh_pool.fetchval("SELECT count(*) FROM companies_current")
    assert count > 0


@pytest.mark.slow
async def test_reingest_without_truncate_grows_observations(large_zip: Path, fresh_pool) -> None:
    await ingest_zip(large_zip, fresh_pool, month_label="2026-04", truncate_first=True)
    obs_before = await fresh_pool.fetchval(
        "SELECT count(*) FROM observations WHERE source='kbo_dump'"
    )
    cc_before = await fresh_pool.fetchval("SELECT count(*) FROM companies_current")

    await ingest_zip(large_zip, fresh_pool, month_label="2026-04", truncate_first=False)
    obs_after = await fresh_pool.fetchval(
        "SELECT count(*) FROM observations WHERE source='kbo_dump'"
    )
    cc_after = await fresh_pool.fetchval("SELECT count(*) FROM companies_current")

    assert obs_after == 2 * obs_before, "without truncate, observations should double"
    assert cc_after == cc_before, "but companies_current is unchanged (matview resolves duplicates)"
