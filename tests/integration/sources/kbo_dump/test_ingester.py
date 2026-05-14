from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from scraper.sources.kbo_dump.ingester import ingest_zip

pytestmark = pytest.mark.integration


@pytest.fixture()
async def fresh_pool(clean_pool):  # type: ignore[no-untyped-def]
    """clean_pool with companies_current refreshed to empty state."""
    await clean_pool.execute("SELECT refresh_companies_current()")
    return clean_pool


async def test_ingest_full_zip_observation_count(synthetic_zip: Path, fresh_pool) -> None:
    report = await ingest_zip(synthetic_zip, fresh_pool, refresh_view=True)

    assert report.extract_type == "Full"
    assert report.snapshot_date.isoformat() == "2026-04-15"
    assert report.enterprises_processed == 5
    # 5 founding_date + 5 status + 7 name + 5 address + 4 phone + 3 email + 2 website + 8 nace = 39
    assert report.observations_inserted == 39
    assert report.phones_invalid_skipped == 1


async def test_reingest_without_truncate_creates_duplicates(
    synthetic_zip: Path, fresh_pool
) -> None:
    """Without truncate_first, re-ingest inserts duplicate rows; dedup is at matview refresh."""
    report1 = await ingest_zip(synthetic_zip, fresh_pool, refresh_view=False)
    report2 = await ingest_zip(synthetic_zip, fresh_pool, refresh_view=False)
    assert report2.observations_inserted == report1.observations_inserted


async def test_ingest_companies_current_bellock(synthetic_zip: Path, fresh_pool) -> None:
    await ingest_zip(synthetic_zip, fresh_pool, refresh_view=True)

    rows = await fresh_pool.fetch(
        "SELECT field, value FROM companies_current WHERE kbo_number = $1 ORDER BY field",
        "0439401387",
    )
    fields = {r["field"] for r in rows}
    assert "name" in fields
    assert "founding_date" in fields
    assert "address" in fields
    assert len(rows) >= 3


async def test_ingest_founding_date_value(synthetic_zip: Path, fresh_pool) -> None:
    await ingest_zip(synthetic_zip, fresh_pool, refresh_view=True)

    row = await fresh_pool.fetchrow(
        """
        SELECT value FROM companies_current
        WHERE kbo_number = $1 AND field = 'founding_date'
        """,
        "0439401387",
    )
    assert row is not None
    assert row["value"]["iso"] == "1989-12-28"


async def test_ingest_name_value(synthetic_zip: Path, fresh_pool) -> None:
    await ingest_zip(synthetic_zip, fresh_pool, refresh_view=True)

    row = await fresh_pool.fetchrow(
        """
        SELECT value FROM companies_current
        WHERE kbo_number = $1 AND field = 'name'
        """,
        "0439401387",
    )
    assert row is not None
    # companies_current picks highest-confidence name (001 = 1.00)
    assert row["value"]["text"] == "Bellock NV"


async def test_ingest_phone_skip_counted(synthetic_zip: Path, fresh_pool) -> None:
    report = await ingest_zip(synthetic_zip, fresh_pool, refresh_view=False)
    assert report.phones_invalid_skipped == 1


async def test_ingest_update_zip_delete_marker(
    synthetic_zip: Path, fresh_pool, tmp_path: Path
) -> None:
    """Update ZIP with an enterprise_delete.csv produces a status=deleted observation."""
    # First do a Full ingest so 0439401387 exists
    await ingest_zip(synthetic_zip, fresh_pool, refresh_view=False)

    # Build a minimal Update ZIP
    update_zip = tmp_path / "KboOpenData_43_2026_04_Update.zip"
    with zipfile.ZipFile(update_zip, "w") as zf:
        zf.writestr(
            "meta.csv",
            "Variable,Value\n"
            "SnapshotDate,16-04-2026\n"
            "ExtractTimestamp,2026-04-16T03:00:00\n"
            "ExtractType,Update\n"
            "ExtractNumber,43\n"
            "Version,R018.00\n",
        )
        zf.writestr(
            "enterprise_delete.csv",
            "EnterpriseNumber\n0439401387\n",
        )
        zf.writestr(
            "enterprise_insert.csv",
            "EnterpriseNumber,Status,JuridicalSituation,TypeOfEnterprise,"
            "JuridicalForm,JuridicalFormCAC,StartDate\n",
        )

    report = await ingest_zip(update_zip, fresh_pool, refresh_view=True)
    assert report.extract_type == "Update"

    # Verify a status=deleted observation exists for 0439401387
    rows = await fresh_pool.fetch(
        """
        SELECT value FROM observations
        WHERE kbo_number = $1 AND field = 'status' AND source = 'kbo_dump'
        ORDER BY observed_at DESC
        """,
        "0439401387",
    )
    assert any(r["value"].get("value") == "deleted" for r in rows)


async def test_ingest_sector_filter(synthetic_zip: Path, fresh_pool) -> None:
    """sector_filter='43' should keep only enterprises with NACE 43.x activity."""
    report = await ingest_zip(synthetic_zip, fresh_pool, sector_filter=["43"], refresh_view=False)
    # Only 0439401387 has NACE 43.x
    kbos = await fresh_pool.fetch(
        "SELECT DISTINCT kbo_number FROM observations WHERE source = 'kbo_dump'"
    )
    assert all(r["kbo_number"].strip() == "0439401387" for r in kbos)
    assert report.enterprises_processed == 1


@pytest.mark.slow
async def test_ingest_large_zip_200_plus_observations(large_zip: Path, fresh_pool) -> None:
    """10k-enterprise fixture produces ≥30k observations."""
    report = await ingest_zip(large_zip, fresh_pool, refresh_view=False)
    assert report.enterprises_processed == 10_000
    assert report.observations_inserted >= 30_000


async def test_skip_if_fresh_skips_when_data_exists(synthetic_zip: Path, fresh_pool) -> None:
    """Second call with skip_if_fresh=True returns 0 observations when month already ingested."""
    first = await ingest_zip(synthetic_zip, fresh_pool, refresh_view=False)
    assert first.observations_inserted > 0

    second = await ingest_zip(synthetic_zip, fresh_pool, refresh_view=False, skip_if_fresh=True)
    assert second.observations_inserted == 0
    assert second.enterprises_processed == 0

    # Row count must not have grown
    count_after = await fresh_pool.fetchval(
        "SELECT COUNT(*) FROM observations WHERE source = 'kbo_dump'"
    )
    assert count_after == first.observations_inserted


async def test_skip_if_fresh_runs_when_no_data(synthetic_zip: Path, fresh_pool) -> None:
    """skip_if_fresh=True on an empty DB performs a normal ingest."""
    report = await ingest_zip(synthetic_zip, fresh_pool, refresh_view=False, skip_if_fresh=True)
    assert report.observations_inserted > 0


async def test_ingest_city_filter(synthetic_zip: Path, fresh_pool) -> None:
    """city_filter=['Antwerpen'] should keep only enterprises with an Antwerpen address."""
    await ingest_zip(synthetic_zip, fresh_pool, city_filter=["Antwerpen"], refresh_view=False)
    kbos = {
        r["kbo_number"].strip()
        for r in await fresh_pool.fetch(
            "SELECT DISTINCT kbo_number FROM observations WHERE source = 'kbo_dump'"
        )
    }
    assert "0439401387" in kbos
    # Others do not have Antwerpen addresses
    assert "0123456749" not in kbos
