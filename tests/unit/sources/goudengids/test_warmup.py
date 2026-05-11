"""Unit tests for warmup.py — all playwright calls are mocked."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scraper.sources.goudengids.warmup import (
    WarmupFailedError,
    WarmupResult,
    is_expired,
    warmup_cookies,
)

_IMPERVA_COOKIES = [
    {"name": "incap_ses_1234_5678", "value": "abc123", "domain": ".goudengids.be", "path": "/"},
    {"name": "visid_incap_5678", "value": "def456", "domain": ".goudengids.be", "path": "/"},
    {"name": "nlbi_5678", "value": "xyz789", "domain": ".goudengids.be", "path": "/"},
    {"name": "_ga", "value": "GA1.2.xxx.yyy", "domain": ".goudengids.be", "path": "/"},
    {"name": "_gid", "value": "GA1.2.zzz", "domain": ".goudengids.be", "path": "/"},
]


def _make_playwright_mock(cookies: list[dict] | None = None) -> MagicMock:
    """Build a full mock playwright async context manager stack."""
    if cookies is None:
        cookies = _IMPERVA_COOKIES

    mock_page = AsyncMock()
    mock_page.goto = AsyncMock(return_value=None)
    mock_page.wait_for_selector = AsyncMock(return_value=None)

    mock_context = AsyncMock()
    mock_context.add_init_script = AsyncMock(return_value=None)
    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_context.cookies = AsyncMock(return_value=cookies)
    mock_context.close = AsyncMock(return_value=None)

    mock_browser = AsyncMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    mock_browser.close = AsyncMock(return_value=None)

    mock_chromium = MagicMock()
    mock_chromium.launch = AsyncMock(return_value=mock_browser)

    mock_pw = MagicMock()
    mock_pw.chromium = mock_chromium

    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_pw)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    mock_async_playwright = MagicMock(return_value=mock_cm)
    return mock_async_playwright


@pytest.mark.asyncio
async def test_warmup_returns_result_with_imperva_cookies() -> None:
    mock_apw = _make_playwright_mock()
    with patch("scraper.sources.goudengids.warmup.async_playwright", mock_apw):
        result = await warmup_cookies("goudengids.be")

    assert isinstance(result, WarmupResult)
    assert "incap_ses_1234_5678" in result.cookies
    assert "visid_incap_5678" in result.cookies
    assert "nlbi_5678" in result.cookies


@pytest.mark.asyncio
async def test_warmup_filters_non_imperva_cookies() -> None:
    mock_apw = _make_playwright_mock()
    with patch("scraper.sources.goudengids.warmup.async_playwright", mock_apw):
        result = await warmup_cookies("goudengids.be")

    assert "_ga" not in result.cookies
    assert "_gid" not in result.cookies


@pytest.mark.asyncio
async def test_warmup_obtained_at_is_recent() -> None:
    before = datetime.now(tz=UTC)
    mock_apw = _make_playwright_mock()
    with patch("scraper.sources.goudengids.warmup.async_playwright", mock_apw):
        result = await warmup_cookies()
    after = datetime.now(tz=UTC)

    assert before <= result.obtained_at <= after


@pytest.mark.asyncio
async def test_warmup_browser_always_closed() -> None:
    mock_apw = _make_playwright_mock()
    with patch("scraper.sources.goudengids.warmup.async_playwright", mock_apw):
        await warmup_cookies()

    mock_browser = mock_apw.return_value.__aenter__.return_value.chromium.launch.return_value
    mock_browser.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_warmup_retries_on_navigation_failure_then_succeeds() -> None:
    """First _navigate_and_harvest fails, second succeeds — result returned."""
    calls = 0

    async def _flaky_navigate(browser, url, timeout_ms):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("navigation timeout")
        return _IMPERVA_COOKIES

    mock_apw = _make_playwright_mock()
    with (
        patch("scraper.sources.goudengids.warmup.async_playwright", mock_apw),
        patch("scraper.sources.goudengids.warmup._navigate_and_harvest", _flaky_navigate),
    ):
        result = await warmup_cookies()

    assert calls == 2
    assert "incap_ses_1234_5678" in result.cookies


@pytest.mark.asyncio
async def test_warmup_raises_warmup_failed_error_on_double_failure() -> None:
    async def _always_fail(browser, url, timeout_ms):  # type: ignore[no-untyped-def]
        raise RuntimeError("page unreachable")

    mock_apw = _make_playwright_mock()
    with (
        patch("scraper.sources.goudengids.warmup.async_playwright", mock_apw),
        patch("scraper.sources.goudengids.warmup._navigate_and_harvest", _always_fail),
        pytest.raises(WarmupFailedError),
    ):
        await warmup_cookies()


def test_is_expired_after_ttl() -> None:
    result = WarmupResult(
        cookies={"incap_ses_x": "v"},
        obtained_at=datetime.now(tz=UTC),
        ttl_minutes=25,
    )
    future = result.obtained_at + timedelta(minutes=26)
    assert is_expired(result, now=future) is True


def test_is_expired_before_ttl() -> None:
    result = WarmupResult(
        cookies={"incap_ses_x": "v"},
        obtained_at=datetime.now(tz=UTC),
        ttl_minutes=25,
    )
    soon = result.obtained_at + timedelta(minutes=20)
    assert is_expired(result, now=soon) is False


def test_is_expired_at_exact_ttl() -> None:
    result = WarmupResult(
        cookies={"incap_ses_x": "v"},
        obtained_at=datetime.now(tz=UTC),
        ttl_minutes=25,
    )
    exact = result.obtained_at + timedelta(minutes=25)
    assert is_expired(result, now=exact) is True
