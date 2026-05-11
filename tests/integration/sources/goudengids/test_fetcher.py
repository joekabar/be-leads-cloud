"""Integration tests for GoudengidsFetcher — HTTP mocked with respx."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from scraper.lib.errors import BlockedError
from scraper.sources.goudengids.fetcher import GoudengidsFetcher, ListingPage

pytestmark = pytest.mark.integration

_GOLDEN = Path("tests/golden/goudengids")
_BASE = "https://www.goudengids.be"


def _antwerpen_html() -> str:
    return (_GOLDEN / "listing_antwerpen_electriciens_page1.html").read_text(encoding="utf-8")


def _no_results_html() -> str:
    return (_GOLDEN / "listing_no_results.html").read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_fetch_page_returns_listing_page(goudengids_fetcher: GoudengidsFetcher) -> None:
    with respx.mock:
        respx.get(_BASE + "/zoeken/elektriciens/antwerpen/1/").mock(
            return_value=httpx.Response(200, text=_antwerpen_html())
        )
        page = await goudengids_fetcher.fetch_page("elektriciens", "antwerpen", 1)

    assert isinstance(page, ListingPage)
    assert page.cards_found == 12
    assert page.is_last_page is False


@pytest.mark.asyncio
async def test_fetch_page_warmup_cookies_injected(goudengids_fetcher: GoudengidsFetcher) -> None:
    """Warmup cookies from _warmup_result are sent on each request."""
    captured_cookie_header: list[str] = []

    def _capture(request: httpx.Request) -> httpx.Response:
        captured_cookie_header.append(request.headers.get("cookie", ""))
        return httpx.Response(200, text=_antwerpen_html())

    with respx.mock:
        respx.get(_BASE + "/zoeken/elektriciens/antwerpen/1/").mock(side_effect=_capture)
        await goudengids_fetcher.fetch_page("elektriciens", "antwerpen", 1)

    assert captured_cookie_header, "no request was made"
    cookie_str = captured_cookie_header[0]
    # Both warmup cookie names must appear in the Cookie header
    assert "incap_ses_test" in cookie_str
    assert "visid_incap_test" in cookie_str


@pytest.mark.asyncio
async def test_fetch_page_no_results_is_last_page(goudengids_fetcher: GoudengidsFetcher) -> None:
    with respx.mock:
        respx.get(_BASE + "/zoeken/elektriciens/mol/1/").mock(
            return_value=httpx.Response(200, text=_no_results_html())
        )
        page = await goudengids_fetcher.fetch_page("elektriciens", "mol", 1)

    assert page.is_last_page is True
    assert page.cards_found == 0


@pytest.mark.asyncio
async def test_fetch_page_403_triggers_rewarm_then_succeeds(
    goudengids_fetcher: GoudengidsFetcher,
) -> None:
    call_count = 0

    def _flaky(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(403)
        return httpx.Response(200, text=_antwerpen_html())

    with respx.mock:
        respx.get(_BASE + "/zoeken/elektriciens/antwerpen/1/").mock(side_effect=_flaky)
        page = await goudengids_fetcher.fetch_page("elektriciens", "antwerpen", 1)

    assert page.cards_found == 12
    assert call_count == 2


@pytest.mark.asyncio
async def test_fetch_page_two_consecutive_403_raises_blocked_error(
    goudengids_fetcher: GoudengidsFetcher,
) -> None:
    with respx.mock:
        respx.get(_BASE + "/zoeken/elektriciens/antwerpen/1/").mock(
            return_value=httpx.Response(403)
        )
        with pytest.raises(BlockedError):
            await goudengids_fetcher.fetch_page("elektriciens", "antwerpen", 1)


@pytest.mark.asyncio
async def test_fetch_page_fr_uses_pagesdor_url(
    fast_limiter,  # type: ignore[no-untyped-def]
    patch_warmup,  # type: ignore[no-untyped-def]
) -> None:
    from datetime import UTC, datetime

    from scraper.lib.http.client import get_polite_client
    from scraper.sources.goudengids.warmup import WarmupResult

    async with get_polite_client(fast_limiter) as polite_client:
        fetcher = GoudengidsFetcher(polite_client, domain="pagesdor.be")
        fetcher._warmup_result = WarmupResult(
            cookies={"incap_ses_test": "v"},
            obtained_at=datetime.now(tz=UTC),
        )

        with respx.mock:
            respx.get("https://www.pagesdor.be/recherche/electriciens/liege/1/").mock(
                return_value=httpx.Response(
                    200,
                    text=(_GOLDEN / "listing_french_liege_plombiers.html").read_text(
                        encoding="utf-8"
                    ),
                )
            )
            page = await fetcher.fetch_page("electriciens", "liege", 1, lang="fr")

    assert page.cards_found == 4


@pytest.mark.asyncio
async def test_city_slug_spaces_replaced_with_hyphens(
    goudengids_fetcher: GoudengidsFetcher,
) -> None:
    with respx.mock:
        respx.get(_BASE + "/zoeken/elektriciens/sint-niklaas/1/").mock(
            return_value=httpx.Response(200, text=_no_results_html())
        )
        page = await goudengids_fetcher.fetch_page("elektriciens", "Sint Niklaas", 1)

    assert page.is_last_page is True
