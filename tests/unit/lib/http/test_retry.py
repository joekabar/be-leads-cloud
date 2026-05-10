from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from scraper.lib.errors import BlockedError, RetriesExhaustedError
from scraper.lib.http.retry import request_with_retry

_URL = "https://example.com/test"


@pytest.mark.asyncio
async def test_200_first_try() -> None:
    with respx.mock:
        respx.get(_URL).mock(return_value=httpx.Response(200, text="ok"))
        async with httpx.AsyncClient() as client:
            resp = await request_with_retry(client, "GET", _URL)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_429_then_200() -> None:
    with respx.mock, patch("asyncio.sleep", new_callable=AsyncMock):
        respx.get(_URL).mock(
            side_effect=[
                httpx.Response(429),
                httpx.Response(200, text="ok"),
            ]
        )
        async with httpx.AsyncClient() as client:
            resp = await request_with_retry(client, "GET", _URL, base_delay=0.0, jitter=0.0)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_503_three_times_then_200() -> None:
    with respx.mock, patch("asyncio.sleep", new_callable=AsyncMock):
        respx.get(_URL).mock(
            side_effect=[
                httpx.Response(503),
                httpx.Response(503),
                httpx.Response(503),
                httpx.Response(200, text="ok"),
            ]
        )
        async with httpx.AsyncClient() as client:
            resp = await request_with_retry(client, "GET", _URL, base_delay=0.0, jitter=0.0)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_403_raises_blocked_immediately() -> None:
    with respx.mock:
        route = respx.get(_URL).mock(return_value=httpx.Response(403))
        async with httpx.AsyncClient() as client:
            with pytest.raises(BlockedError):
                await request_with_retry(client, "GET", _URL)
        # no retry — exactly one request fired
        assert route.call_count == 1


@pytest.mark.asyncio
async def test_retry_after_int_honored() -> None:
    with respx.mock, patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        respx.get(_URL).mock(
            side_effect=[
                httpx.Response(429, headers={"Retry-After": "5"}),
                httpx.Response(200, text="ok"),
            ]
        )
        async with httpx.AsyncClient() as client:
            resp = await request_with_retry(client, "GET", _URL)
    assert resp.status_code == 200
    assert mock_sleep.call_count >= 1
    assert mock_sleep.call_args_list[0].args[0] == pytest.approx(5.0, abs=0.01)


@pytest.mark.asyncio
async def test_retry_after_http_date_honored() -> None:
    """Retry-After as an HTTP-date in the past → delay ≈ 0 (no long wait)."""
    with respx.mock, patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        respx.get(_URL).mock(
            side_effect=[
                httpx.Response(
                    503,
                    headers={"Retry-After": "Thu, 01 Jan 1970 00:00:00 GMT"},
                ),
                httpx.Response(200, text="ok"),
            ]
        )
        async with httpx.AsyncClient() as client:
            resp = await request_with_retry(client, "GET", _URL)
    assert resp.status_code == 200
    # Past date → delay clamped to 0.0
    assert mock_sleep.call_args_list[0].args[0] == pytest.approx(0.0, abs=0.01)


@pytest.mark.asyncio
async def test_retries_exhausted_raises() -> None:
    with respx.mock, patch("asyncio.sleep", new_callable=AsyncMock):
        respx.get(_URL).mock(return_value=httpx.Response(503))
        async with httpx.AsyncClient() as client:
            with pytest.raises(RetriesExhaustedError):
                await request_with_retry(
                    client, "GET", _URL, max_attempts=3, base_delay=0.0, jitter=0.0
                )
