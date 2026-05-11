from __future__ import annotations

import json
import re
from collections.abc import AsyncGenerator
from pathlib import Path

import httpx
import pytest

from scraper.lib.http.client import get_polite_client
from scraper.lib.http.limiter import HostConfig, HostLimiter
from scraper.sources.nbb_authentic.client import NbbClient

_GOLDEN = Path("tests/golden/nbb_authentic")

_REFERENCES_FIXTURES: dict[str, str] = {
    "0439401387": "0439401387_references.json",
    "0502699332": "0502699332_references_single.json",
}

_ACCOUNTING_FIXTURES: dict[str, dict[str, str]] = {
    "0439401387": {
        "2024-00000148": "0439401387_accounting_2024-00000148.json",
        "2023-00000119": "0439401387_accounting_2023-00000119.json",
        "2022-00000091": "0439401387_accounting_2022-00000091.json",
    },
    "0502699332": {
        "2024-00012345": "0502699332_accounting_2024-00012345.json",
    },
}

_NBB_URL_RE = re.compile(r"/authentic/legalEntity/(\d+)/references(?:/([^/]+)/accountingData)?")


def make_fast_limiter() -> HostLimiter:
    fast = HostConfig(rps=1000.0, concurrency=10, timeout_s=5.0, user_agent_pool_id="api-client")
    return HostLimiter(configs={}, default=fast)


def nbb_side_effect(request: httpx.Request) -> httpx.Response:
    """Dispatch mock NBB CBSO responses based on URL path."""
    m = _NBB_URL_RE.search(str(request.url))
    if not m:
        return httpx.Response(404)

    kbo = m.group(1)
    ref_num = m.group(2)

    if ref_num is None:
        filename = _REFERENCES_FIXTURES.get(kbo)
        if filename:
            data = json.loads((_GOLDEN / filename).read_text())
            return httpx.Response(200, json=data)
        return httpx.Response(200, json={"references": []})
    else:
        filename = _ACCOUNTING_FIXTURES.get(kbo, {}).get(ref_num)
        if filename:
            data = json.loads((_GOLDEN / filename).read_text())
            return httpx.Response(200, json=data)
        return httpx.Response(404)


@pytest.fixture()
def fast_limiter() -> HostLimiter:
    return make_fast_limiter()


@pytest.fixture()
async def nbb_client(fast_limiter: HostLimiter) -> AsyncGenerator[NbbClient, None]:
    async with get_polite_client(fast_limiter) as polite_client:
        yield NbbClient(polite_client=polite_client, subscription_key="test-key-12345")
