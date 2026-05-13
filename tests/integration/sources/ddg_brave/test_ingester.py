"""Integration tests for ddg_brave ingester — mocked clients, real DB."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from scraper.lib.http.client import get_polite_client
from scraper.sources.ddg_brave.brave_client import BraveClient, BraveQuotaExhaustedError
from scraper.sources.ddg_brave.ddg_client import DdgClient
from scraper.sources.ddg_brave.ingester import SearchValidationReport, validate_companies

from .conftest import make_fast_limiter

pytestmark = pytest.mark.integration

_GOLDEN = Path("tests/golden/ddg_brave")

_KBO_BELLOCK = "0439401387"
_KBO_BAKK = "0502699332"  # valid mod-97 KBO used across integration tests
_KBO_P1 = "9100000001"
_KBO_P2 = "9100000002"
_KBO_P3 = "9100000003"

_BRAVE_PAYLOAD = json.loads((_GOLDEN / "brave_bellock_antwerpen.json").read_text())
_BRAVE_NO_RESULTS = json.loads((_GOLDEN / "brave_no_results.json").read_text())
_DDG_PAYLOAD = json.loads((_GOLDEN / "ddg_bellock_html.json").read_text())


@pytest.fixture()
async def fresh_pool(clean_pool):  # type: ignore[no-untyped-def]
    await clean_pool.execute("SELECT refresh_companies_current()")
    return clean_pool


def _make_brave(payload: dict | None = None, *, raises: type[Exception] | None = None) -> MagicMock:
    bc = MagicMock(spec=BraveClient)
    if raises:
        bc.search = AsyncMock(side_effect=raises("quota"))
    else:
        bc.search = AsyncMock(return_value=payload or _BRAVE_PAYLOAD)
    return bc


def _make_ddg(payload: list | None = None) -> MagicMock:
    dc = MagicMock(spec=DdgClient)
    dc.search = AsyncMock(return_value=payload or _DDG_PAYLOAD)
    return dc


@pytest.mark.asyncio
async def test_five_inputs_produce_observations(fresh_pool) -> None:  # type: ignore[no-untyped-def]
    inputs = [
        (_KBO_BELLOCK, "Bellock", "Antwerpen"),
        (_KBO_BAKK, "Bakk", "Brugge"),
        (_KBO_P1, "Alpha", "Gent"),
        (_KBO_P2, "Beta", "Leuven"),
        (_KBO_P3, "Gamma", "Luik"),
    ]
    limiter = make_fast_limiter()
    async with get_polite_client(limiter) as pc:
        report = await validate_companies(
            inputs,
            fresh_pool,
            pc,
            brave_client=_make_brave(),
            ddg_client=None,
            skip_recent_hours=0,
        )

    assert isinstance(report, SearchValidationReport)
    assert report.queries_processed == 5
    assert report.brave_queries == 5
    # Each company: at least the cross_validation obs
    assert report.observations_inserted >= 5

    rows = await fresh_pool.fetch(
        "SELECT DISTINCT kbo_number FROM observations WHERE field = 'cross_validation'"
    )
    assert len(rows) == 5


@pytest.mark.asyncio
async def test_brave_quota_exhausted_switches_to_ddg(fresh_pool) -> None:  # type: ignore[no-untyped-def]
    inputs = [
        (_KBO_P1, "Alpha", "Gent"),
        (_KBO_P2, "Beta", "Leuven"),
        (_KBO_P3, "Gamma", "Luik"),
    ]

    call_count = [0]

    async def _brave_side_effect(query, **kwargs):  # type: ignore[no-untyped-def]
        call_count[0] += 1
        if call_count[0] >= 2:
            raise BraveQuotaExhaustedError("quota")
        return _BRAVE_PAYLOAD

    bc = MagicMock(spec=BraveClient)
    bc.search = _brave_side_effect
    dc = _make_ddg()

    limiter = make_fast_limiter()
    async with get_polite_client(limiter) as pc:
        report = await validate_companies(
            inputs,
            fresh_pool,
            pc,
            brave_client=bc,
            ddg_client=dc,
            skip_recent_hours=0,
        )

    assert report.brave_quota_exhausted is True
    assert report.brave_queries == 1
    assert report.ddg_queries >= 1
    assert report.queries_processed == 3


@pytest.mark.asyncio
async def test_no_ddg_fallback_brave_exhausted(fresh_pool) -> None:  # type: ignore[no-untyped-def]
    inputs = [(_KBO_P1, "Alpha", "Gent"), (_KBO_P2, "Beta", "Leuven")]
    bc = _make_brave(raises=BraveQuotaExhaustedError)

    limiter = make_fast_limiter()
    async with get_polite_client(limiter) as pc:
        report = await validate_companies(
            inputs,
            fresh_pool,
            pc,
            brave_client=bc,
            ddg_client=None,
            skip_recent_hours=0,
            use_ddg_fallback=False,
        )

    assert report.brave_quota_exhausted is True
    assert report.queries_processed == 0
    assert report.observations_inserted == 0


@pytest.mark.asyncio
async def test_skip_recent_7_days(fresh_pool) -> None:  # type: ignore[no-untyped-def]
    inputs = [(_KBO_BELLOCK, "Bellock", "Antwerpen")]
    bc = _make_brave()

    limiter = make_fast_limiter()
    async with get_polite_client(limiter) as pc:
        report1 = await validate_companies(
            inputs,
            fresh_pool,
            pc,
            brave_client=bc,
            ddg_client=None,
            skip_recent_hours=168,
        )
        report2 = await validate_companies(
            inputs,
            fresh_pool,
            pc,
            brave_client=bc,
            ddg_client=None,
            skip_recent_hours=168,
        )

    assert report1.observations_inserted > 0
    assert report2.observations_inserted == 0
    assert report2.queries_processed == 0


@pytest.mark.asyncio
async def test_empty_results_yields_only_cv_observation(fresh_pool) -> None:  # type: ignore[no-untyped-def]
    inputs = [(_KBO_P1, "Unknown", "Gent")]
    bc = _make_brave(payload=_BRAVE_NO_RESULTS)

    limiter = make_fast_limiter()
    async with get_polite_client(limiter) as pc:
        report = await validate_companies(
            inputs,
            fresh_pool,
            pc,
            brave_client=bc,
            ddg_client=None,
            skip_recent_hours=0,
        )

    assert report.websites_confirmed == 0
    rows = await fresh_pool.fetch("SELECT field FROM observations WHERE kbo_number = $1", _KBO_P1)
    fields = {r["field"] for r in rows}
    assert "cross_validation" in fields
    assert "website" not in fields


@pytest.mark.asyncio
async def test_brave_auth_error_marks_quota_exhausted(fresh_pool) -> None:  # type: ignore[no-untyped-def]
    from scraper.sources.ddg_brave.brave_client import BraveAuthError

    inputs = [(_KBO_P1, "Alpha", "Gent"), (_KBO_P2, "Beta", "Leuven")]
    bc = _make_brave(raises=BraveAuthError)

    limiter = make_fast_limiter()
    async with get_polite_client(limiter) as pc:
        report = await validate_companies(
            inputs,
            fresh_pool,
            pc,
            brave_client=bc,
            ddg_client=None,
            skip_recent_hours=0,
        )

    assert report.brave_quota_exhausted is True
    assert len(report.errors) > 0


@pytest.mark.asyncio
async def test_ddg_rate_limited_skips_gracefully(fresh_pool) -> None:  # type: ignore[no-untyped-def]
    from scraper.sources.ddg_brave.ddg_client import DdgRateLimitedError

    dc = MagicMock(spec=DdgClient)
    dc.search = AsyncMock(side_effect=DdgRateLimitedError("rate limited"))

    inputs = [(_KBO_P1, "Alpha", "Gent")]
    limiter = make_fast_limiter()
    async with get_polite_client(limiter) as pc:
        report = await validate_companies(
            inputs,
            fresh_pool,
            pc,
            brave_client=None,
            ddg_client=dc,
            skip_recent_hours=0,
        )

    assert report.queries_processed == 0
    assert len(report.errors) > 0


@pytest.mark.asyncio
async def test_batch_flush_mid_loop(fresh_pool) -> None:  # type: ignore[no-untyped-def]
    """Verify buffer flushes when it reaches _BATCH_SIZE."""
    from unittest.mock import patch

    inputs = [
        (_KBO_P1, "Alpha", "Gent"),
        (_KBO_P2, "Beta", "Leuven"),
        (_KBO_P3, "Gamma", "Luik"),
    ]
    bc = _make_brave()

    limiter = make_fast_limiter()
    # Patch _BATCH_SIZE to 2 so the flush triggers during the loop (3 companies x 2 obs = 6 > 2)
    with patch("scraper.sources.ddg_brave.ingester._BATCH_SIZE", 2):
        async with get_polite_client(limiter) as pc:
            report = await validate_companies(
                inputs,
                fresh_pool,
                pc,
                brave_client=bc,
                ddg_client=None,
                skip_recent_hours=0,
            )

    assert report.queries_processed == 3
    assert report.observations_inserted >= 3
