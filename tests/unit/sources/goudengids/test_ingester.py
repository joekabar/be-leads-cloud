"""Unit tests for goudengids/ingester.py — no real browser or DB needed."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scraper.pipeline.sector_queue import COMPLETE_MARKER
from scraper.sources.goudengids.ingester import (
    GoudengidsReport,
    _recent_placeholder_kbos,
    ingest_sector_city,
    load_valid_sectors,
)
from scraper.sources.goudengids.parser import ListingCardRow


def _card(postal: str = "8400", name: str = "Test BV") -> ListingCardRow:
    """A minimal listing card, in or out of the target city per *postal*."""
    return ListingCardRow(
        name=name,
        detail_url="https://www.goudengids.be/x",
        phones=["059 70 00 00"],
        website=None,
        email=None,
        address_street="Teststraat 1",
        address_postal_code=postal,
        address_city="Oostende" if postal.startswith("84") else "Brussel",
        description=None,
        logo_url=None,
        raw_card_html="<div></div>",
    )


def _make_pool() -> MagicMock:
    pool = MagicMock()
    pool.fetch = AsyncMock(return_value=[])
    pool.execute = AsyncMock()
    pool.fetchrow = AsyncMock(return_value={"id": uuid.uuid4()})

    tx_cm = MagicMock()
    tx_cm.__aenter__ = AsyncMock(return_value=None)
    tx_cm.__aexit__ = AsyncMock(return_value=False)

    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value={"id": 1})
    conn.transaction = MagicMock(return_value=tx_cm)

    acquire_cm = MagicMock()
    acquire_cm.__aenter__ = AsyncMock(return_value=conn)
    acquire_cm.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=acquire_cm)

    return pool


def _make_fetcher(listing_pages=None) -> MagicMock:
    """Return a fetcher mock usable as `async with fetcher:`."""
    fetcher = MagicMock()
    fetcher._domain = "goudengids.be"

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=fetcher)
    cm.__aexit__ = AsyncMock(return_value=False)
    fetcher.__aenter__ = cm.__aenter__
    fetcher.__aexit__ = cm.__aexit__

    if listing_pages is None:
        listing_pages = []

    fetcher.fetch_page = AsyncMock(side_effect=listing_pages or [_last_page()])
    return fetcher


def _last_page(html: str = "<html></html>") -> MagicMock:
    page = MagicMock()
    page.is_last_page = True
    page.html = html
    return page


def _normal_page(html: str = "<html></html>") -> MagicMock:
    page = MagicMock()
    page.is_last_page = False
    page.html = html
    return page


class TestStopsOnceResultsLeaveTheCity:
    """Stop paging when goudengids has switched to nationwide filler.

    When a sector is thin locally the site pads results with companies from anywhere,
    which the postcode filter then discards. Those runs cost the most and yield the
    least: `machinebouwers` fetched 25 pages and 500 cards of which **all 500** were out
    of city, and `logistiekverleners` kept 35 of 500. Meanwhile the WAF tightened from
    ~120 pages per block to ~11, so the most expensive requests were also the ones
    burning a shrinking budget on data that is thrown away.

    Local results rank first, so several consecutive pages with no in-city card means the
    useful part is already behind us.
    """

    def _cards_html(self, n_in_city: int, n_out: int) -> str:
        parts = []
        for i in range(n_in_city):
            parts.append(f'<div class="card"><h2>In {i}</h2><span>8400 Oostende</span></div>')
        for i in range(n_out):
            parts.append(f'<div class="card"><h2>Out {i}</h2><span>1000 Brussel</span></div>')
        return "<html>" + "".join(parts) + "</html>"

    async def test_aborts_after_consecutive_out_of_city_pages(self) -> None:
        pool = _make_pool()
        # 10 pages available, but none of them hold an in-city card.
        pages = [_normal_page(self._cards_html(0, 20)) for _ in range(10)]
        fetcher = _make_fetcher(pages)

        with patch(
            "scraper.sources.goudengids.ingester.parse_listing_page",
            side_effect=lambda html, domain: [_card(postal="1000") for _ in range(20)],
        ):
            report = await ingest_sector_city(
                "machinebouw", "oostende", pool, fetcher, max_pages=10, max_empty_pages=3
            )

        assert report.pages_scanned == 3, "must stop after 3 fruitless pages, not fetch all 10"

    async def test_keeps_paging_while_in_city_cards_appear(self) -> None:
        pool = _make_pool()
        pages = [_normal_page() for _ in range(5)] + [_last_page()]
        fetcher = _make_fetcher(pages)

        with patch(
            "scraper.sources.goudengids.ingester.parse_listing_page",
            side_effect=lambda html, domain: [_card(postal="8400")],
        ):
            report = await ingest_sector_city(
                "restaurants", "oostende", pool, fetcher, max_pages=10, max_empty_pages=3
            )

        assert report.pages_scanned >= 5, "productive pages must not trigger the bail-out"

    async def test_streak_resets_when_a_local_card_reappears(self) -> None:
        """Two empty pages then a good one must not count toward the limit."""
        pool = _make_pool()
        pages = [_normal_page() for _ in range(8)] + [_last_page()]
        fetcher = _make_fetcher(pages)
        postcodes = ["1000", "1000", "8400", "1000", "1000", "1000", "8400", "8400"]
        calls = iter(postcodes)

        with patch(
            "scraper.sources.goudengids.ingester.parse_listing_page",
            side_effect=lambda html, domain: [_card(postal=next(calls, "8400"))],
        ):
            report = await ingest_sector_city(
                "loodgieters", "oostende", pool, fetcher, max_pages=9, max_empty_pages=3
            )

        assert report.pages_scanned > 3, "a reset streak must allow paging to continue"

    async def test_early_stop_still_counts_as_complete(self) -> None:
        """Bailing out is a decision, not a failure — re-running would find the same."""
        pool = _make_pool()
        pages = [_normal_page(self._cards_html(0, 20)) for _ in range(10)]
        fetcher = _make_fetcher(pages)
        finish = AsyncMock()

        with (
            patch(
                "scraper.sources.goudengids.ingester.parse_listing_page",
                side_effect=lambda html, domain: [_card(postal="1000")],
            ),
            patch("scraper.db.repositories.runs.RunsRepo.finish_run", new=finish),
        ):
            await ingest_sector_city(
                "machinebouw", "oostende", pool, fetcher, max_pages=10, max_empty_pages=2
            )

        assert finish.await_args.kwargs["notes"] == COMPLETE_MARKER


class TestLoadValidSectors:
    def test_returns_dict_with_string_keys(self) -> None:
        result = load_valid_sectors()
        assert isinstance(result, dict)
        assert len(result) > 0

    def test_elektriciens_is_valid(self) -> None:
        result = load_valid_sectors()
        assert "elektriciens" in result


class TestRecentPlaceholderKbos:
    async def test_returns_empty_set_when_no_rows(self) -> None:
        from datetime import UTC, datetime

        pool = _make_pool()
        pool.fetch = AsyncMock(return_value=[])
        result = await _recent_placeholder_kbos(pool, datetime.now(tz=UTC))
        assert result == set()

    async def test_returns_placeholder_kbo_numbers(self) -> None:
        from datetime import UTC, datetime

        pool = _make_pool()
        pool.fetch = AsyncMock(return_value=[{"kbo_number": "9000000001"}])
        result = await _recent_placeholder_kbos(pool, datetime.now(tz=UTC))
        assert "9000000001" in result


class TestIngestSectorCity:
    async def test_raises_for_unknown_sector(self) -> None:
        pool = _make_pool()
        fetcher = _make_fetcher()
        with pytest.raises(ValueError, match="Unknown sector slug"):
            await ingest_sector_city("not_a_real_sector", "antwerpen", pool, fetcher)

    async def test_raises_for_empty_city(self) -> None:
        pool = _make_pool()
        fetcher = _make_fetcher()
        with pytest.raises(ValueError, match="city_slug must not be empty"):
            await ingest_sector_city("elektriciens", "   ", pool, fetcher)

    async def test_single_last_page_returns_report(self) -> None:
        pool = _make_pool()
        fetcher = _make_fetcher(listing_pages=[_last_page()])

        mock_runs_cls = MagicMock()
        mock_runs_cls.return_value.start_run = AsyncMock(return_value=uuid.uuid4())
        mock_runs_cls.return_value.finish_run = AsyncMock()

        mock_obs_cls = MagicMock()
        mock_obs_cls.return_value.insert_many = AsyncMock(return_value=[])

        with (
            patch("scraper.sources.goudengids.ingester.RunsRepo", mock_runs_cls),
            patch("scraper.sources.goudengids.ingester.ObservationsRepo", mock_obs_cls),
        ):
            report = await ingest_sector_city(
                "elektriciens", "antwerpen", pool, fetcher, skip_recent_hours=0
            )

        assert isinstance(report, GoudengidsReport)
        assert report.pages_scanned == 1
        assert report.sector == "elektriciens"
        assert report.city == "antwerpen"

    async def test_stops_on_blocked_error(self) -> None:
        from scraper.lib.errors import BlockedError

        pool = _make_pool()
        fetcher = _make_fetcher()
        fetcher.fetch_page = AsyncMock(
            side_effect=BlockedError(403, "https://goudengids.be/", "blocked")
        )

        mock_runs_cls = MagicMock()
        mock_runs_cls.return_value.start_run = AsyncMock(return_value=uuid.uuid4())
        mock_runs_cls.return_value.finish_run = AsyncMock()

        mock_obs_cls = MagicMock()
        mock_obs_cls.return_value.insert_many = AsyncMock(return_value=[])

        with (
            patch("scraper.sources.goudengids.ingester.RunsRepo", mock_runs_cls),
            patch("scraper.sources.goudengids.ingester.ObservationsRepo", mock_obs_cls),
        ):
            report = await ingest_sector_city(
                "elektriciens", "antwerpen", pool, fetcher, skip_recent_hours=0
            )

        assert report.pages_scanned == 0

    async def test_stops_on_timeout(self) -> None:
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError

        pool = _make_pool()
        fetcher = _make_fetcher()
        fetcher.fetch_page = AsyncMock(side_effect=PlaywrightTimeoutError("timeout"))

        mock_runs_cls = MagicMock()
        mock_runs_cls.return_value.start_run = AsyncMock(return_value=uuid.uuid4())
        mock_runs_cls.return_value.finish_run = AsyncMock()

        mock_obs_cls = MagicMock()
        mock_obs_cls.return_value.insert_many = AsyncMock(return_value=[])

        with (
            patch("scraper.sources.goudengids.ingester.RunsRepo", mock_runs_cls),
            patch("scraper.sources.goudengids.ingester.ObservationsRepo", mock_obs_cls),
        ):
            report = await ingest_sector_city(
                "elektriciens", "antwerpen", pool, fetcher, skip_recent_hours=0
            )

        assert report.pages_scanned == 0

    async def test_cards_with_phone_and_website_counted(self) -> None:
        from scraper.sources.goudengids.parser import ListingCardRow as BusinessCard

        pool = _make_pool()
        # is_last_page=False so the ingester processes cards before ending at max_pages=1
        fetcher = _make_fetcher(listing_pages=[_normal_page()])

        fake_card = BusinessCard(
            name="Elektro NV",
            detail_url="https://goudengids.be/elektro-nv",
            phones=["+3232361306"],
            website="https://elektro.be",
            email=None,
            address_street=None,
            address_postal_code="2000",
            address_city="Antwerpen",
            description=None,
            logo_url=None,
            raw_card_html="<li>Elektro NV</li>",
        )

        mock_runs_cls = MagicMock()
        mock_runs_cls.return_value.start_run = AsyncMock(return_value=uuid.uuid4())
        mock_runs_cls.return_value.finish_run = AsyncMock()

        mock_obs_cls = MagicMock()
        mock_obs_cls.return_value.insert_many = AsyncMock(return_value=[1])

        with (
            patch("scraper.sources.goudengids.ingester.RunsRepo", mock_runs_cls),
            patch("scraper.sources.goudengids.ingester.ObservationsRepo", mock_obs_cls),
            patch(
                "scraper.sources.goudengids.ingester.parse_listing_page", return_value=[fake_card]
            ),
            patch(
                "scraper.sources.goudengids.ingester.make_placeholder_kbo",
                return_value="9123456789",
            ),
            patch(
                "scraper.sources.goudengids.ingester.card_to_observations",
                return_value=[MagicMock()],
            ),
        ):
            report = await ingest_sector_city(
                "elektriciens", "antwerpen", pool, fetcher, skip_recent_hours=0, max_pages=1
            )

        assert report.cards_found == 1
        assert report.cards_with_phone == 1
        assert report.cards_with_website == 1
        assert report.placeholders_created == 1

    async def test_recent_placeholder_skipped(self) -> None:
        from scraper.sources.goudengids.parser import ListingCardRow as BusinessCard

        pool = _make_pool()
        pool.fetch = AsyncMock(return_value=[{"kbo_number": "9123456789"}])
        fetcher = _make_fetcher(listing_pages=[_normal_page()])

        fake_card = BusinessCard(
            name="Elektro NV",
            detail_url="https://goudengids.be/elektro-nv",
            phones=[],
            website=None,
            email=None,
            address_street=None,
            address_postal_code="2000",
            address_city="Antwerpen",
            description=None,
            logo_url=None,
            raw_card_html="<li>Elektro NV</li>",
        )

        mock_runs_cls = MagicMock()
        mock_runs_cls.return_value.start_run = AsyncMock(return_value=uuid.uuid4())
        mock_runs_cls.return_value.finish_run = AsyncMock()

        mock_obs_cls = MagicMock()
        mock_obs_cls.return_value.insert_many = AsyncMock(return_value=[])

        with (
            patch("scraper.sources.goudengids.ingester.RunsRepo", mock_runs_cls),
            patch("scraper.sources.goudengids.ingester.ObservationsRepo", mock_obs_cls),
            patch(
                "scraper.sources.goudengids.ingester.parse_listing_page", return_value=[fake_card]
            ),
            patch(
                "scraper.sources.goudengids.ingester.make_placeholder_kbo",
                return_value="9123456789",
            ),
        ):
            report = await ingest_sector_city(
                "elektriciens", "antwerpen", pool, fetcher, skip_recent_hours=24, max_pages=1
            )

        assert report.observations_inserted == 0
