from __future__ import annotations

import re
from typing import TYPE_CHECKING

import httpx
import pytest
import respx

from scraper.lib.errors import NbbAuthError, NbbNotFoundError

if TYPE_CHECKING:
    from scraper.sources.nbb_authentic.client import NbbClient

pytestmark = pytest.mark.integration

_REFS_URL = "https://ws.cbso.nbb.be/authentic/legalEntity/0439401387/references"
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


@pytest.mark.asyncio
async def test_subscription_key_header_sent(nbb_client: NbbClient) -> None:
    with respx.mock:
        route = respx.get(_REFS_URL).mock(return_value=httpx.Response(200, json={"references": []}))
        await nbb_client.get_references("0439401387")

    assert route.called
    req = route.calls.last.request
    assert req.headers["NBB-CBSO-Subscription-Key"] == "test-key-12345"


@pytest.mark.asyncio
async def test_x_request_id_is_uuid4(nbb_client: NbbClient) -> None:
    with respx.mock:
        route = respx.get(_REFS_URL).mock(return_value=httpx.Response(200, json={"references": []}))
        await nbb_client.get_references("0439401387")

    req = route.calls.last.request
    assert _UUID_RE.match(req.headers["X-Request-Id"]) is not None


@pytest.mark.asyncio
async def test_x_request_id_unique_per_call(nbb_client: NbbClient) -> None:
    with respx.mock:
        route = respx.get(_REFS_URL).mock(return_value=httpx.Response(200, json={"references": []}))
        await nbb_client.get_references("0439401387")
        await nbb_client.get_references("0439401387")

    ids = [call.request.headers["X-Request-Id"] for call in route.calls]
    assert ids[0] != ids[1]


@pytest.mark.asyncio
async def test_401_raises_nbb_auth_error(nbb_client: NbbClient) -> None:
    with respx.mock:
        respx.get(_REFS_URL).mock(return_value=httpx.Response(401))
        with pytest.raises(NbbAuthError):
            await nbb_client.get_references("0439401387")


@pytest.mark.asyncio
async def test_404_raises_nbb_not_found(nbb_client: NbbClient) -> None:
    with respx.mock:
        respx.get(_REFS_URL).mock(return_value=httpx.Response(404))
        with pytest.raises(NbbNotFoundError):
            await nbb_client.get_references("0439401387")


@pytest.mark.asyncio
async def test_429_retries_and_eventually_succeeds(nbb_client: NbbClient) -> None:
    responses = [
        httpx.Response(429, headers={"Retry-After": "0"}),
        httpx.Response(200, json={"references": []}),
    ]
    with respx.mock:
        respx.get(_REFS_URL).mock(side_effect=responses)
        refs = await nbb_client.get_references("0439401387")
    assert refs == []


@pytest.mark.asyncio
async def test_empty_references_returns_empty_list(nbb_client: NbbClient) -> None:
    with respx.mock:
        respx.get(_REFS_URL).mock(return_value=httpx.Response(200, json={"references": []}))
        refs = await nbb_client.get_references("0439401387")
    assert refs == []


# ---------------------------------------------------------------------------
# get_accounting_data error mapping
# ---------------------------------------------------------------------------

_ACCOUNTING_URL = (
    "https://ws.cbso.nbb.be/authentic/legalEntity/0439401387"
    "/references/2024-00000148/accountingData"
)


@pytest.mark.asyncio
async def test_accounting_data_401_raises_nbb_auth_error(nbb_client: NbbClient) -> None:
    with respx.mock:
        respx.get(_ACCOUNTING_URL).mock(return_value=httpx.Response(401))
        with pytest.raises(NbbAuthError):
            await nbb_client.get_accounting_data("0439401387", "2024-00000148")


@pytest.mark.asyncio
async def test_accounting_data_404_raises_nbb_not_found(nbb_client: NbbClient) -> None:
    with respx.mock:
        respx.get(_ACCOUNTING_URL).mock(return_value=httpx.Response(404))
        with pytest.raises(NbbNotFoundError):
            await nbb_client.get_accounting_data("0439401387", "2024-00000148")
