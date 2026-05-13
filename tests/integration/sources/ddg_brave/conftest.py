"""Shared fixtures for ddg_brave integration tests."""

from __future__ import annotations

from scraper.lib.http.limiter import HostConfig, HostLimiter


def make_fast_limiter() -> HostLimiter:
    fast = HostConfig(rps=1000.0, concurrency=10, timeout_s=5.0, user_agent_pool_id="api-client")
    return HostLimiter(configs={}, default=fast)
