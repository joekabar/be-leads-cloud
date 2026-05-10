"""Async retry wrapper with exponential backoff, jitter, and Retry-After support."""

from __future__ import annotations

import asyncio
import email.utils
import random
import time
from typing import Any

import httpx

from scraper.lib.errors import (
    BlockedError,
    RateLimitedError,
    RetriesExhaustedError,
    TerminalServerError,
    TransientServerError,
)

_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


def _parse_retry_after(value: str) -> float:
    """Parse Retry-After header — integer seconds or HTTP-date — into float seconds."""
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        dt = email.utils.parsedate_to_datetime(value)
        return max(0.0, dt.timestamp() - time.time())
    except Exception:
        return 0.0


async def request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    max_attempts: int = 5,
    base_delay: float = 1.0,
    jitter: float = 0.3,
    **kwargs: Any,
) -> httpx.Response:
    last_exc: BaseException | None = None

    for attempt in range(max_attempts):
        try:
            response = await client.request(method, url, **kwargs)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            last_exc = exc
            delay = min(60.0, base_delay * (2**attempt)) + random.uniform(0, jitter)  # noqa: S311
            await asyncio.sleep(delay)
            continue

        status = response.status_code
        url_str = str(response.url)

        if status == 403:
            raise BlockedError(status, url_str, "blocked (WAF/403) — not retrying")

        if status < 400:
            return response

        if status not in _RETRYABLE_STATUSES:
            raise TerminalServerError(status, url_str, f"terminal HTTP {status}")

        retry_after = response.headers.get("Retry-After")
        if retry_after is not None:
            delay = _parse_retry_after(retry_after)
        else:
            delay = min(60.0, base_delay * (2**attempt)) + random.uniform(0, jitter)  # noqa: S311

        if status == 429:
            last_exc = RateLimitedError(status, url_str, f"rate limited (HTTP {status})")
        else:
            last_exc = TransientServerError(status, url_str, f"transient server error {status}")

        await asyncio.sleep(delay)

    raise RetriesExhaustedError(f"Exhausted {max_attempts} attempts for {url}") from last_exc
