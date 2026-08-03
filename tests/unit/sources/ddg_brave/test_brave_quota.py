"""Brave quota headers are recorded, so "did it hold?" is answerable from the log.

Without this, quota exhaustion only ever surfaces as an HTTP 403 after the fact. Brave
sends "per-second, per-month" pairs, e.g. ``x-ratelimit-policy: 50;w=1, 0;w=2678400``
(50 requests per second; the second window is 2,678,400 s = 31 days).
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from scraper.sources.ddg_brave.brave_client import BraveClient


def _client_with_headers(headers: dict[str, str]) -> BraveClient:
    response = MagicMock()
    response.headers = headers
    response.json.return_value = {"web": {"results": []}}

    polite = MagicMock()
    polite.get = AsyncMock(return_value=response)
    return BraveClient(polite, "test-key")


class TestQuotaRecording:
    def test_remaining_is_captured(self) -> None:
        client = _client_with_headers(
            {
                "x-ratelimit-remaining": "49, 1998",
                "x-ratelimit-limit": "50, 2000",
                "x-ratelimit-policy": "50;w=1, 2000;w=2678400",
            }
        )
        asyncio.run(client.search("q"))
        assert client.last_quota_remaining == "49, 1998"

    def test_latest_value_wins_across_calls(self) -> None:
        client = _client_with_headers({"x-ratelimit-remaining": "49, 1998"})
        asyncio.run(client.search("first"))
        client._polite_client.get.return_value.headers = {"x-ratelimit-remaining": "48, 1997"}
        asyncio.run(client.search("second"))
        assert client.last_quota_remaining == "48, 1997"

    def test_missing_headers_are_tolerated(self) -> None:
        """A response without quota headers must not break the search."""
        client = _client_with_headers({})
        result = asyncio.run(client.search("q"))
        assert client.last_quota_remaining is None
        assert result == {"web": {"results": []}}

    def test_search_result_is_unaffected(self) -> None:
        client = _client_with_headers({"x-ratelimit-remaining": "49, 1998"})
        assert asyncio.run(client.search("q")) == {"web": {"results": []}}
