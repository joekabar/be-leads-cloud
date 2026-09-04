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
    """HTTP 402 or 403 — monthly free-tier quota exhausted.

    Brave signals a spent free tier with 402 Payment Required (observed live
    2026-08-21 through 2026-09-04) as well as the documented 403. Both mean the
    same thing operationally: stop asking Brave until the monthly credits reset.
    """


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
        #: Last seen "per-second, per-month" remaining pair, for reporting.
        self.last_quota_remaining: str | None = None
        self._quota_logged = False

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
            BraveQuotaExhausted: on HTTP 402 or 403 (monthly quota).
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
            if exc.status == 402:
                raise BraveQuotaExhaustedError("Brave monthly quota exhausted (HTTP 402)") from exc
            raise
        except BlockedError as exc:
            raise BraveQuotaExhaustedError("Brave monthly quota exhausted (HTTP 403)") from exc
        except RetriesExhaustedError as exc:
            raise BraveRateLimitedError("Brave API rate limited after retries (HTTP 429)") from exc

        self._record_quota(response)
        return dict(response.json())

    def _record_quota(self, response: Any) -> None:
        """Log Brave's rate-limit headers once per client, so runs are self-reporting.

        Brave sends "per-second, per-month" pairs, e.g. ``x-ratelimit-policy:
        50;w=1, 0;w=2678400``. Recording them means "did the quota hold?" is answerable
        from the run log afterwards instead of needing a live probe: without this, quota
        exhaustion would only ever surface as an HTTP 403 after the fact.
        """
        headers = getattr(response, "headers", {}) or {}
        remaining = headers.get("x-ratelimit-remaining")
        if not remaining:
            return
        self.last_quota_remaining = str(remaining)
        if not self._quota_logged:
            self._quota_logged = True
            logger.info(
                "brave_quota",
                remaining=str(remaining),
                limit=str(headers.get("x-ratelimit-limit", "")),
                policy=str(headers.get("x-ratelimit-policy", "")),
            )
