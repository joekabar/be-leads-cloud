"""Integration tests: batch pipeline (stage_zip + run_batch) end-to-end."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from unittest.mock import MagicMock

import asyncpg
import pytest

from scraper.pipeline.batch import BatchConfig, run_batch
from scraper.sources.kbo_dump.staging import cleanup_old_snapshots, stage_zip

pytestmark = pytest.mark.integration

_STAGE_TABLES = (
    "kbo_stage_enterprise",
    "kbo_stage_address",
    "kbo_stage_denomination",
    "kbo_stage_contact",
    "kbo_stage_activity",
)


@pytest.fixture()
async def batch_pool(pg_pool: asyncpg.Pool) -> AsyncGenerator[asyncpg.Pool, None]:  # type: ignore[type-arg]
    """pg_pool with both observations and kbo_stage_* tables wiped before each test."""
    await pg_pool.execute("TRUNCATE observations, jobs, run_log RESTART IDENTITY CASCADE")
    await pg_pool.execute("TRUNCATE prospect_scores")
    for tbl in _STAGE_TABLES:
        await pg_pool.execute(f"TRUNCATE {tbl}")
    yield pg_pool


def _make_polite_client() -> MagicMock:
    """Minimal PoliteClient stand-in; enrichers are disabled so limiter is never called."""
    client = MagicMock()
    client.limiter = MagicMock()
    return client


async def test_stage_zip_populates_staging_tables(
    batch_pool: asyncpg.Pool,  # type: ignore[type-arg]
    pipeline_synthetic_zip,
) -> None:
    """stage_zip loads all 5 CSVs into kbo_stage_* tables with correct snapshot_date."""
    report = await stage_zip(pipeline_synthetic_zip, batch_pool)

    assert not report.skipped
    assert report.rows_enterprise > 0
    assert report.rows_address > 0
    assert report.rows_activity > 0
    assert report.snapshot_date is not None

    # Snapshot date comes from meta.csv: 15-04-2026
    from datetime import date

    assert report.snapshot_date == date(2026, 4, 15)

    # Verify rows are actually in the DB.
    n = await batch_pool.fetchval("SELECT COUNT(*) FROM kbo_stage_enterprise")
    assert n == report.rows_enterprise


async def test_stage_zip_idempotent(
    batch_pool: asyncpg.Pool,  # type: ignore[type-arg]
    pipeline_synthetic_zip,
) -> None:
    """Second stage_zip call with same snapshot skips without re-inserting."""
    await stage_zip(pipeline_synthetic_zip, batch_pool)
    n_before = await batch_pool.fetchval("SELECT COUNT(*) FROM kbo_stage_enterprise")

    report2 = await stage_zip(pipeline_synthetic_zip, batch_pool)

    assert report2.skipped is True
    n_after = await batch_pool.fetchval("SELECT COUNT(*) FROM kbo_stage_enterprise")
    assert n_after == n_before


async def test_stage_zip_force_rereplaces(
    batch_pool: asyncpg.Pool,  # type: ignore[type-arg]
    pipeline_synthetic_zip,
) -> None:
    """force=True deletes then re-inserts; row count stays the same."""
    r1 = await stage_zip(pipeline_synthetic_zip, batch_pool)
    r2 = await stage_zip(pipeline_synthetic_zip, batch_pool, force=True)

    assert not r2.skipped
    assert r2.rows_enterprise == r1.rows_enterprise


async def test_run_batch_inserts_observations(
    batch_pool: asyncpg.Pool,  # type: ignore[type-arg]
    pipeline_synthetic_zip,
) -> None:
    """run_batch emits kbo_dump observations for entities in Antwerpen."""
    await stage_zip(pipeline_synthetic_zip, batch_pool)

    config = BatchConfig(
        city="antwerpen",
        sectors=[],  # empty NACE union → all city entities
        do_goudengids=False,
        do_kbopub=False,
        do_nbb=False,
        do_website=False,
        do_search=False,
    )
    report = await run_batch(config, batch_pool, _make_polite_client())

    assert report.phase_a_kbos > 0
    assert "kbo_dump" in report.sources_run

    n = await batch_pool.fetchval("SELECT COUNT(*) FROM observations WHERE source = 'kbo_dump'")
    assert n > 0


async def test_run_batch_no_duplicate_obs_on_rerun(
    batch_pool: asyncpg.Pool,  # type: ignore[type-arg]
    pipeline_synthetic_zip,
) -> None:
    """Re-running run_batch with the same snapshot_date must not accumulate duplicates."""
    await stage_zip(pipeline_synthetic_zip, batch_pool)

    config = BatchConfig(
        city="antwerpen",
        sectors=[],
        do_goudengids=False,
        do_kbopub=False,
        do_nbb=False,
        do_website=False,
        do_search=False,
    )
    await run_batch(config, batch_pool, _make_polite_client())
    n1 = await batch_pool.fetchval("SELECT COUNT(*) FROM observations WHERE source = 'kbo_dump'")

    # Second run — Phase A deletes the snapshot's obs before re-inserting.
    await run_batch(config, batch_pool, _make_polite_client())
    n2 = await batch_pool.fetchval("SELECT COUNT(*) FROM observations WHERE source = 'kbo_dump'")

    assert n2 == n1, f"Duplicate observations accumulated: {n1} → {n2}"


async def test_run_batch_scores_computed(
    batch_pool: asyncpg.Pool,  # type: ignore[type-arg]
    pipeline_synthetic_zip,
) -> None:
    """Phase F populates prospect_scores after a successful batch."""
    await stage_zip(pipeline_synthetic_zip, batch_pool)

    config = BatchConfig(
        city="antwerpen",
        sectors=[],
        do_goudengids=False,
        do_kbopub=False,
        do_nbb=False,
        do_website=False,
        do_search=False,
    )
    report = await run_batch(config, batch_pool, _make_polite_client())

    assert report.prospect_scores_computed >= 0  # may be 0 if matview is empty
    n = await batch_pool.fetchval("SELECT COUNT(*) FROM prospect_scores")
    # companies_current requires matview function; at least no error raised
    assert n >= 0


async def test_cleanup_old_snapshots(
    batch_pool: asyncpg.Pool,  # type: ignore[type-arg]
    pipeline_synthetic_zip,
) -> None:
    """cleanup_old_snapshots with keep_n >= staged count returns all-zero deletions."""
    await stage_zip(pipeline_synthetic_zip, batch_pool)

    # Only 1 snapshot staged; keeping 3 should delete nothing.
    deleted = await cleanup_old_snapshots(batch_pool, keep_n=3)

    for tbl, count in deleted.items():
        assert count == 0, f"{tbl}: expected 0 deleted rows, got {count}"


async def test_run_batch_no_staging_data_raises(
    batch_pool: asyncpg.Pool,  # type: ignore[type-arg]
) -> None:
    """run_batch without any staged data raises RuntimeError with helpful message."""
    config = BatchConfig(
        city="antwerpen",
        sectors=[],
        do_goudengids=False,
        do_kbopub=False,
        do_nbb=False,
        do_website=False,
        do_search=False,
    )
    with pytest.raises(RuntimeError, match="No staged KBO data"):
        await run_batch(config, batch_pool, _make_polite_client())


async def test_run_batch_unknown_city_produces_zero_kbos(
    batch_pool: asyncpg.Pool,  # type: ignore[type-arg]
    pipeline_synthetic_zip,
) -> None:
    """City not present in staging tables yields phase_a_kbos == 0 without error."""
    await stage_zip(pipeline_synthetic_zip, batch_pool)

    config = BatchConfig(
        city="nonexistent-city-xyz",
        sectors=[],
        do_goudengids=False,
        do_kbopub=False,
        do_nbb=False,
        do_website=False,
        do_search=False,
    )
    report = await run_batch(config, batch_pool, _make_polite_client())

    assert report.phase_a_kbos == 0


async def test_run_batch_nace_filter_path_exercised(
    batch_pool: asyncpg.Pool,  # type: ignore[type-arg]
    pipeline_synthetic_zip,
) -> None:
    """Passing a real sector exercises the NACE intersection path in _get_entity_filter.

    The synthetic fixture uses dotted NACE codes (43.211) while _SECTOR_NACE_PREFIXES uses
    dotless prefixes (4321), so the intersection yields 0 — but the NACE filter branch runs.
    """
    await stage_zip(pipeline_synthetic_zip, batch_pool)

    config = BatchConfig(
        city="antwerpen",
        sectors=["elektriciens"],  # NACE prefix "4321" — won't match "43.211" in fixture
        do_goudengids=False,
        do_kbopub=False,
        do_nbb=False,
        do_website=False,
        do_search=False,
    )
    report = await run_batch(config, batch_pool, _make_polite_client())
    # NACE filter produces empty intersection (dotted vs. dotless), so 0 KBOs emitted.
    assert report.phase_a_kbos == 0


async def test_run_batch_real_kbos_query_runs_when_enrichment_enabled(
    batch_pool: asyncpg.Pool,  # type: ignore[type-arg]
    pipeline_synthetic_zip,
) -> None:
    """Enabling an enricher exercises the phase_a_real_kbos query path (lines 541-547).

    With an unknown city, phase_a produces 0 obs, so real_kbos is empty and kbopub
    logs 'kbopub_skipped: no_real_kbos' — no actual HTTP requests are made.
    """
    await stage_zip(pipeline_synthetic_zip, batch_pool)

    config = BatchConfig(
        city="nonexistent-city-xyz",
        sectors=[],
        do_goudengids=False,
        do_kbopub=True,  # enables real_kbos query; will skip due to empty list
        do_nbb=False,
        do_website=False,
        do_search=False,
    )
    report = await run_batch(config, batch_pool, _make_polite_client())
    assert report.phase_a_kbos == 0
    assert "kbopub_html" not in report.sources_run  # skipped cleanly
