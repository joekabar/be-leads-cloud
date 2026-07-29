"""Unit tests for website/ingester.py — no real network or DB needed."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from scraper.sources.website.fetcher import FetchedPage
from scraper.sources.website.ingester import (
    WebsiteReport,
    _process_company,
    _recent_website_kbos,
    ingest_kbos,
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


def _fake_page(status: int = 200, html: str = "<html></html>") -> FetchedPage:
    return FetchedPage(
        url="https://example.be",
        html=html,
        status=status,
        final_url="https://example.be/",
    )


class TestRecentWebsiteKbos:
    async def test_returns_empty_set_when_no_rows(self) -> None:
        pool = _make_pool()
        pool.fetch = AsyncMock(return_value=[])
        result = await _recent_website_kbos(pool, datetime.now(tz=UTC))
        assert result == set()

    async def test_returns_kbo_numbers_from_rows(self) -> None:
        pool = _make_pool()
        pool.fetch = AsyncMock(return_value=[{"kbo_number": "0403019261"}])
        result = await _recent_website_kbos(pool, datetime.now(tz=UTC))
        assert "0403019261" in result


class TestProcessCompany:
    async def test_returns_empty_on_fetch_exception(self) -> None:
        client = MagicMock()
        run_id = uuid.uuid4()

        with patch(
            "scraper.sources.website.ingester.fetch_page",
            new=AsyncMock(side_effect=RuntimeError("connection refused")),
        ):
            obs, pages = await _process_company(
                "0403019261", "https://example.be", client, run_id, datetime.now(tz=UTC)
            )

        assert obs == []
        assert pages == 0

    async def test_returns_empty_on_bad_status(self) -> None:
        client = MagicMock()
        run_id = uuid.uuid4()

        with patch(
            "scraper.sources.website.ingester.fetch_page",
            new=AsyncMock(return_value=_fake_page(status=404)),
        ):
            obs, pages = await _process_company(
                "0403019261", "https://example.be", client, run_id, datetime.now(tz=UTC)
            )

        assert obs == []
        assert pages == 1

    async def test_returns_observations_on_success(self) -> None:
        client = MagicMock()
        run_id = uuid.uuid4()
        fake_obs = [MagicMock()]

        with (
            patch(
                "scraper.sources.website.ingester.fetch_page",
                new=AsyncMock(return_value=_fake_page()),
            ),
            patch("scraper.sources.website.ingester.extract_jsonld", return_value={}),
            patch(
                "scraper.sources.website.ingester.estimate_age", new=AsyncMock(return_value=None)
            ),
            patch(
                "scraper.sources.website.ingester.find_contact_page",
                new=AsyncMock(return_value=None),
            ),
            patch("scraper.sources.website.ingester.extract_persons", return_value=[]),
            patch("scraper.sources.website.ingester.site_to_observations", return_value=fake_obs),
        ):
            obs, pages = await _process_company(
                "0403019261", "https://example.be", client, run_id, datetime.now(tz=UTC)
            )

        assert obs == fake_obs
        assert pages == 1

    async def test_fetches_contact_page_when_different_url(self) -> None:
        client = MagicMock()
        run_id = uuid.uuid4()
        contact_page = _fake_page(html="<html>contact</html>")
        contact_page = FetchedPage(
            url="https://example.be/contact",
            html="<html>contact</html>",
            status=200,
            final_url="https://example.be/contact",
        )

        with (
            patch(
                "scraper.sources.website.ingester.fetch_page",
                new=AsyncMock(side_effect=[_fake_page(), contact_page]),
            ),
            patch("scraper.sources.website.ingester.extract_jsonld", return_value={}),
            patch(
                "scraper.sources.website.ingester.estimate_age", new=AsyncMock(return_value=None)
            ),
            patch(
                "scraper.sources.website.ingester.find_contact_page",
                new=AsyncMock(return_value="https://example.be/contact"),
            ),
            patch("scraper.sources.website.ingester.extract_persons", return_value=[]),
            patch(
                "scraper.sources.website.ingester.site_to_observations", return_value=[MagicMock()]
            ),
        ):
            _obs, pages = await _process_company(
                "0403019261", "https://example.be", client, run_id, datetime.now(tz=UTC)
            )

        assert pages == 2

    async def test_contact_page_fetch_exception_ignored(self) -> None:
        client = MagicMock()
        run_id = uuid.uuid4()

        with (
            patch(
                "scraper.sources.website.ingester.fetch_page",
                new=AsyncMock(side_effect=[_fake_page(), RuntimeError("contact page timeout")]),
            ),
            patch("scraper.sources.website.ingester.extract_jsonld", return_value={}),
            patch(
                "scraper.sources.website.ingester.estimate_age", new=AsyncMock(return_value=None)
            ),
            patch(
                "scraper.sources.website.ingester.find_contact_page",
                new=AsyncMock(return_value="https://example.be/contact"),
            ),
            patch("scraper.sources.website.ingester.extract_persons", return_value=[]),
            patch(
                "scraper.sources.website.ingester.site_to_observations", return_value=[MagicMock()]
            ),
        ):
            obs, pages = await _process_company(
                "0403019261", "https://example.be", client, run_id, datetime.now(tz=UTC)
            )

        assert pages == 1
        assert len(obs) == 1


class TestIngestKbos:
    async def test_empty_list_returns_zero_report(self) -> None:
        pool = _make_pool()
        mock_runs_cls = MagicMock()
        mock_runs_cls.return_value.start_run = AsyncMock(return_value=uuid.uuid4())
        mock_runs_cls.return_value.finish_run = AsyncMock()
        mock_obs_cls = MagicMock()
        mock_obs_cls.return_value.insert_many = AsyncMock(return_value=[])

        with (
            patch("scraper.sources.website.ingester.RunsRepo", mock_runs_cls),
            patch("scraper.sources.website.ingester.ObservationsRepo", mock_obs_cls),
        ):
            report = await ingest_kbos([], pool, MagicMock())

        assert isinstance(report, WebsiteReport)
        assert report.kbos_processed == 0
        assert report.observations_inserted == 0

    async def test_skips_recent_kbos(self) -> None:
        pool = _make_pool()
        pool.fetch = AsyncMock(return_value=[{"kbo_number": "0403019261"}])

        mock_runs_cls = MagicMock()
        mock_runs_cls.return_value.start_run = AsyncMock(return_value=uuid.uuid4())
        mock_runs_cls.return_value.finish_run = AsyncMock()
        mock_obs_cls = MagicMock()
        mock_obs_cls.return_value.insert_many = AsyncMock(return_value=[])

        with (
            patch("scraper.sources.website.ingester.RunsRepo", mock_runs_cls),
            patch("scraper.sources.website.ingester.ObservationsRepo", mock_obs_cls),
        ):
            report = await ingest_kbos(
                [("0403019261", "https://delhaize.be")],
                pool,
                MagicMock(),
                skip_recent_hours=168,
            )

        assert report.kbos_processed == 0

    async def test_processes_company_and_inserts_observations(self) -> None:
        pool = _make_pool()

        mock_runs_cls = MagicMock()
        mock_runs_cls.return_value.start_run = AsyncMock(return_value=uuid.uuid4())
        mock_runs_cls.return_value.finish_run = AsyncMock()
        mock_obs_cls = MagicMock()
        mock_obs_cls.return_value.insert_many = AsyncMock(return_value=[1, 2])

        with (
            patch("scraper.sources.website.ingester.RunsRepo", mock_runs_cls),
            patch("scraper.sources.website.ingester.ObservationsRepo", mock_obs_cls),
            patch(
                "scraper.sources.website.ingester._process_company",
                new=AsyncMock(return_value=([MagicMock(), MagicMock()], 1)),
            ),
        ):
            report = await ingest_kbos(
                [("0403019261", "https://delhaize.be")],
                pool,
                MagicMock(),
                skip_recent_hours=0,
            )

        assert report.kbos_processed == 1
        assert report.observations_inserted == 2
        assert report.fetch_failures == 0

    async def test_counts_fetch_failures(self) -> None:
        pool = _make_pool()

        mock_runs_cls = MagicMock()
        mock_runs_cls.return_value.start_run = AsyncMock(return_value=uuid.uuid4())
        mock_runs_cls.return_value.finish_run = AsyncMock()
        mock_obs_cls = MagicMock()
        mock_obs_cls.return_value.insert_many = AsyncMock(return_value=[])

        with (
            patch("scraper.sources.website.ingester.RunsRepo", mock_runs_cls),
            patch("scraper.sources.website.ingester.ObservationsRepo", mock_obs_cls),
            patch(
                "scraper.sources.website.ingester._process_company",
                new=AsyncMock(return_value=([], 0)),
            ),
        ):
            report = await ingest_kbos(
                [("0403019261", "https://delhaize.be")],
                pool,
                MagicMock(),
                skip_recent_hours=0,
            )

        assert report.kbos_processed == 1
        assert report.fetch_failures == 1
