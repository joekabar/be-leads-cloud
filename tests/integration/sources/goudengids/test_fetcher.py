"""Integration tests for BrowserListingFetcher — Playwright route-mocked.

Each test launches a real Chromium browser but intercepts all network requests
via context.route() so no real traffic reaches goudengids.be.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from scraper.lib.errors import BlockedError
from scraper.sources.goudengids.fetcher import BrowserListingFetcher, ListingPage

pytestmark = pytest.mark.integration

_GOLDEN = Path("tests/golden/goudengids")


def _html(name: str) -> str:
    return (_GOLDEN / name).read_text(encoding="utf-8")


async def _noop_sleep(delay: float, *args: object, **kwargs: object) -> None:
    pass


@pytest.mark.asyncio
async def test_fetch_page_returns_listing_page(fast_limiter, monkeypatch) -> None:
    html = _html("listing_antwerpen_electriciens_page1.html")
    monkeypatch.setattr(asyncio, "sleep", _noop_sleep)

    async def handler(route, _request):  # type: ignore[no-untyped-def]
        await route.fulfill(body=html, content_type="text/html; charset=utf-8")

    async with BrowserListingFetcher(fast_limiter) as fetcher:
        await fetcher._context.route("**/*", handler)
        result = await fetcher.fetch_page("elektriciens", "antwerpen", 1)

    assert isinstance(result, ListingPage)
    assert result.cards_found == 12
    assert result.is_last_page is False


@pytest.mark.asyncio
async def test_fetch_page_no_results_is_last_page(fast_limiter, monkeypatch) -> None:
    html = _html("listing_no_results.html")
    monkeypatch.setattr(asyncio, "sleep", _noop_sleep)

    async def handler(route, _request):  # type: ignore[no-untyped-def]
        await route.fulfill(body=html, content_type="text/html; charset=utf-8")

    async with BrowserListingFetcher(fast_limiter) as fetcher:
        await fetcher._context.route("**/*", handler)
        result = await fetcher.fetch_page("elektriciens", "mol", 1)

    assert result.is_last_page is True
    assert result.cards_found == 0


@pytest.mark.asyncio
async def test_fetch_page_fr_uses_pagesdor_url(fast_limiter, monkeypatch) -> None:
    html = _html("listing_french_liege_plombiers.html")
    monkeypatch.setattr(asyncio, "sleep", _noop_sleep)

    async def handler(route, _request):  # type: ignore[no-untyped-def]
        await route.fulfill(body=html, content_type="text/html; charset=utf-8")

    async with BrowserListingFetcher(fast_limiter, domain="pagesdor.be") as fetcher:
        await fetcher._context.route("**/*", handler)
        result = await fetcher.fetch_page("electriciens", "liege", 1, lang="fr")

    assert result.cards_found == 4


@pytest.mark.asyncio
async def test_city_slug_spaces_replaced_with_hyphens(fast_limiter, monkeypatch) -> None:
    html = _html("listing_no_results.html")
    monkeypatch.setattr(asyncio, "sleep", _noop_sleep)
    captured_urls: list[str] = []

    async def handler(route, request):  # type: ignore[no-untyped-def]
        captured_urls.append(request.url)
        await route.fulfill(body=html, content_type="text/html; charset=utf-8")

    async with BrowserListingFetcher(fast_limiter) as fetcher:
        await fetcher._context.route("**/*", handler)
        result = await fetcher.fetch_page("elektriciens", "Sint Niklaas", 1)

    assert result.is_last_page is True
    assert any("sint-niklaas" in u for u in captured_urls)


@pytest.mark.asyncio
async def test_blocked_response_raises_blocked_error(fast_limiter, monkeypatch) -> None:
    blocked_html = "<html><body>Pardon Our Interruption — Imperva</body></html>"
    monkeypatch.setattr(asyncio, "sleep", _noop_sleep)

    async def handler(route, _request):  # type: ignore[no-untyped-def]
        await route.fulfill(body=blocked_html, content_type="text/html; charset=utf-8")

    async with BrowserListingFetcher(fast_limiter) as fetcher:
        await fetcher._context.route("**/*", handler)
        with pytest.raises(BlockedError):
            await fetcher.fetch_page("elektriciens", "antwerpen", 1)
