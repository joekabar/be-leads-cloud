"""Async Brave Search API client."""

from __future__ import annotations

import urllib.parse
from typing import TYPE_CHECKING, Any, Literal

import structlog

from scraper.lib.errors import (
    BlockedError,
    RetriesExhaustedError,
    ScraperError,
    TerminalServerError,
)

if TYPE_CHECKING:
    from scraper.lib.http.client import PoliteClient

logger = structlog.get_logger()

_BASE_URL = "https://api.search.brave.com/res/v1/web/search"


class BraveAuthError(ScraperError):
    """HTTP 401 — subscription key is invalid or missing."""


class BraveQuotaExhaustedError(ScraperError):
    """HTTP 403 — monthly free-tier quota exhausted."""


class BraveRateLimitedError(ScraperError):
    """HTTP 429 — QPS limit hit; caller decides whether to retry."""


class BraveClient:
    def __init__(
        self,
        polite_client: PoliteClient,
        subscription_key: str,
        *,
        country: str = "BE",
    ) -> None:
        self._polite_client = polite_client
        self._subscription_key = subscription_key
        self._country = country

    async def search(
        self,
        query: str,
        *,
        count: int = 10,
        search_lang: Literal["nl", "fr", "en"] = "nl",
    ) -> dict[str, Any]:
        """Execute a web search and return the raw Brave JSON payload.

        Raises:
            BraveAuthError: on HTTP 401.
            BraveQuotaExhausted: on HTTP 403 (monthly quota).
            BraveRateLimited: on HTTP 429 (QPS limit, after retries exhausted).
        """
        params = urllib.parse.urlencode(
            {
                "q": query,
                "count": count,
                "country": self._country,
                "search_lang": search_lang,
            }
        )
        url = f"{_BASE_URL}?{params}"
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": self._subscription_key,
        }

        try:
            response = await self._polite_client.get(url, headers=headers)
        except TerminalServerError as exc:
            if exc.status == 401:
                raise BraveAuthError("Brave subscription key invalid (HTTP 401)") from exc
            raise
        except BlockedError as exc:
            raise BraveQuotaExhaustedError("Brave monthly quota exhausted (HTTP 403)") from exc
        except RetriesExhaustedError as exc:
            raise BraveRateLimitedError("Brave API rate limited after retries (HTTP 429)") from exc

        return dict(response.json())
