"""Public async HTTP client with rate limiting and retry baked in."""

from __future__ import annotations

import contextlib
import urllib.parse
from typing import TYPE_CHECKING, Any

import httpx

from scraper.lib.http.retry import request_with_retry

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from scraper.lib.http.limiter import HostLimiter

_UA_POOLS: dict[str, list[str]] = {
    "browser-mix": [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:130.0) Gecko/20100101 Firefox/130.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/18.0 Safari/605.1.15",
    ],
    "chrome-only": [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    ],
    "api-client": ["be-leads/0.1 (+https://example.invalid)"],
    "identifying": ["be-leads/0.1 (contact@example.invalid)"],
}

_COMMON_HEADERS = {
    "Accept-Language": "nl-BE,nl;q=0.9,fr;q=0.5,en;q=0.3",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
}


def _pick_ua(pool_id: str, session_id: int = 0) -> str:
    pool = _UA_POOLS.get(pool_id, _UA_POOLS["browser-mix"])
    return pool[session_id % len(pool)]


class PoliteClient:
    """httpx.AsyncClient wrapper with per-host rate limiting and retry."""

    def __init__(self, inner: httpx.AsyncClient, limiter: HostLimiter) -> None:
        self._inner = inner
        self._limiter = limiter

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        host = urllib.parse.urlparse(url).netloc
        cfg = self._limiter.config_for(host)

        headers: dict[str, str] = dict(_COMMON_HEADERS)
        headers["User-Agent"] = _pick_ua(cfg.user_agent_pool_id)
        if "headers" in kwargs:
            headers.update(kwargs.pop("headers"))
        kwargs["headers"] = headers

        async with self._limiter.slot(host):
            await self._limiter.acquire(host)
            return await request_with_retry(
                self._inner,
                method,
                url,
                timeout=cfg.timeout_s,
                **kwargs,
            )

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self._request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self._request("POST", url, **kwargs)


@contextlib.asynccontextmanager
async def get_polite_client(limiter: HostLimiter) -> AsyncIterator[PoliteClient]:
    """Async context manager that yields a PoliteClient backed by a shared httpx session."""
    async with httpx.AsyncClient(follow_redirects=True) as inner:
        yield PoliteClient(inner=inner, limiter=limiter)
