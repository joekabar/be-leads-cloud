"""Shared fixtures for website integration tests."""

from __future__ import annotations

from scraper.lib.http.limiter import HostConfig, HostLimiter


def make_fast_limiter() -> HostLimiter:
    fast = HostConfig(rps=1000.0, concurrency=10, timeout_s=5.0, user_agent_pool_id="chrome-only")
    return HostLimiter(configs={}, default=fast)
