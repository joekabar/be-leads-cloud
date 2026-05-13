"""Integration tests for BraveClient — HTTP mocked with respx."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from scraper.lib.http.client import get_polite_client
from scraper.sources.ddg_brave.brave_client import (
    BraveAuthError,
    BraveClient,
    BraveQuotaExhaustedError,
    BraveRateLimitedError,
)

from .conftest import make_fast_limiter

_GOLDEN = Path("tests/golden/ddg_brave")
_BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"
_KEY = "test-subscription-key"


@pytest.fixture()
async def brave_client():  # type: ignore[return]
    limiter = make_fast_limiter()
    async with get_polite_client(limiter) as pc:
        yield BraveClient(pc, _KEY)


@pytest.mark.asyncio
async def test_200_returns_parsed_dict(brave_client: BraveClient) -> None:
    payload = json.loads((_GOLDEN / "brave_bellock_antwerpen.json").read_text())
    with respx.mock:
        respx.get(_BRAVE_URL).mock(return_value=httpx.Response(200, json=payload))
        result = await brave_client.search("Bellock Antwerpen")
    assert "web" in result
    assert len(result["web"]["results"]) == 8


@pytest.mark.asyncio
async def test_401_raises_brave_auth_error(brave_client: BraveClient) -> None:
    with respx.mock:
        respx.get(_BRAVE_URL).mock(return_value=httpx.Response(401, json={"error": "Unauthorized"}))
        with pytest.raises(BraveAuthError):
            await brave_client.search("test query")


@pytest.mark.asyncio
async def test_403_raises_brave_quota_exhausted(brave_client: BraveClient) -> None:
    with respx.mock:
        respx.get(_BRAVE_URL).mock(
            return_value=httpx.Response(403, json={"error": "Quota exceeded"})
        )
        with pytest.raises(BraveQuotaExhaustedError):
            await brave_client.search("test query")


@pytest.mark.asyncio
async def test_429_raises_brave_rate_limited(brave_client: BraveClient) -> None:
    with respx.mock:
        # Always return 429 so all retries are exhausted → BraveRateLimitedError
        respx.get(_BRAVE_URL).mock(return_value=httpx.Response(429, headers={"Retry-After": "0"}))
        with pytest.raises(BraveRateLimitedError):
            await brave_client.search("test query")


@pytest.mark.asyncio
async def test_request_includes_subscription_token(brave_client: BraveClient) -> None:
    payload = json.loads((_GOLDEN / "brave_bellock_antwerpen.json").read_text())
    with respx.mock:
        route = respx.get(_BRAVE_URL).mock(return_value=httpx.Response(200, json=payload))
        await brave_client.search("Bellock Antwerpen")
    assert route.called
    req = route.calls.last.request
    assert req.headers["x-subscription-token"] == _KEY
    assert req.headers["accept"] == "application/json"


@pytest.mark.asyncio
async def test_request_url_contains_expected_params(brave_client: BraveClient) -> None:
    payload = json.loads((_GOLDEN / "brave_bellock_antwerpen.json").read_text())
    with respx.mock:
        route = respx.get(_BRAVE_URL).mock(return_value=httpx.Response(200, json=payload))
        await brave_client.search("Bellock Antwerpen", count=10)
    req = route.calls.last.request
    url_str = str(req.url)
    assert "q=Bellock" in url_str or "q=" in url_str
    assert "country=BE" in url_str
    assert "count=10" in url_str
