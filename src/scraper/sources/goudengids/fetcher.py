"""Playwright-based listing-page fetcher for goudengids.be / pagesdor.be.

Uses a single Chromium browser context for the entire scrape session so Imperva
session cookies are preserved across all page navigations. The old two-phase
warmup+httpx approach is archived in archive/fetcher_httpx.py.
"""

from __future__ import annotations

import asyncio
import contextlib
import random
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import structlog
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

from scraper.lib.errors import BlockedError
from scraper.sources.goudengids.parser import is_empty_results_page, parse_listing_page

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Playwright

    from scraper.lib.http.limiter import HostLimiter

logger = structlog.get_logger()

_LISTING_SELECTOR = "li[data-small-result]"
_BLOCKED_PHRASES = ("pardon our interruption", "imperva")


@dataclass(frozen=True, slots=True)
class ListingPage:
    url: str
    html: str
    cards_found: int
    is_last_page: bool


def _build_url(domain: str, sector_slug: str, city_slug: str, page: int, lang: str) -> str:
    city = city_slug.lower().strip().replace(" ", "-")
    sector = sector_slug.lower()
    if lang == "fr":
        return f"https://www.{domain}/recherche/{sector}/{city}/{page}/"
    return f"https://www.{domain}/zoeken/{sector}/{city}/{page}/"


def is_blocked(html: str) -> bool:
    lower = html.lower()
    return any(phrase in lower for phrase in _BLOCKED_PHRASES)


class BrowserListingFetcher:
    """Single Playwright Chromium session for goudengids listing pages.

    Use as an async context manager — opens the browser on enter, closes on exit:

        async with BrowserListingFetcher(limiter) as fetcher:
            html = await fetcher.fetch_listing(url)
    """

    def __init__(self, limiter: HostLimiter, domain: str = "goudengids.be") -> None:
        self._limiter = limiter
        self._domain = domain
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._warmed_up: bool = False

    async def __aenter__(self) -> BrowserListingFetcher:
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        # Read the UA the installed Chromium binary sends — avoids hardcoding a version.
        _temp = await self._browser.new_context()
        _temp_page = await _temp.new_page()
        user_agent: str = await _temp_page.evaluate("navigator.userAgent")
        await _temp.close()

        # Strip "Headless" so Imperva sees a normal Chrome UA, not "HeadlessChrome/X.Y"
        user_agent = user_agent.replace("HeadlessChrome/", "Chrome/")
        self._context = await self._browser.new_context(
            user_agent=user_agent,
            locale="nl-BE",
            viewport={"width": 1280, "height": 720},
        )
        await self._context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        logger.debug("goudengids_browser_started", domain=self._domain, user_agent=user_agent)
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._browser is not None:
            await self._browser.close()
        if self._pw is not None:
            await self._pw.stop()
        self._browser = None
        self._pw = None
        self._context = None

    async def _warmup(self) -> None:
        """Navigate to the domain homepage once to establish Imperva session cookies."""
        if self._context is None:
            raise RuntimeError("BrowserListingFetcher must be used as an async context manager")
        page = await self._context.new_page()
        try:
            await page.goto(
                f"https://www.{self._domain}/",
                wait_until="load",
                timeout=30_000,
            )
        except PlaywrightTimeoutError:
            logger.warning("goudengids_warmup_timeout", domain=self._domain)
        finally:
            await page.close()
        await asyncio.sleep(3.0)
        self._warmed_up = True
        logger.debug("goudengids_warmup_done", domain=self._domain)

    async def fetch_listing(self, url: str) -> str:
        """Navigate to url and return the page HTML.

        Raises BlockedError immediately on Imperva detection — do not retry.
        """
        if self._context is None:
            raise RuntimeError("BrowserListingFetcher must be used as an async context manager")

        if not self._warmed_up:
            await self._warmup()

        await self._limiter.acquire(self._domain)
        await asyncio.sleep(random.uniform(1.5, 3.0))  # noqa: S311

        page = await self._context.new_page()
        try:
            await page.goto(url, wait_until="load", timeout=30_000)
            with contextlib.suppress(PlaywrightTimeoutError):
                await page.wait_for_selector(_LISTING_SELECTOR, timeout=20_000)
            html: str = await page.content()
        finally:
            await page.close()

        if is_blocked(html):
            logger.error("goudengids_imperva_block", url=url)
            raise BlockedError(403, url, "Imperva block detected in page HTML")

        return html

    async def fetch_page(
        self,
        sector_slug: str,
        city_slug: str,
        page: int,
        *,
        lang: Literal["nl", "fr"] = "nl",
    ) -> ListingPage:
        """Fetch and parse one listing page."""
        url = _build_url(self._domain, sector_slug, city_slug, page, lang)
        html = await self.fetch_listing(url)
        cards = parse_listing_page(html, domain=self._domain)
        is_last = is_empty_results_page(html) or len(cards) == 0
        return ListingPage(url=url, html=html, cards_found=len(cards), is_last_page=is_last)
