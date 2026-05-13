"""Integration tests for DdgClient — ddgs library monkeypatched."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scraper.sources.ddg_brave.ddg_client import DdgClient, DdgRateLimitedError

_FIXTURE = [
    {
        "title": "Bellock - Elektriciteit Antwerpen",
        "href": "https://www.bellock.be/",
        "body": "...",
    },
    {
        "title": "Bellock op Goudengids",
        "href": "https://www.goudengids.be/bedrijf/...",
        "body": "...",
    },
]


@pytest.mark.asyncio
async def test_search_returns_fixture_results() -> None:
    mock_instance = MagicMock()
    mock_instance.text.return_value = _FIXTURE

    with patch("ddgs.DDGS", return_value=mock_instance):
        client = DdgClient(region="be-nl")
        results = await client.search("Bellock Antwerpen", max_results=10)

    assert results == _FIXTURE
    mock_instance.text.assert_called_once_with(
        "Bellock Antwerpen",
        max_results=10,
        region="be-nl",
        safesearch="moderate",
    )


@pytest.mark.asyncio
async def test_returns_empty_list_when_ddgs_returns_none() -> None:
    mock_instance = MagicMock()
    mock_instance.text.return_value = None

    with patch("ddgs.DDGS", return_value=mock_instance):
        client = DdgClient()
        results = await client.search("query")

    assert results == []


@pytest.mark.asyncio
async def test_ratelimit_retries_once_and_succeeds() -> None:
    from ddgs.exceptions import RatelimitException

    call_count = [0]

    def _text_side_effect(*args, **kwargs):  # type: ignore[no-untyped-def]
        call_count[0] += 1
        if call_count[0] == 1:
            raise RatelimitException("rate limited")
        return _FIXTURE

    mock_instance = MagicMock()
    mock_instance.text.side_effect = _text_side_effect
    sleep_mock = AsyncMock()

    with patch("ddgs.DDGS", return_value=mock_instance), patch("asyncio.sleep", sleep_mock):
        client = DdgClient()
        results = await client.search("Bellock Antwerpen")

    assert results == _FIXTURE
    sleep_mock.assert_awaited_once_with(60)
    assert call_count[0] == 2


@pytest.mark.asyncio
async def test_two_consecutive_ratelimits_raise_ddg_rate_limited_error() -> None:
    from ddgs.exceptions import RatelimitException

    mock_instance = MagicMock()
    mock_instance.text.side_effect = RatelimitException("rate limited")
    sleep_mock = AsyncMock()

    with patch("ddgs.DDGS", return_value=mock_instance), patch("asyncio.sleep", sleep_mock):
        client = DdgClient()
        with pytest.raises(DdgRateLimitedError):
            await client.search("Bellock Antwerpen")

    sleep_mock.assert_awaited_once_with(60)


@pytest.mark.asyncio
async def test_region_passed_to_ddgs() -> None:
    mock_instance = MagicMock()
    mock_instance.text.return_value = []

    with patch("ddgs.DDGS", return_value=mock_instance):
        client = DdgClient(region="be-fr")
        await client.search("Acme Liège")

    call_kwargs = mock_instance.text.call_args.kwargs
    assert call_kwargs["region"] == "be-fr"
