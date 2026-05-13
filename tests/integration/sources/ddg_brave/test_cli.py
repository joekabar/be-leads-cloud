"""Integration tests for be-leads-search-validate CLI."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.integration

_KBO_BELLOCK = "0439401387"
_KBO_P1 = "9100000001"

_BRAVE_PAYLOAD = json.loads(
    (Path("tests/golden/ddg_brave") / "brave_bellock_antwerpen.json").read_text()
)
_DDG_PAYLOAD = json.loads((Path("tests/golden/ddg_brave") / "ddg_bellock_html.json").read_text())


@pytest.mark.asyncio
async def test_inputs_file_runs_cleanly(clean_pool) -> None:  # type: ignore[no-untyped-def]

    from scraper.lib.http.client import get_polite_client
    from scraper.sources.ddg_brave.brave_client import BraveClient
    from scraper.sources.ddg_brave.ingester import validate_companies
    from tests.integration.sources.ddg_brave.conftest import make_fast_limiter

    bc = MagicMock(spec=BraveClient)
    bc.search = AsyncMock(return_value=_BRAVE_PAYLOAD)

    inputs = [(_KBO_BELLOCK, "Bellock", "Antwerpen")]
    limiter = make_fast_limiter()
    async with get_polite_client(limiter) as pc:
        report = await validate_companies(
            inputs,
            clean_pool,
            pc,
            brave_client=bc,
            ddg_client=None,
            skip_recent_hours=0,
        )

    assert report.queries_processed == 1
    out = json.dumps(
        {
            "queries_processed": report.queries_processed,
            "observations_inserted": report.observations_inserted,
        }
    )
    parsed = json.loads(out)
    assert parsed["queries_processed"] == 1


@pytest.mark.asyncio
async def test_engine_ddg_forces_ddg_path(clean_pool) -> None:  # type: ignore[no-untyped-def]
    from scraper.lib.http.client import get_polite_client
    from scraper.sources.ddg_brave.ddg_client import DdgClient
    from scraper.sources.ddg_brave.ingester import validate_companies
    from tests.integration.sources.ddg_brave.conftest import make_fast_limiter

    dc = MagicMock(spec=DdgClient)
    dc.search = AsyncMock(return_value=_DDG_PAYLOAD)

    inputs = [(_KBO_BELLOCK, "Bellock", "Antwerpen")]
    limiter = make_fast_limiter()
    async with get_polite_client(limiter) as pc:
        report = await validate_companies(
            inputs,
            clean_pool,
            pc,
            brave_client=None,
            ddg_client=dc,
            skip_recent_hours=0,
        )

    assert report.ddg_queries == 1
    assert report.brave_queries == 0


@pytest.mark.asyncio
async def test_from_db_flag_pulls_placeholder_kbos(clean_pool) -> None:  # type: ignore[no-untyped-def]
    from datetime import UTC, datetime

    from scraper.db.models import Observation
    from scraper.db.repositories.observations import ObservationsRepo
    from scraper.db.repositories.runs import RunsRepo
    from scraper.lib.http.client import get_polite_client
    from scraper.sources.ddg_brave.brave_client import BraveClient
    from scraper.sources.ddg_brave.ingester import validate_companies
    from tests.integration.sources.ddg_brave.conftest import make_fast_limiter

    # Seed a placeholder company observation so --from-db can find it
    runs_repo = RunsRepo(clean_pool)
    obs_repo = ObservationsRepo(clean_pool)
    run_id = await runs_repo.start_run(source="goudengids")
    snapshot = datetime.now(tz=UTC)
    await obs_repo.insert(
        Observation(
            kbo_number=_KBO_P1,
            field="name",
            value={"text": "TestCo", "lang": "nl"},
            raw_value="TestCo",
            source="goudengids",
            observed_at=snapshot,
            confidence=0.85,
            run_id=run_id,
        )
    )

    rows = await clean_pool.fetch(
        "SELECT kbo_number, value->>'text' AS name FROM observations "
        "WHERE field = 'name' AND kbo_number LIKE '9%'"
    )
    assert any(r["kbo_number"] == _KBO_P1 for r in rows)

    bc = MagicMock(spec=BraveClient)
    bc.search = AsyncMock(return_value=_BRAVE_PAYLOAD)

    inputs = [(r["kbo_number"], r["name"] or "", "") for r in rows if r["name"]]
    limiter = make_fast_limiter()
    async with get_polite_client(limiter) as pc:
        report = await validate_companies(
            inputs,
            clean_pool,
            pc,
            brave_client=bc,
            ddg_client=None,
            skip_recent_hours=0,
        )

    assert report.queries_processed >= 1
