"""Async per-host token-bucket rate limiter with concurrency cap."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import tomllib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path


@dataclass(frozen=True, slots=True)
class HostConfig:
    rps: float
    concurrency: int
    timeout_s: float
    user_agent_pool_id: str


class HostLimiter:
    def __init__(self, configs: dict[str, HostConfig], default: HostConfig) -> None:
        self._configs = configs
        self._default = default
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        self._next_allowed: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def config_for(self, host: str) -> HostConfig:
        return self._configs.get(host, self._default)

    def _get_semaphore(self, host: str) -> asyncio.Semaphore:
        if host not in self._semaphores:
            self._semaphores[host] = asyncio.Semaphore(self.config_for(host).concurrency)
        return self._semaphores[host]

    def _get_lock(self, host: str) -> asyncio.Lock:
        if host not in self._locks:
            self._locks[host] = asyncio.Lock()
        return self._locks[host]

    async def acquire(self, host: str) -> None:
        """Wait until a token-bucket slot is available for *host*."""
        cfg = self.config_for(host)
        lock = self._get_lock(host)
        async with lock:
            now = asyncio.get_running_loop().time()
            next_time = self._next_allowed.get(host, now)
            if next_time > now:
                await asyncio.sleep(next_time - now)
                now = next_time
            self._next_allowed[host] = now + (1.0 / cfg.rps)

    @contextlib.asynccontextmanager
    async def slot(self, host: str) -> AsyncIterator[None]:
        """Async context manager that caps concurrent requests per host."""
        sem = self._get_semaphore(host)
        async with sem:
            yield


def load_from_toml(path: Path) -> HostLimiter:
    """Build a HostLimiter from a per-host TOML config file."""
    with path.open("rb") as fh:
        data: dict[str, Any] = tomllib.load(fh)

    raw_default = data.pop("default", {})
    default = HostConfig(
        rps=float(raw_default.get("rps", 0.5)),
        concurrency=int(raw_default.get("concurrency", 2)),
        timeout_s=float(raw_default.get("timeout_s", 12.0)),
        user_agent_pool_id=str(raw_default.get("user_agent_pool_id", "browser-mix")),
    )

    configs: dict[str, HostConfig] = {}
    for host, raw in data.items():
        if isinstance(raw, dict):
            configs[host] = HostConfig(
                rps=float(raw.get("rps", default.rps)),
                concurrency=int(raw.get("concurrency", default.concurrency)),
                timeout_s=float(raw.get("timeout_s", default.timeout_s)),
                user_agent_pool_id=str(raw.get("user_agent_pool_id", default.user_agent_pool_id)),
            )

    return HostLimiter(configs=configs, default=default)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="HostLimiter — async token-bucket rate limiter for polite scraping."
    )
    parser.parse_args()
