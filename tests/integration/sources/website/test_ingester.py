"""Integration tests for website ingester — HTTP mocked with respx, real DB."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
import respx

from scraper.lib.http.client import get_polite_client
from scraper.sources.website.ingester import WebsiteReport, ingest_kbos

from .conftest import make_fast_limiter

pytestmark = pytest.mark.integration

_GOLDEN = Path("tests/golden/website")

_KBO_BELLOCK = "0439401387"
_KBO_BOONEN = "0502699332"
_KBO_EXAMPLE = "9000000003"  # placeholder KBO (9-prefix)


def _html(name: str) -> str:
    return (_GOLDEN / name).read_text(encoding="utf-8")


@pytest.fixture()
async def fresh_pool(clean_pool):  # type: ignore[no-untyped-def]
    await clean_pool.execute("SELECT refresh_companies_current()")
    return clean_pool


@pytest.mark.asyncio
async def test_ingest_three_websites(fresh_pool) -> None:  # type: ignore[no-untyped-def]
    pairs = [
        (_KBO_BELLOCK, "https://bellock.be"),
        (_KBO_BOONEN, "https://boonen-partners.be"),
        (_KBO_EXAMPLE, "https://example.be"),
    ]

    with respx.mock, patch("scraper.sources.website.age._WHOIS_AVAILABLE", False):
        respx.get("https://bellock.be").mock(
            return_value=httpx.Response(200, text=_html("wordpress_local_business.html"))
        )
        respx.get("https://boonen-partners.be").mock(
            return_value=httpx.Response(200, text=_html("squarespace_org.html"))
        )
        respx.get("https://example.be").mock(
            return_value=httpx.Response(200, text=_html("custom_no_jsonld.html"))
        )
        # contact page probes — all 404
        respx.route(method="HEAD").mock(return_value=httpx.Response(404))

        limiter = make_fast_limiter()
        async with get_polite_client(limiter) as client:
            report = await ingest_kbos(
                pairs,
                fresh_pool,
                client,
                skip_recent_hours=0,
                concurrent_companies=3,
            )

    assert isinstance(report, WebsiteReport)
    assert report.kbos_processed == 3
    assert report.observations_inserted > 0
    assert report.fetch_failures == 0


@pytest.mark.asyncio
async def test_fetch_failure_counted(fresh_pool) -> None:  # type: ignore[no-untyped-def]
    pairs = [
        (_KBO_BELLOCK, "https://bellock.be"),
        (_KBO_BOONEN, "https://boonen-partners.be"),
    ]

    with respx.mock, patch("scraper.sources.website.age._WHOIS_AVAILABLE", False):
        respx.get("https://bellock.be").mock(
            return_value=httpx.Response(200, text=_html("wordpress_local_business.html"))
        )
        respx.get("https://boonen-partners.be").mock(
            return_value=httpx.Response(500, text="Server Error")
        )
        respx.route(method="HEAD").mock(return_value=httpx.Response(404))

        limiter = make_fast_limiter()
        async with get_polite_client(limiter) as client:
            report = await ingest_kbos(
                pairs,
                fresh_pool,
                client,
                skip_recent_hours=0,
            )

    assert report.fetch_failures == 1
    assert report.kbos_processed == 2
    rows = await fresh_pool.fetch(
        "SELECT DISTINCT kbo_number FROM observations WHERE source = 'website'"
    )
    kbos = {r["kbo_number"] for r in rows}
    assert _KBO_BELLOCK in kbos
    assert _KBO_BOONEN not in kbos


@pytest.mark.asyncio
async def test_skip_recent_7_days(fresh_pool) -> None:  # type: ignore[no-untyped-def]
    pairs = [(_KBO_BELLOCK, "https://bellock.be")]

    def _mock() -> None:
        respx.get("https://bellock.be").mock(
            return_value=httpx.Response(200, text=_html("wordpress_local_business.html"))
        )
        respx.route(method="HEAD").mock(return_value=httpx.Response(404))

    with respx.mock, patch("scraper.sources.website.age._WHOIS_AVAILABLE", False):
        _mock()
        limiter = make_fast_limiter()
        async with get_polite_client(limiter) as client:
            report1 = await ingest_kbos(pairs, fresh_pool, client, skip_recent_hours=168)

    with respx.mock, patch("scraper.sources.website.age._WHOIS_AVAILABLE", False):
        _mock()
        limiter = make_fast_limiter()
        async with get_polite_client(limiter) as client:
            report2 = await ingest_kbos(pairs, fresh_pool, client, skip_recent_hours=168)

    assert report1.observations_inserted > 0
    assert report2.observations_inserted == 0
    assert report2.kbos_processed == 0


@pytest.mark.asyncio
async def test_concurrent_companies_limit(fresh_pool) -> None:  # type: ignore[no-untyped-def]
    """At most N companies in-flight simultaneously."""
    peak: list[int] = [0]
    current: list[int] = [0]

    kbos = [
        ("0439401387", "https://site1.be"),
        ("0502699332", "https://site2.be"),
        ("9000000001", "https://site3.be"),
        ("9000000002", "https://site4.be"),
    ]

    async def _slow_response(request: httpx.Request) -> httpx.Response:
        current[0] += 1
        peak[0] = max(peak[0], current[0])
        await asyncio.sleep(0.05)
        current[0] -= 1
        fname = "wordpress_local_business.html"
        return httpx.Response(200, text=_html(fname))

    with respx.mock, patch("scraper.sources.website.age._WHOIS_AVAILABLE", False):
        respx.route(method="GET").mock(side_effect=_slow_response)
        respx.route(method="HEAD").mock(return_value=httpx.Response(404))

        limiter = make_fast_limiter()
        async with get_polite_client(limiter) as client:
            await ingest_kbos(kbos, fresh_pool, client, skip_recent_hours=0, concurrent_companies=2)

    assert peak[0] <= 2
