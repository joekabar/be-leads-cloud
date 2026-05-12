"""Integration tests for be-leads-enrich-website ingester (CLI-facing logic)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
import respx

from scraper.lib.http.client import get_polite_client
from scraper.sources.website.ingester import ingest_kbos

from .conftest import make_fast_limiter

pytestmark = pytest.mark.integration

_GOLDEN = Path("tests/golden/website")


def _html(name: str) -> str:
    return (_GOLDEN / name).read_text(encoding="utf-8")


@pytest.fixture()
async def fresh_pool(clean_pool):  # type: ignore[no-untyped-def]
    await clean_pool.execute("SELECT refresh_companies_current()")
    return clean_pool


@pytest.mark.asyncio
async def test_ingest_from_pairs(fresh_pool) -> None:  # type: ignore[no-untyped-def]
    pairs = [
        ("0439401387", "https://bellock.be"),
        ("0502699332", "https://boonen-partners.be"),
    ]

    with respx.mock, patch("scraper.sources.website.age._WHOIS_AVAILABLE", False):
        respx.get("https://bellock.be").mock(
            return_value=httpx.Response(200, text=_html("wordpress_local_business.html"))
        )
        respx.get("https://boonen-partners.be").mock(
            return_value=httpx.Response(200, text=_html("squarespace_org.html"))
        )
        respx.route(method="HEAD").mock(return_value=httpx.Response(404))

        limiter = make_fast_limiter()
        async with get_polite_client(limiter) as client:
            report = await ingest_kbos(pairs, fresh_pool, client, skip_recent_hours=0)

    assert report.kbos_processed == 2
    assert report.observations_inserted > 0


@pytest.mark.asyncio
async def test_empty_pairs_returns_zero(fresh_pool) -> None:  # type: ignore[no-untyped-def]
    with patch("scraper.sources.website.age._WHOIS_AVAILABLE", False):
        limiter = make_fast_limiter()
        async with get_polite_client(limiter) as client:
            report = await ingest_kbos([], fresh_pool, client, skip_recent_hours=0)

    assert report.kbos_processed == 0
    assert report.observations_inserted == 0
