"""Unit tests for BrowserListingFetcher."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from scraper.sources.goudengids.fetcher import BrowserListingFetcher


class TestFetchListingNavTimeout:
    """Navigation timeout must not abort the fetch — content is still extracted."""

    async def test_nav_timeout_still_returns_content(self) -> None:
        limiter = MagicMock()
        limiter.acquire = AsyncMock()
        fetcher = BrowserListingFetcher(limiter)
        fetcher._warmed_up = True

        page_mock = AsyncMock()
        page_mock.goto.side_effect = PlaywrightTimeoutError("navigation timeout")
        page_mock.wait_for_selector.side_effect = PlaywrightTimeoutError("selector timeout")
        page_mock.content.return_value = "<html><body>some listing html</body></html>"

        context_mock = MagicMock()
        context_mock.new_page = AsyncMock(return_value=page_mock)
        fetcher._context = context_mock

        html = await fetcher.fetch_listing("https://www.goudengids.be/zoeken/elektriciens/gent/1/")
        assert html == "<html><body>some listing html</body></html>"
        page_mock.close.assert_awaited_once()

    async def test_nav_timeout_then_block_raises(self) -> None:
        """If nav times out but content contains an Imperva block, BlockedError is still raised."""
        from scraper.lib.errors import BlockedError

        limiter = MagicMock()
        limiter.acquire = AsyncMock()
        fetcher = BrowserListingFetcher(limiter)
        fetcher._warmed_up = True

        page_mock = AsyncMock()
        page_mock.goto.side_effect = PlaywrightTimeoutError("navigation timeout")
        page_mock.wait_for_selector.side_effect = PlaywrightTimeoutError("selector timeout")
        page_mock.content.return_value = "<html>pardon our interruption</html>"

        context_mock = MagicMock()
        context_mock.new_page = AsyncMock(return_value=page_mock)
        fetcher._context = context_mock

        with pytest.raises(BlockedError):
            await fetcher.fetch_listing("https://www.goudengids.be/zoeken/x/y/1/")


class TestBrowserListingFetcherAexit:
    """Cleanup errors must not replace the original exception."""

    async def test_aexit_suppresses_browser_close_error(self) -> None:
        """If browser.close() raises, the original exception is preserved."""
        limiter = MagicMock()
        fetcher = BrowserListingFetcher(limiter)

        browser_mock = AsyncMock()
        browser_mock.close.side_effect = RuntimeError("browser already dead")
        pw_mock = AsyncMock()
        fetcher._browser = browser_mock
        fetcher._pw = pw_mock

        # Should not raise
        await fetcher.__aexit__(None, None, None)

        assert fetcher._browser is None
        assert fetcher._pw is None
        assert fetcher._context is None

    async def test_aexit_suppresses_pw_stop_error(self) -> None:
        """If pw.stop() raises, it is suppressed and state is cleared."""
        limiter = MagicMock()
        fetcher = BrowserListingFetcher(limiter)

        browser_mock = AsyncMock()
        pw_mock = AsyncMock()
        pw_mock.stop.side_effect = RuntimeError("playwright already stopped")
        fetcher._browser = browser_mock
        fetcher._pw = pw_mock

        await fetcher.__aexit__(None, None, None)

        assert fetcher._browser is None
        assert fetcher._pw is None

    async def test_aexit_clears_state_when_both_none(self) -> None:
        """aexit is a no-op when browser/pw are already None."""
        limiter = MagicMock()
        fetcher = BrowserListingFetcher(limiter)
        # browser and pw are None by default
        await fetcher.__aexit__(None, None, None)
        assert fetcher._context is None

    async def test_fetch_listing_requires_context_manager(self) -> None:
        """Calling fetch_listing without __aenter__ raises RuntimeError."""
        limiter = MagicMock()
        fetcher = BrowserListingFetcher(limiter)
        with pytest.raises(RuntimeError, match="async context manager"):
            await fetcher.fetch_listing("https://www.goudengids.be/zoeken/elektriciens/gent/1/")
