from __future__ import annotations

import httpx
import pytest
import respx

from scraper.lib.http.client import get_polite_client
from scraper.lib.http.limiter import HostConfig, HostLimiter

_URL = "https://example.com/path"


def _fast_limiter() -> HostLimiter:
    """High-rps limiter so tests don't actually wait."""
    default = HostConfig(
        rps=1000.0, concurrency=10, timeout_s=10.0, user_agent_pool_id="browser-mix"
    )
    return HostLimiter(configs={}, default=default)


@pytest.mark.asyncio
async def test_get_returns_response() -> None:
    limiter = _fast_limiter()
    with respx.mock:
        respx.get(_URL).mock(return_value=httpx.Response(200, text="hello"))
        async with get_polite_client(limiter) as pc:
            resp = await pc.get(_URL)
    assert resp.status_code == 200
    assert resp.text == "hello"


@pytest.mark.asyncio
async def test_user_agent_header_set() -> None:
    limiter = _fast_limiter()
    with respx.mock:
        route = respx.get(_URL).mock(return_value=httpx.Response(200))
        async with get_polite_client(limiter) as pc:
            await pc.get(_URL)
        request = route.calls.last.request
    assert "User-Agent" in request.headers
    ua = request.headers["User-Agent"]
    assert len(ua) > 10


@pytest.mark.asyncio
async def test_accept_language_header_set() -> None:
    limiter = _fast_limiter()
    with respx.mock:
        route = respx.get(_URL).mock(return_value=httpx.Response(200))
        async with get_polite_client(limiter) as pc:
            await pc.get(_URL)
        request = route.calls.last.request
    assert request.headers.get("Accept-Language", "").startswith("nl-BE")


@pytest.mark.asyncio
async def test_polite_client_post() -> None:
    limiter = _fast_limiter()
    with respx.mock:
        respx.post(_URL).mock(return_value=httpx.Response(201, text="created"))
        async with get_polite_client(limiter) as pc:
            resp = await pc.post(_URL, content=b"body")
    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_chrome_only_ua_for_goudengids() -> None:
    """goudengids.be config uses chrome-only pool — UA must be a Chrome string."""
    named = HostConfig(rps=1000.0, concurrency=2, timeout_s=10.0, user_agent_pool_id="chrome-only")
    limiter = HostLimiter(configs={"goudengids.be": named}, default=named)
    url = "https://goudengids.be/nl/"

    with respx.mock:
        route = respx.get(url).mock(return_value=httpx.Response(200))
        async with get_polite_client(limiter) as pc:
            await pc.get(url)
        request = route.calls.last.request

    assert "Chrome" in request.headers["User-Agent"]
