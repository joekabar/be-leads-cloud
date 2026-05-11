"""Integration tests for goudengids ingester — HTTP mocked with respx, real DB."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from scraper.sources.goudengids.ingester import GoudengidsReport, ingest_sector_city

pytestmark = pytest.mark.integration

_GOLDEN = Path("tests/golden/goudengids")
_BASE = "https://www.goudengids.be"


def _page_html(name: str) -> str:
    return (_GOLDEN / name).read_text(encoding="utf-8")


def _make_url(sector: str, city: str, page: int) -> str:
    return f"{_BASE}/zoeken/{sector}/{city}/{page}/"


@pytest.fixture()
async def fresh_pool(clean_pool):  # type: ignore[no-untyped-def]
    await clean_pool.execute("SELECT refresh_companies_current()")
    return clean_pool


@pytest.mark.asyncio
async def test_ingest_three_pages_stops_on_empty(
    fresh_pool,
    goudengids_fetcher,  # type: ignore[no-untyped-def]
) -> None:
    """3-page scenario: page1=10 cards, page2=10 cards, page3=empty → stop."""
    antwerpen = _page_html("listing_antwerpen_electriciens_page1.html")
    brugge_sparse = _page_html("listing_brugge_bakkers_page2.html")
    no_results = _page_html("listing_no_results.html")

    with respx.mock:
        respx.get(_make_url("elektriciens", "antwerpen", 1)).mock(
            return_value=httpx.Response(200, text=antwerpen)
        )
        respx.get(_make_url("elektriciens", "antwerpen", 2)).mock(
            return_value=httpx.Response(200, text=brugge_sparse)
        )
        respx.get(_make_url("elektriciens", "antwerpen", 3)).mock(
            return_value=httpx.Response(200, text=no_results)
        )
        report = await ingest_sector_city(
            "elektriciens",
            "antwerpen",
            fresh_pool,
            goudengids_fetcher,
            max_pages=10,
            skip_recent_hours=0,
        )

    assert isinstance(report, GoudengidsReport)
    assert report.pages_scanned == 3
    assert report.cards_found == 18  # 12 + 6
    assert report.observations_inserted >= 60  # at least 3-4 obs per card x 18 cards


@pytest.mark.asyncio
async def test_ingest_observations_written_to_db(
    fresh_pool,
    goudengids_fetcher,  # type: ignore[no-untyped-def]
) -> None:
    with respx.mock:
        respx.get(_make_url("elektriciens", "antwerpen", 1)).mock(
            return_value=httpx.Response(
                200, text=_page_html("listing_antwerpen_electriciens_page1.html")
            )
        )
        respx.get(_make_url("elektriciens", "antwerpen", 2)).mock(
            return_value=httpx.Response(200, text=_page_html("listing_no_results.html"))
        )
        await ingest_sector_city(
            "elektriciens",
            "antwerpen",
            fresh_pool,
            goudengids_fetcher,
            skip_recent_hours=0,
        )

    rows = await fresh_pool.fetch(
        "SELECT DISTINCT kbo_number FROM observations WHERE source = 'goudengids'"
    )
    # All placeholder KBOs start with 9
    assert all(r["kbo_number"].startswith("9") for r in rows)
    assert len(rows) == 12  # 12 distinct cards → 12 placeholder KBOs


@pytest.mark.asyncio
async def test_ingest_idempotent_within_24h(
    fresh_pool,
    goudengids_fetcher,  # type: ignore[no-untyped-def]
) -> None:
    antwerpen = _page_html("listing_antwerpen_electriciens_page1.html")
    no_results = _page_html("listing_no_results.html")

    def _mock_pages() -> None:
        respx.get(_make_url("elektriciens", "antwerpen", 1)).mock(
            return_value=httpx.Response(200, text=antwerpen)
        )
        respx.get(_make_url("elektriciens", "antwerpen", 2)).mock(
            return_value=httpx.Response(200, text=no_results)
        )

    with respx.mock:
        _mock_pages()
        report1 = await ingest_sector_city(
            "elektriciens", "antwerpen", fresh_pool, goudengids_fetcher, skip_recent_hours=24
        )

    with respx.mock:
        _mock_pages()
        report2 = await ingest_sector_city(
            "elektriciens", "antwerpen", fresh_pool, goudengids_fetcher, skip_recent_hours=24
        )

    assert report1.observations_inserted > 0
    assert report2.observations_inserted == 0


@pytest.mark.asyncio
async def test_ingest_force_reingest_with_skip_zero(
    fresh_pool,
    goudengids_fetcher,  # type: ignore[no-untyped-def]
) -> None:
    antwerpen = _page_html("listing_antwerpen_electriciens_page1.html")
    no_results = _page_html("listing_no_results.html")

    def _mock_pages() -> None:
        respx.get(_make_url("elektriciens", "antwerpen", 1)).mock(
            return_value=httpx.Response(200, text=antwerpen)
        )
        respx.get(_make_url("elektriciens", "antwerpen", 2)).mock(
            return_value=httpx.Response(200, text=no_results)
        )

    with respx.mock:
        _mock_pages()
        report1 = await ingest_sector_city(
            "elektriciens", "antwerpen", fresh_pool, goudengids_fetcher, skip_recent_hours=24
        )

    with respx.mock:
        _mock_pages()
        report2 = await ingest_sector_city(
            "elektriciens", "antwerpen", fresh_pool, goudengids_fetcher, skip_recent_hours=0
        )

    assert report1.observations_inserted > 0
    assert report2.observations_inserted > 0


@pytest.mark.asyncio
async def test_ingest_invalid_sector_raises(
    fresh_pool,
    goudengids_fetcher,  # type: ignore[no-untyped-def]
) -> None:
    with pytest.raises(ValueError, match="Unknown sector slug"):
        await ingest_sector_city("nonexistent-sector", "antwerpen", fresh_pool, goudengids_fetcher)


@pytest.mark.asyncio
async def test_ingest_empty_city_raises(
    fresh_pool,
    goudengids_fetcher,  # type: ignore[no-untyped-def]
) -> None:
    with pytest.raises(ValueError, match="city_slug"):
        await ingest_sector_city("elektriciens", "  ", fresh_pool, goudengids_fetcher)
