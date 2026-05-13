"""End-to-end smoke test: full pipeline from fixture data → Bellock in companies_current."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime

import pytest

from scraper.db.models import Observation
from scraper.db.repositories.observations import ObservationsRepo
from scraper.db.repositories.runs import RunsRepo
from scraper.pipeline.consolidate import consolidate
from scraper.sources.kbo_dump.ingester import ingest_zip

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 5, 13, 12, 0, 0, tzinfo=UTC)


async def _insert(pool, kbo: str, field: str, value: dict, source: str) -> None:
    run_id = await RunsRepo(pool).start_run(source=source)
    await ObservationsRepo(pool).insert(
        Observation(
            kbo_number=kbo,
            field=field,
            value=value,
            source=source,
            observed_at=_NOW,
            confidence=0.90,
            run_id=run_id,
        )
    )


async def test_bellock_emerges_with_six_fields(clean_pool, pipeline_synthetic_zip) -> None:
    """Full fixture ingest + manual enrichment seeds + consolidation → Bellock ≥6 fields."""
    # Step 1: ingest kbo_dump synthetic mini (gives name, address, phone, founding_date, nace, status)
    await ingest_zip(pipeline_synthetic_zip, clean_pool, refresh_view=False)

    # Step 2: seed kbopub function_holder observation
    await _insert(
        clean_pool,
        "0439401387",
        "function_holder",
        {"name": "Boonen Peter", "role": "director", "since": "2005-01-01"},
        "kbopub",
    )

    # Step 3: seed NBB financial observation
    await _insert(
        clean_pool,
        "0439401387",
        "revenue_2023",
        {"eur": 1500000, "year": 2023},
        "nbb_authentic",
    )

    # Step 4: seed a website observation
    await _insert(
        clean_pool,
        "0439401387",
        "website",
        {"url": "https://www.bellock.be", "tld": "be"},
        "goudengids",
    )

    # Step 5: seed a goudengids placeholder that consolidates to Bellock
    run_id = await RunsRepo(clean_pool).start_run(source="goudengids")
    obs_repo = ObservationsRepo(clean_pool)
    placeholder = "9439401000"
    await obs_repo.insert(
        Observation(
            kbo_number=placeholder,
            field="name",
            value={"text": "Bellock NV", "lang": "nl"},
            source="goudengids",
            observed_at=_NOW,
            confidence=0.85,
            run_id=run_id,
        )
    )
    await obs_repo.insert(
        Observation(
            kbo_number=placeholder,
            field="address",
            value={
                "street": "Lange Van Bloerstraat",
                "postal_code": "2060",
                "city": "Antwerpen",
                "country": "BE",
            },
            source="goudengids",
            observed_at=_NOW,
            confidence=0.80,
            run_id=run_id,
        )
    )
    await obs_repo.insert(
        Observation(
            kbo_number=placeholder,
            field="phone",
            value={"e164": "+3232361306", "raw": "03 236 13 06", "type": "landline"},
            source="goudengids",
            observed_at=_NOW,
            confidence=0.85,
            run_id=run_id,
        )
    )

    # Step 6: refresh matview + run consolidation
    await clean_pool.execute("SELECT refresh_companies_current()")
    await consolidate(clean_pool)
    await clean_pool.execute("SELECT refresh_companies_current()")

    # Step 7: assert Bellock has ≥6 distinct fields
    rows = await clean_pool.fetch(
        "SELECT DISTINCT field FROM companies_current WHERE kbo_number = '0439401387'"
    )
    fields = {r["field"] for r in rows}

    assert len(fields) >= 6, f"Expected ≥6 fields for Bellock, got {sorted(fields)}"

    # Specific field assertions
    assert "name" in fields
    assert "founding_date" in fields
    assert "function_holder" in fields
    assert "revenue_2023" in fields
    assert "website" in fields

    # Check phone value shape
    phone_row = await clean_pool.fetchrow(
        "SELECT value FROM companies_current WHERE kbo_number = '0439401387' AND field = 'phone'"
    )
    assert phone_row is not None
    phone_val = dict(phone_row["value"])
    assert phone_val.get("e164") == "+3232361306"

    # Check founding_date
    fd_row = await clean_pool.fetchrow(
        "SELECT value FROM companies_current WHERE kbo_number = '0439401387' AND field = 'founding_date'"
    )
    assert fd_row is not None
    assert "1989-12-28" in str(dict(fd_row["value"]).get("iso", ""))

    # Check website contains "bellock"
    web_row = await clean_pool.fetchrow(
        "SELECT value FROM companies_current WHERE kbo_number = '0439401387' AND field = 'website'"
    )
    assert web_row is not None
    assert "bellock" in dict(web_row["value"]).get("url", "").lower()

    # Check function_holder contains "Boonen"
    fh_row = await clean_pool.fetchrow(
        "SELECT value FROM companies_current WHERE kbo_number = '0439401387' AND field = 'function_holder'"
    )
    assert fh_row is not None
    assert "Boonen" in dict(fh_row["value"]).get("name", "")


async def test_companies_current_row_count_gte_one(clean_pool, pipeline_synthetic_zip) -> None:
    """After kbo_dump fixture ingest, companies_current has ≥1 row."""
    await ingest_zip(pipeline_synthetic_zip, clean_pool, refresh_view=True)
    row = await clean_pool.fetchrow("SELECT COUNT(DISTINCT kbo_number) AS n FROM companies_current")
    assert row is not None
    assert int(row["n"]) >= 1


def test_cli_exits_zero_kbo_dump_only(test_db_dsn: str) -> None:
    """CLI exits 0 with --use-fixture and all non-kbo-dump sources skipped."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from scraper.pipeline.cli import cli_main; import sys; "
            "sys.argv = ['be-leads-pipeline', '--sector', 'electriciens', '--city', 'antwerpen', "
            "'--use-fixture', '--skip-goudengids', '--skip-kbopub', '--skip-nbb', "
            "'--skip-website', '--skip-search', '--database-url', sys.argv[1]]; cli_main()",
            test_db_dsn,
        ],
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "DATABASE_URL": test_db_dsn},
    )
    assert result.returncode == 0, f"CLI failed:\nstdout={result.stdout}\nstderr={result.stderr}"
    import json

    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert "kbo_dump" in report["sources_run"]
    assert report["companies_in_view"] >= 1
