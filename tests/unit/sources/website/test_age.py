"""Unit tests for website age.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scraper.sources.website.age import estimate_age

_GOLDEN = Path("tests/golden/website")


def _html(name: str) -> str:
    return (_GOLDEN / name).read_text(encoding="utf-8")


class TestEstimateAge:
    @pytest.mark.asyncio
    async def test_whois_returns_year(self) -> None:
        fake_result = MagicMock()
        fake_result.creation_date = "2017-03-15 00:00:00"

        with (
            patch("scraper.sources.website.age._WHOIS_AVAILABLE", True),
            patch("scraper.sources.website.age._whois_lib") as mock_whois,
            patch("asyncio.to_thread") as mock_thread,
        ):
            mock_thread.return_value = fake_result
            mock_whois.whois = MagicMock()
            year, source = await estimate_age("https://bellock.be")

        assert year == "2017"
        assert source == "whois"

    @pytest.mark.asyncio
    async def test_whois_list_creation_date(self) -> None:
        fake_result = MagicMock()
        fake_result.creation_date = ["2015-01-01 00:00:00", "2015-06-01 00:00:00"]

        with (
            patch("scraper.sources.website.age._WHOIS_AVAILABLE", True),
            patch("scraper.sources.website.age._whois_lib") as mock_whois,
            patch("asyncio.to_thread") as mock_thread,
        ):
            mock_thread.return_value = fake_result
            mock_whois.whois = MagicMock()
            year, source = await estimate_age("https://example.be")

        assert year == "2015"
        assert source == "whois"

    @pytest.mark.asyncio
    async def test_whois_failure_falls_back_to_footer(self) -> None:
        html = _html("wordpress_local_business.html")

        with (
            patch("scraper.sources.website.age._WHOIS_AVAILABLE", True),
            patch("asyncio.to_thread", side_effect=Exception("WHOIS timeout")),
        ):
            year, source = await estimate_age("https://bellock.be", html)

        assert year == "2017"
        assert source == "footer"

    @pytest.mark.asyncio
    async def test_footer_copyright_year(self) -> None:
        with patch("scraper.sources.website.age._WHOIS_AVAILABLE", False):
            year, source = await estimate_age(
                "https://bellock.be", _html("wordpress_local_business.html")
            )
        assert year == "2017"
        assert source == "footer"

    @pytest.mark.asyncio
    async def test_footer_year_range_takes_max(self) -> None:
        # custom_no_jsonld has copyright 2008-2026
        with patch("scraper.sources.website.age._WHOIS_AVAILABLE", False):
            year, source = await estimate_age("https://example.be", _html("custom_no_jsonld.html"))
        assert year == "2026"
        assert source == "footer"

    @pytest.mark.asyncio
    async def test_no_whois_no_footer_returns_none(self) -> None:
        html = "<html><body><p>No date anywhere.</p></body></html>"
        with patch("scraper.sources.website.age._WHOIS_AVAILABLE", False):
            year, source = await estimate_age("https://example.be", html)
        assert year is None
        assert source == "none"

    @pytest.mark.asyncio
    async def test_no_html_no_whois_returns_none(self) -> None:
        with patch("scraper.sources.website.age._WHOIS_AVAILABLE", False):
            year, source = await estimate_age("https://example.be")
        assert year is None
        assert source == "none"
