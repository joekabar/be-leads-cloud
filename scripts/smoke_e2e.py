#!/usr/bin/env python
"""Standalone end-to-end smoke test runner.

Usage:
    uv run python scripts/smoke_e2e.py              # mocked NBB/Brave
    uv run python scripts/smoke_e2e.py --live       # real APIs if env keys set
"""

from __future__ import annotations

import asyncio
import os
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(_ROOT / "src"))

_MINI = _ROOT / "tests" / "golden" / "kbo_dump" / "synthetic_mini"
_NOW = datetime(2026, 5, 13, 12, 0, 0, tzinfo=UTC)

_PASS = "\033[32mPASS\033[0m"
_FAIL = "\033[31mFAIL\033[0m"

_results: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = _PASS if condition else _FAIL
    msg = f"  [{tag}] {name}"
    if detail:
        msg += f" — {detail}"
    print(msg)
    _results.append((name, condition, detail))


def _create_fixture_zip(tmp_dir: Path) -> Path:
    out = tmp_dir / "KboOpenData_fixture_Full.zip"
    with zipfile.ZipFile(out, "w") as zf:
        for f in _MINI.glob("*.csv"):
            zf.write(f, arcname=f.name)
    return out


async def _run_smoke(live: bool) -> None:
    import tempfile

    import asyncpg

    from scraper.db.migrations.runner import apply_pending
    from scraper.db.models import Observation
    from scraper.db.repositories.observations import ObservationsRepo
    from scraper.db.repositories.runs import RunsRepo
    from scraper.pipeline.consolidate import consolidate
    from scraper.sources.kbo_dump.ingester import ingest_zip

    db_url = os.environ.get("DATABASE_URL", "postgresql://leads:leads@localhost:5432/leads")

    def _init_jsonb(conn):  # type: ignore[no-untyped-def]
        import json as _json

        return conn.set_type_codec(
            "jsonb",
            encoder=_json.dumps,
            decoder=_json.loads,
            schema="pg_catalog",
        )

    print(f"\nConnecting to {db_url!r}…")
    pool = await asyncpg.create_pool(db_url, min_size=1, max_size=5, init=_init_jsonb)
    assert pool is not None

    migrations_dir = _ROOT / "src" / "scraper" / "db" / "migrations"

    try:
        await apply_pending(pool, migrations_dir)
        print("Migrations applied.")

        # Clean slate for smoke test
        await pool.execute("TRUNCATE observations, jobs, run_log RESTART IDENTITY CASCADE")
        await pool.execute("SELECT refresh_companies_current()")

        print("\nStep 1: ingest kbo_dump synthetic fixture…")
        with tempfile.TemporaryDirectory() as tmpd:
            zip_path = _create_fixture_zip(Path(tmpd))
            report = await ingest_zip(zip_path, pool, refresh_view=False)

        check("kbo_dump enterprises_processed", report.enterprises_processed == 5)
        check("kbo_dump observations_inserted", report.observations_inserted >= 30)

        print("\nStep 2: seed enrichment observations…")
        runs_repo = RunsRepo(pool)
        obs_repo = ObservationsRepo(pool)

        run_id = await runs_repo.start_run(source="kbopub")
        await obs_repo.insert(
            Observation(
                kbo_number="0439401387",
                field="function_holder",
                value={"name": "Boonen Peter", "role": "director", "since": "2005-01-01"},
                source="kbopub",
                observed_at=_NOW,
                confidence=0.95,
                run_id=run_id,
            )
        )

        run_id2 = await runs_repo.start_run(source="nbb_authentic")
        await obs_repo.insert(
            Observation(
                kbo_number="0439401387",
                field="revenue_2023",
                value={"eur": 1_500_000, "year": 2023},
                source="nbb_authentic",
                observed_at=_NOW,
                confidence=1.0,
                run_id=run_id2,
            )
        )

        run_id3 = await runs_repo.start_run(source="goudengids")
        await obs_repo.insert(
            Observation(
                kbo_number="0439401387",
                field="website",
                value={"url": "https://www.bellock.be", "tld": "be"},
                source="goudengids",
                observed_at=_NOW,
                confidence=0.85,
                run_id=run_id3,
            )
        )

        # Seed placeholder for consolidation test
        placeholder = "9439401000"
        await obs_repo.insert(
            Observation(
                kbo_number=placeholder,
                field="name",
                value={"text": "Bellock NV", "lang": "nl"},
                source="goudengids",
                observed_at=_NOW,
                confidence=0.85,
                run_id=run_id3,
            )
        )
        await obs_repo.insert(
            Observation(
                kbo_number=placeholder,
                field="address",
                value={"postal_code": "2060", "city": "Antwerpen", "street": "", "country": "BE"},
                source="goudengids",
                observed_at=_NOW,
                confidence=0.80,
                run_id=run_id3,
            )
        )

        print("\nStep 3: refresh matview + consolidate…")
        await pool.execute("SELECT refresh_companies_current()")
        matches = await consolidate(pool)
        await pool.execute("SELECT refresh_companies_current()")

        check("consolidation_matches >= 1", len(matches) >= 1, f"got {len(matches)}")

        print("\nStep 4: assert Bellock in companies_current with >=6 fields…")
        rows = await pool.fetch(
            "SELECT field, value FROM companies_current WHERE kbo_number = '0439401387' ORDER BY field"
        )
        fields = {r["field"] for r in rows}

        check("field_count >= 6", len(fields) >= 6, f"fields={sorted(fields)}")
        check("name present", "name" in fields)
        check("phone present", "phone" in fields)
        check("founding_date present", "founding_date" in fields)
        check("website present", "website" in fields)
        check("function_holder present", "function_holder" in fields)
        check("revenue_2023 present", "revenue_2023" in fields)

        phone_row = next((r for r in rows if r["field"] == "phone"), None)
        if phone_row:
            pval = dict(phone_row["value"])
            check("phone_e164", pval.get("e164") == "+3232361306", str(pval.get("e164")))

        fd_row = next((r for r in rows if r["field"] == "founding_date"), None)
        if fd_row:
            fdval = dict(fd_row["value"])
            check("founding_date_iso", fdval.get("iso") == "1989-12-28", str(fdval.get("iso")))

        web_row = next((r for r in rows if r["field"] == "website"), None)
        if web_row:
            wval = dict(web_row["value"])
            check("website_contains_bellock", "bellock" in wval.get("url", "").lower())

        fh_row = next((r for r in rows if r["field"] == "function_holder"), None)
        if fh_row:
            fhval = dict(fh_row["value"])
            check("function_holder_boonen", "Boonen" in fhval.get("name", ""))

        print("\nStep 5: companies_current row count…")
        count_row = await pool.fetchrow(
            "SELECT COUNT(DISTINCT kbo_number) AS n FROM companies_current"
        )
        n = int(count_row["n"]) if count_row else 0
        check("companies_in_view >= 1", n >= 1, f"n={n}")

    finally:
        await pool.close()


def main() -> int:
    live = "--live" in sys.argv

    print("=" * 60)
    print(f"be-leads smoke test (live={live})")
    print("=" * 60)

    asyncio.run(_run_smoke(live=live))

    passed = sum(1 for _, ok, _ in _results if ok)
    failed = sum(1 for _, ok, _ in _results if not ok)

    print()
    print("=" * 60)
    if failed == 0:
        print(f"\033[32mALL ASSERTIONS PASSED ({passed}/{passed})\033[0m")
    else:
        print(f"\033[31mFAILED {failed}/{passed + failed} assertions\033[0m")
    print("=" * 60)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
