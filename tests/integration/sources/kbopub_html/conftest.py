from __future__ import annotations

import re
from pathlib import Path

import httpx
import pytest

from scraper.lib.http.limiter import HostConfig, HostLimiter

_GOLDEN = Path("tests/golden/kbopub_html")

# KBO → fixture filename for mock dispatch.
# Fixture filenames use the spec-given identifiers but the ingester receives valid KBO
# numbers (mod-97 checksum).  Mapping here decouples the two.
# Valid equivalents: 0234567873 (not 0234567890), 0345678997 (not 0345678901),
#                   0456789034 (not 0456789012).
_KBO_FIXTURES: dict[str, str] = {
    "0439401387": "0439401387_bellock_nl.html",
    "0123456749": "0123456749_no_holders.html",
    "0234567873": "0234567890_multiple_roles.html",
    "0345678997": "0345678901_french.html",
    "0456789034": "0456789012_legal_person_holder.html",
}

_KBO_RE = re.compile(r"ondernemingsnummer=(\d+)")


def make_fast_limiter() -> HostLimiter:
    """High-rps limiter so integration tests don't spend seconds waiting."""
    fast = HostConfig(rps=1000.0, concurrency=10, timeout_s=5.0, user_agent_pool_id="api-client")
    return HostLimiter(configs={}, default=fast)


def kbopub_side_effect(request: httpx.Request) -> httpx.Response:
    """Dispatch mock kbopub responses based on the ondernemingsnummer query param."""
    m = _KBO_RE.search(str(request.url))
    if not m:
        return httpx.Response(404)
    kbo = m.group(1)
    filename = _KBO_FIXTURES.get(kbo)
    if filename:
        html = (_GOLDEN / filename).read_text(encoding="utf-8")
        return httpx.Response(200, text=html)
    return httpx.Response(404)


@pytest.fixture()
def fast_limiter() -> HostLimiter:
    return make_fast_limiter()
