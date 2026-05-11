"""httpx-based listing-page fetcher for goudengids.be / pagesdor.be.

Wraps PoliteClient with Imperva cookie management. On 403 (WAF block), attempts
exactly one cookie re-warm then retries. A second consecutive 403 raises BlockedError.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import structlog

from scraper.lib.errors import BlockedError
from scraper.sources.goudengids.parser import is_empty_results_page, parse_listing_page
from scraper.sources.goudengids.warmup import WarmupResult, is_expired, warmup_cookies

if TYPE_CHECKING:
    from scraper.lib.http.client import PoliteClient

logger = structlog.get_logger()


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


class GoudengidsFetcher:
    """httpx session pre-loaded with warmup cookies. Auto-refreshes cookies on 403."""

    def __init__(self, polite_client: PoliteClient, domain: str = "goudengids.be") -> None:
        self._client = polite_client
        self._domain = domain
        self._warmup_result: WarmupResult | None = None

    async def warm(self) -> None:
        """Initial cookie warmup. Must be called before fetch_page, or called automatically."""
        result = await warmup_cookies(self._domain)
        self._warmup_result = result
        logger.bind(domain=self._domain).info(
            "goudengids_warmup_complete",
            cookie_count=len(result.cookies),
        )

    async def fetch_page(
        self,
        sector_slug: str,
        city_slug: str,
        page: int,
        *,
        lang: Literal["nl", "fr"] = "nl",
    ) -> ListingPage:
        """Fetch one listing page. Auto-refreshes cookies if expired or on first 403.

        Raises BlockedError on second consecutive 403 (WAF is actively blocking).
        """
        if self._warmup_result is None or is_expired(self._warmup_result):
            await self.warm()

        warmup = self._warmup_result
        if warmup is None:
            raise BlockedError(0, "", "warm() did not produce a WarmupResult")

        url = _build_url(self._domain, sector_slug, city_slug, page, lang)

        def _cookie_header(c: dict[str, str]) -> dict[str, str]:
            return {"Cookie": "; ".join(f"{k}={v}" for k, v in c.items())} if c else {}

        try:
            response = await self._client.get(url, headers=_cookie_header(warmup.cookies))
        except BlockedError:
            logger.warning("goudengids_403_rewarm", url=url)
            await self.warm()
            warmup = self._warmup_result
            if warmup is None:
                raise BlockedError(403, url, "re-warm did not produce cookies") from None
            # Second BlockedError propagates to the caller.
            response = await self._client.get(url, headers=_cookie_header(warmup.cookies))

        html = response.text
        cards = parse_listing_page(html, domain=self._domain)
        is_last = is_empty_results_page(html) or len(cards) == 0
        return ListingPage(url=url, html=html, cards_found=len(cards), is_last_page=is_last)
