"""Shared fixtures for goudengids integration tests."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import pytest

from scraper.lib.http.limiter import HostConfig, HostLimiter
from scraper.sources.goudengids.fetcher import ListingPage, _build_url
from scraper.sources.goudengids.parser import is_empty_results_page, parse_listing_page

_GOLDEN = Path("tests/golden/goudengids")


def _page_html(name: str) -> str:
    return (_GOLDEN / name).read_text(encoding="utf-8")


def make_fast_limiter() -> HostLimiter:
    fast = HostConfig(rps=1000.0, concurrency=10, timeout_s=5.0, user_agent_pool_id="chrome-only")
    return HostLimiter(configs={}, default=fast)


@pytest.fixture()
def fast_limiter() -> HostLimiter:
    return make_fast_limiter()


class StubBrowserFetcher:
    """Stub BrowserListingFetcher for ingester/CLI tests — no real browser launched."""

    _domain = "goudengids.be"

    def __init__(self, page_responses: dict[tuple[str, str, int], str] | None = None) -> None:
        self._pages: dict[tuple[str, str, int], str] = page_responses or {}

    async def __aenter__(self) -> StubBrowserFetcher:
        return self

    async def __aexit__(self, *_: object) -> None:
        pass

    async def fetch_page(
        self,
        sector_slug: str,
        city_slug: str,
        page: int,
        *,
        lang: Literal["nl", "fr"] = "nl",
    ) -> ListingPage:
        html = self._pages.get(
            (sector_slug, city_slug, page), _page_html("listing_no_results.html")
        )
        cards = parse_listing_page(html, domain=self._domain)
        is_last = is_empty_results_page(html) or len(cards) == 0
        return ListingPage(
            url=_build_url(self._domain, sector_slug, city_slug, page, lang),
            html=html,
            cards_found=len(cards),
            is_last_page=is_last,
        )
