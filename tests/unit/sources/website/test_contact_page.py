"""Unit tests for website contact_page.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scraper.sources.website.contact_page import find_contact_page

_GOLDEN = Path("tests/golden/website")


def _html(name: str) -> str:
    return (_GOLDEN / name).read_text(encoding="utf-8")


def _make_client(head_responses: dict[str, int]) -> MagicMock:
    """Fake PoliteClient whose _request returns a mock response for HEAD calls."""
    client = MagicMock()

    async def _fake_request(method: str, url: str, **_kwargs: object) -> MagicMock:
        status = head_responses.get(url, 404)
        resp = MagicMock()
        resp.status_code = status
        return resp

    client._request = _fake_request
    return client


class TestFindContactPage:
    @pytest.mark.asyncio
    async def test_finds_contact_link_in_homepage(self) -> None:
        html = """
        <html><body>
        <a href="/contact">Contacteer ons</a>
        <a href="/over-ons">Over ons</a>
        </body></html>
        """
        client = _make_client({})
        result = await find_contact_page(client, "https://example.be", html)
        assert result == "https://example.be/contact"

    @pytest.mark.asyncio
    async def test_falls_back_to_head_probe(self) -> None:
        html = "<html><body><p>No links here</p></body></html>"
        client = _make_client({"https://example.be/team": 200})
        result = await find_contact_page(client, "https://example.be", html)
        assert result == "https://example.be/team"

    @pytest.mark.asyncio
    async def test_returns_none_when_nothing_works(self) -> None:
        html = "<html><body><p>No links</p></body></html>"
        client = _make_client({})
        result = await find_contact_page(client, "https://example.be", html)
        assert result is None

    @pytest.mark.asyncio
    async def test_wordpress_has_contact_link(self) -> None:
        html = _html("wordpress_local_business.html")
        client = _make_client({})
        result = await find_contact_page(client, "https://bellock.be", html)
        # fixture has no contact links; should probe and return None since all 404
        assert result is None

    @pytest.mark.asyncio
    async def test_does_not_follow_external_contact_links(self) -> None:
        html = """
        <html><body>
        <a href="https://other-domain.com/contact">External contact</a>
        </body></html>
        """
        client = _make_client({})
        result = await find_contact_page(client, "https://example.be", html)
        assert result is None
