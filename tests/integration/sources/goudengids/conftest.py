"""Shared fixtures for goudengids integration tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from scraper.lib.http.client import get_polite_client
from scraper.lib.http.limiter import HostConfig, HostLimiter
from scraper.sources.goudengids.fetcher import GoudengidsFetcher
from scraper.sources.goudengids.warmup import WarmupResult

_GOLDEN = Path("tests/golden/goudengids")

_FAKE_WARMUP_RESULT = WarmupResult(
    cookies={"incap_ses_test": "test_value", "visid_incap_test": "test_vis"},
    obtained_at=datetime.now(tz=UTC),
    ttl_minutes=25,
)


def make_fast_limiter() -> HostLimiter:
    fast = HostConfig(rps=1000.0, concurrency=10, timeout_s=5.0, user_agent_pool_id="chrome-only")
    return HostLimiter(configs={}, default=fast)


async def _noop_warmup(domain: str = "goudengids.be", *, timeout_s: float = 30.0) -> WarmupResult:
    return _FAKE_WARMUP_RESULT


@pytest.fixture()
def fast_limiter() -> HostLimiter:
    return make_fast_limiter()


@pytest.fixture()
def patch_warmup():  # type: ignore[no-untyped-def]
    """Patch warmup_cookies in both warmup and fetcher modules to skip Playwright."""
    with (
        patch("scraper.sources.goudengids.warmup.warmup_cookies", _noop_warmup),
        patch("scraper.sources.goudengids.fetcher.warmup_cookies", _noop_warmup),
    ):
        yield


@pytest.fixture()
async def goudengids_fetcher(fast_limiter: HostLimiter, patch_warmup):  # type: ignore[no-untyped-def]
    async with get_polite_client(fast_limiter) as polite_client:
        fetcher = GoudengidsFetcher(polite_client, domain="goudengids.be")
        fetcher._warmup_result = _FAKE_WARMUP_RESULT
        yield fetcher
