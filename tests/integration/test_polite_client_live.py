import pytest

from scraper.lib.http.client import get_polite_client
from scraper.lib.http.limiter import HostConfig, HostLimiter


@pytest.mark.network
@pytest.mark.asyncio
async def test_example_com_reachable() -> None:
    """Smoke test: PoliteClient can reach https://example.com/ and gets 200."""
    default = HostConfig(rps=1.0, concurrency=1, timeout_s=15.0, user_agent_pool_id="browser-mix")
    limiter = HostLimiter(configs={}, default=default)
    async with get_polite_client(limiter) as pc:
        resp = await pc.get("https://example.com/")
    assert resp.status_code == 200
