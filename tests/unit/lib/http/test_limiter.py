import asyncio
import time
from pathlib import Path

import pytest

from scraper.lib.http.limiter import HostConfig, HostLimiter, load_from_toml


def _make_limiter(rps: float = 2.0, concurrency: int = 2) -> HostLimiter:
    default = HostConfig(
        rps=rps, concurrency=concurrency, timeout_s=10.0, user_agent_pool_id="browser-mix"
    )
    return HostLimiter(configs={}, default=default)


@pytest.mark.asyncio
async def test_rps_capping() -> None:
    """Token bucket spaces 5 acquires by 1/rps each — total ≥ 4*(1/rps) seconds."""
    default = HostConfig(rps=4.0, concurrency=5, timeout_s=10.0, user_agent_pool_id="browser-mix")
    limiter = HostLimiter(configs={}, default=default)
    start = time.monotonic()
    for _ in range(5):
        await limiter.acquire("example.com")
    elapsed = time.monotonic() - start
    # 4 gaps of 0.25 s each; generous tolerance for slow CI
    assert elapsed >= 0.9


@pytest.mark.asyncio
async def test_concurrency_cap() -> None:
    """At most `concurrency` coroutines should run simultaneously."""
    default = HostConfig(rps=100.0, concurrency=2, timeout_s=10.0, user_agent_pool_id="browser-mix")
    limiter = HostLimiter(configs={}, default=default)
    running: list[int] = []
    peak: list[int] = []

    async def task() -> None:
        async with limiter.slot("example.com"):
            running.append(1)
            peak.append(len(running))
            await asyncio.sleep(0.05)
            running.pop()

    async with asyncio.TaskGroup() as tg:
        for _ in range(6):
            tg.create_task(task())

    assert max(peak) <= 2


@pytest.mark.asyncio
async def test_default_fallback() -> None:
    """Unknown host should use the default config."""
    limiter = _make_limiter(rps=100.0, concurrency=2)
    cfg = limiter.config_for("unknown-host.example")
    assert cfg.rps == 100.0
    assert cfg.concurrency == 2


@pytest.mark.asyncio
async def test_named_host_config() -> None:
    """Named host overrides the default."""
    named = HostConfig(rps=0.3, concurrency=1, timeout_s=15.0, user_agent_pool_id="chrome-only")
    default = HostConfig(rps=0.5, concurrency=2, timeout_s=12.0, user_agent_pool_id="browser-mix")
    limiter = HostLimiter(configs={"goudengids.be": named}, default=default)
    cfg = limiter.config_for("goudengids.be")
    assert cfg.rps == 0.3
    assert cfg.user_agent_pool_id == "chrome-only"


def test_load_from_toml(tmp_path: Path) -> None:
    """load_from_toml should parse a TOML file into a HostLimiter."""
    toml_content = """
[default]
rps = 0.5
concurrency = 2
timeout_s = 12.0
user_agent_pool_id = "browser-mix"

["example.com"]
rps = 1.0
concurrency = 3
timeout_s = 8.0
user_agent_pool_id = "api-client"
"""
    p = tmp_path / "hosts.toml"
    p.write_text(toml_content)
    limiter = load_from_toml(p)

    default_cfg = limiter.config_for("other.com")
    assert default_cfg.rps == 0.5
    assert default_cfg.concurrency == 2

    named_cfg = limiter.config_for("example.com")
    assert named_cfg.rps == 1.0
    assert named_cfg.concurrency == 3
