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

# Golden PDF used for all mocked PDF fetches — MICRO model, gives revenue + profit_loss (no employees)
_PDF_FIXTURE = _GOLDEN / "0439401387_pdf_2024-00290653.pdf"

_REFS_URL_RE = re.compile(r"/authentic/legalEntity/(\d+)/references$")
_PDF_URL_RE = re.compile(r"/authentic/deposit/([^/]+)/accountingData$")


def make_fast_limiter() -> HostLimiter:
    fast = HostConfig(rps=1000.0, concurrency=10, timeout_s=5.0, user_agent_pool_id="api-client")
    return HostLimiter(configs={}, default=fast)


def _inject_accounting_url(ref: dict) -> dict:  # type: ignore[type-arg]
    """Add accountingDataURL to a legacy camelCase reference dict."""
    ref_num = ref.get("referenceNumber") or ref.get("ReferenceNumber", "")
    url = f"https://ws.cbso.nbb.be/authentic/deposit/{ref_num}/accountingData"
    return {**ref, "accountingDataURL": url}


def nbb_side_effect(request: httpx.Request) -> httpx.Response:
    """Dispatch mock NBB CBSO responses based on URL path."""
    path = request.url.path

    # References list endpoint — inject accountingDataURL into each entry
    m_refs = _REFS_URL_RE.search(path)
    if m_refs:
        kbo = m_refs.group(1)
        filename = _REFERENCES_FIXTURES.get(kbo)
        if filename:
            raw = json.loads((_GOLDEN / filename).read_text())
            if isinstance(raw, dict) and "references" in raw:
                patched = {"references": [_inject_accounting_url(r) for r in raw["references"]]}
            elif isinstance(raw, list):
                patched = [_inject_accounting_url(r) for r in raw]
            else:
                patched = raw
            return httpx.Response(200, json=patched)
        return httpx.Response(200, json={"references": []})

    # PDF accounting data endpoint
    m_pdf = _PDF_URL_RE.search(path)
    if m_pdf:
        if _PDF_FIXTURE.exists():
            return httpx.Response(200, content=_PDF_FIXTURE.read_bytes())
        return httpx.Response(404)

    return httpx.Response(404)


@pytest.fixture()
def fast_limiter() -> HostLimiter:
    return make_fast_limiter()


@pytest.fixture()
async def nbb_client(fast_limiter: HostLimiter) -> AsyncGenerator[NbbClient, None]:
    async with get_polite_client(fast_limiter) as polite_client:
        yield NbbClient(polite_client=polite_client, subscription_key="test-key-12345")
