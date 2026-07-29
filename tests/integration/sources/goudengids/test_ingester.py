"""Integration tests for goudengids ingester — stub fetcher, real DB."""

from __future__ import annotations

from pathlib import Path

import pytest

from scraper.sources.goudengids.ingester import GoudengidsReport, ingest_sector_city
from tests.integration.sources.goudengids.conftest import StubBrowserFetcher

pytestmark = pytest.mark.integration

_GOLDEN = Path("tests/golden/goudengids")


def _page_html(name: str) -> str:
    return (_GOLDEN / name).read_text(encoding="utf-8")


@pytest.fixture()
async def fresh_pool(clean_pool):  # type: ignore[no-untyped-def]
    await clean_pool.execute("SELECT refresh_companies_current()")
    return clean_pool


@pytest.mark.asyncio
async def test_ingest_three_pages_stops_on_empty(fresh_pool) -> None:
    """3-page scenario: page1=12 cards, page2=6 cards, page3=empty → stop."""
    stub = StubBrowserFetcher(
        {
            ("elektriciens", "antwerpen", 1): _page_html(
                "listing_antwerpen_electriciens_page1.html"
            ),
            ("elektriciens", "antwerpen", 2): _page_html("listing_brugge_bakkers_page2.html"),
        }
    )
    report = await ingest_sector_city(
        "elektriciens",
        "antwerpen",
        fresh_pool,
        stub,
        max_pages=10,
        skip_recent_hours=0,
    )

    assert isinstance(report, GoudengidsReport)
    assert report.pages_scanned == 3
    assert report.cards_found == 18  # 12 + 6

    # Page 2 is the *Brugge* bakers fixture, reused here only to supply 6 more cards.
    # Those companies are not in Antwerpen, so the city filter drops them — which is
    # exactly what the filter exists for. Only the 12 Antwerpen cards are ingested.
    assert report.cards_out_of_city == 6
    assert report.placeholders_created == 12
    assert report.observations_inserted >= 36  # >= 3 obs per kept card x 12 cards


@pytest.mark.asyncio
async def test_ingest_observations_written_to_db(fresh_pool) -> None:
    stub = StubBrowserFetcher(
        {
            ("elektriciens", "antwerpen", 1): _page_html(
                "listing_antwerpen_electriciens_page1.html"
            ),
        }
    )
    await ingest_sector_city(
        "elektriciens",
        "antwerpen",
        fresh_pool,
        stub,
        skip_recent_hours=0,
    )

    rows = await fresh_pool.fetch(
        "SELECT DISTINCT kbo_number FROM observations WHERE source = 'goudengids'"
    )
    assert all(r["kbo_number"].startswith("9") for r in rows)
    assert len(rows) == 12


@pytest.mark.asyncio
async def test_ingest_idempotent_within_24h(fresh_pool) -> None:
    def _make_stub() -> StubBrowserFetcher:
        return StubBrowserFetcher(
            {
                ("elektriciens", "antwerpen", 1): _page_html(
                    "listing_antwerpen_electriciens_page1.html"
                ),
            }
        )

    report1 = await ingest_sector_city(
        "elektriciens", "antwerpen", fresh_pool, _make_stub(), skip_recent_hours=24
    )
    report2 = await ingest_sector_city(
        "elektriciens", "antwerpen", fresh_pool, _make_stub(), skip_recent_hours=24
    )

    assert report1.observations_inserted > 0
    assert report2.observations_inserted == 0


@pytest.mark.asyncio
async def test_ingest_force_reingest_with_skip_zero(fresh_pool) -> None:
    def _make_stub() -> StubBrowserFetcher:
        return StubBrowserFetcher(
            {
                ("elektriciens", "antwerpen", 1): _page_html(
                    "listing_antwerpen_electriciens_page1.html"
                ),
            }
        )

    report1 = await ingest_sector_city(
        "elektriciens", "antwerpen", fresh_pool, _make_stub(), skip_recent_hours=24
    )
    report2 = await ingest_sector_city(
        "elektriciens", "antwerpen", fresh_pool, _make_stub(), skip_recent_hours=0
    )

    assert report1.observations_inserted > 0
    assert report2.observations_inserted > 0


@pytest.mark.asyncio
async def test_ingest_invalid_sector_raises(fresh_pool) -> None:
    with pytest.raises(ValueError, match="Unknown sector slug"):
        await ingest_sector_city(
            "nonexistent-sector", "antwerpen", fresh_pool, StubBrowserFetcher()
        )


@pytest.mark.asyncio
async def test_ingest_empty_city_raises(fresh_pool) -> None:
    with pytest.raises(ValueError, match="city_slug"):
        await ingest_sector_city("elektriciens", "  ", fresh_pool, StubBrowserFetcher())
