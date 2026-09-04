"""Unit tests for ddg_brave/ingester.py — no real network or DB needed."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from scraper.sources.ddg_brave.ingester import (
    _recent_kbos,
    validate_companies,
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


def _patched_repos(run_id=None):
    """Return a pair of (mock_runs_cls, mock_obs_cls) for patching."""
    if run_id is None:
        run_id = uuid.uuid4()

    mock_runs_cls = MagicMock()
    mock_runs_cls.return_value.start_run = AsyncMock(return_value=run_id)
    mock_runs_cls.return_value.finish_run = AsyncMock()

    mock_obs_cls = MagicMock()
    mock_obs_cls.return_value.insert_many = AsyncMock(return_value=[1, 2])

    return mock_runs_cls, mock_obs_cls


class TestRecentKbos:
    async def test_returns_empty_set_when_no_rows(self) -> None:
        from datetime import UTC, datetime

        pool = _make_pool()
        pool.fetch = AsyncMock(return_value=[])
        result = await _recent_kbos(pool, datetime.now(tz=UTC))
        assert result == set()

    async def test_returns_kbo_numbers_from_rows(self) -> None:
        from datetime import UTC, datetime

        pool = _make_pool()
        pool.fetch = AsyncMock(return_value=[{"kbo_number": "0403019261"}])
        result = await _recent_kbos(pool, datetime.now(tz=UTC))
        assert "0403019261" in result


class TestValidateCompanies:
    async def test_empty_list_returns_zero_report(self) -> None:
        pool = _make_pool()
        mock_runs_cls, mock_obs_cls = _patched_repos()

        with (
            patch("scraper.sources.ddg_brave.ingester.RunsRepo", mock_runs_cls),
            patch("scraper.sources.ddg_brave.ingester.ObservationsRepo", mock_obs_cls),
        ):
            report = await validate_companies(
                [],
                pool,
                MagicMock(),
                brave_client=None,
                ddg_client=None,
            )

        assert report.queries_processed == 0
        assert report.observations_inserted == 0

    async def test_skips_recently_seen_kbos(self) -> None:
        pool = _make_pool()
        pool.fetch = AsyncMock(return_value=[{"kbo_number": "0403019261"}])

        mock_runs_cls, mock_obs_cls = _patched_repos()

        with (
            patch("scraper.sources.ddg_brave.ingester.RunsRepo", mock_runs_cls),
            patch("scraper.sources.ddg_brave.ingester.ObservationsRepo", mock_obs_cls),
        ):
            report = await validate_companies(
                [("0403019261", "Delhaize", "Brussel")],
                pool,
                MagicMock(),
                brave_client=None,
                ddg_client=None,
                skip_recent_hours=168,
            )

        assert report.queries_processed == 0

    async def test_skips_when_no_engine_available(self) -> None:
        pool = _make_pool()
        mock_runs_cls, mock_obs_cls = _patched_repos()

        with (
            patch("scraper.sources.ddg_brave.ingester.RunsRepo", mock_runs_cls),
            patch("scraper.sources.ddg_brave.ingester.ObservationsRepo", mock_obs_cls),
        ):
            report = await validate_companies(
                [("0403019261", "Delhaize", "Brussel")],
                pool,
                MagicMock(),
                brave_client=None,
                ddg_client=None,
                skip_recent_hours=0,
            )

        assert report.queries_processed == 0

    async def test_uses_brave_client_when_available(self) -> None:
        from scraper.sources.ddg_brave.brave_client import BraveClient

        pool = _make_pool()
        mock_runs_cls, mock_obs_cls = _patched_repos()

        brave_client = MagicMock(spec=BraveClient)
        brave_client.search = AsyncMock(return_value={"web": {"results": []}})

        with (
            patch("scraper.sources.ddg_brave.ingester.RunsRepo", mock_runs_cls),
            patch("scraper.sources.ddg_brave.ingester.ObservationsRepo", mock_obs_cls),
            patch("scraper.sources.ddg_brave.ingester.parse_brave", return_value=[]),
            patch("scraper.sources.ddg_brave.ingester.classify", return_value=MagicMock()),
            patch("scraper.sources.ddg_brave.ingester.query_to_observations", return_value=[]),
        ):
            report = await validate_companies(
                [("0403019261", "Delhaize", "Brussel")],
                pool,
                MagicMock(),
                brave_client=brave_client,
                ddg_client=None,
                skip_recent_hours=0,
            )

        assert report.brave_queries == 1
        assert report.ddg_queries == 0

    async def test_falls_back_to_ddg_when_brave_unavailable(self) -> None:
        from scraper.sources.ddg_brave.ddg_client import DdgClient

        pool = _make_pool()
        mock_runs_cls, mock_obs_cls = _patched_repos()

        ddg_client = MagicMock(spec=DdgClient)
        ddg_client.search = AsyncMock(return_value=[])

        with (
            patch("scraper.sources.ddg_brave.ingester.RunsRepo", mock_runs_cls),
            patch("scraper.sources.ddg_brave.ingester.ObservationsRepo", mock_obs_cls),
            patch("scraper.sources.ddg_brave.ingester.parse_ddg", return_value=[]),
            patch("scraper.sources.ddg_brave.ingester.query_to_observations", return_value=[]),
        ):
            report = await validate_companies(
                [("0403019261", "Delhaize", "Brussel")],
                pool,
                MagicMock(),
                brave_client=None,
                ddg_client=ddg_client,
                skip_recent_hours=0,
            )

        assert report.ddg_queries == 1
        assert report.brave_queries == 0

    async def test_brave_quota_exhausted_switches_to_ddg(self) -> None:
        from scraper.sources.ddg_brave.brave_client import BraveClient, BraveQuotaExhaustedError
        from scraper.sources.ddg_brave.ddg_client import DdgClient

        pool = _make_pool()
        mock_runs_cls, mock_obs_cls = _patched_repos()

        brave_client = MagicMock(spec=BraveClient)
        brave_client.search = AsyncMock(side_effect=BraveQuotaExhaustedError())

        ddg_client = MagicMock(spec=DdgClient)
        ddg_client.search = AsyncMock(return_value=[])

        with (
            patch("scraper.sources.ddg_brave.ingester.RunsRepo", mock_runs_cls),
            patch("scraper.sources.ddg_brave.ingester.ObservationsRepo", mock_obs_cls),
            patch("scraper.sources.ddg_brave.ingester.parse_ddg", return_value=[]),
            patch("scraper.sources.ddg_brave.ingester.query_to_observations", return_value=[]),
        ):
            report = await validate_companies(
                [("0403019261", "Delhaize", "Brussel")],
                pool,
                MagicMock(),
                brave_client=brave_client,
                ddg_client=ddg_client,
                skip_recent_hours=0,
            )

        assert report.brave_quota_exhausted is True
        assert report.ddg_queries == 1

    async def test_unexpected_brave_error_switches_to_ddg(self) -> None:
        """An unmapped Brave failure must disable Brave and continue on DDG.

        The 2026-08-21 HTTP 402 escaped this branch entirely and killed the whole
        cross-validation phase, free DDG fallback included. Whatever Brave throws,
        the phase must survive on DDG.
        """
        from scraper.sources.ddg_brave.brave_client import BraveClient
        from scraper.sources.ddg_brave.ddg_client import DdgClient

        pool = _make_pool()
        mock_runs_cls, mock_obs_cls = _patched_repos()

        brave_client = MagicMock(spec=BraveClient)
        brave_client.search = AsyncMock(side_effect=RuntimeError("terminal HTTP 418"))

        ddg_client = MagicMock(spec=DdgClient)
        ddg_client.search = AsyncMock(return_value=[])

        with (
            patch("scraper.sources.ddg_brave.ingester.RunsRepo", mock_runs_cls),
            patch("scraper.sources.ddg_brave.ingester.ObservationsRepo", mock_obs_cls),
            patch("scraper.sources.ddg_brave.ingester.parse_ddg", return_value=[]),
            patch("scraper.sources.ddg_brave.ingester.query_to_observations", return_value=[]),
        ):
            report = await validate_companies(
                [
                    ("0403019261", "Delhaize", "Brussel"),
                    ("0417497106", "Colruyt", "Halle"),
                ],
                pool,
                MagicMock(),
                brave_client=brave_client,
                ddg_client=ddg_client,
                skip_recent_hours=0,
            )

        assert brave_client.search.await_count == 1  # disabled after the first failure
        assert report.ddg_queries == 2
        assert any("terminal HTTP 418" in e for e in report.errors)

    async def test_brave_auth_error_stops_brave_usage(self) -> None:
        from scraper.sources.ddg_brave.brave_client import BraveAuthError, BraveClient

        pool = _make_pool()
        mock_runs_cls, mock_obs_cls = _patched_repos()

        brave_client = MagicMock(spec=BraveClient)
        brave_client.search = AsyncMock(
            side_effect=BraveAuthError(401, "https://brave/", "invalid key")
        )

        with (
            patch("scraper.sources.ddg_brave.ingester.RunsRepo", mock_runs_cls),
            patch("scraper.sources.ddg_brave.ingester.ObservationsRepo", mock_obs_cls),
        ):
            report = await validate_companies(
                [("0403019261", "Delhaize", "Brussel")],
                pool,
                MagicMock(),
                brave_client=brave_client,
                ddg_client=None,
                skip_recent_hours=0,
                use_ddg_fallback=False,
            )

        assert report.brave_quota_exhausted is True
        assert len(report.errors) == 1

    async def test_ddg_rate_limited_logged_and_skipped(self) -> None:
        from scraper.sources.ddg_brave.ddg_client import DdgClient, DdgRateLimitedError

        pool = _make_pool()
        mock_runs_cls, mock_obs_cls = _patched_repos()

        ddg_client = MagicMock(spec=DdgClient)
        ddg_client.search = AsyncMock(side_effect=DdgRateLimitedError("rate limited"))

        with (
            patch("scraper.sources.ddg_brave.ingester.RunsRepo", mock_runs_cls),
            patch("scraper.sources.ddg_brave.ingester.ObservationsRepo", mock_obs_cls),
        ):
            report = await validate_companies(
                [("0403019261", "Delhaize", "Brussel")],
                pool,
                MagicMock(),
                brave_client=None,
                ddg_client=ddg_client,
                skip_recent_hours=0,
            )

        assert report.queries_processed == 0
        assert len(report.errors) == 1

    async def test_observations_flushed_at_batch_boundary(self) -> None:
        from scraper.db.models import Observation

        pool = _make_pool()
        mock_runs_cls, mock_obs_cls = _patched_repos()
        run_id = uuid.uuid4()
        mock_runs_cls.return_value.start_run = AsyncMock(return_value=run_id)

        from scraper.sources.ddg_brave.ddg_client import DdgClient

        ddg_client = MagicMock(spec=DdgClient)
        ddg_client.search = AsyncMock(return_value=[])

        fake_obs = MagicMock(spec=Observation)
        fake_obs.field = "website"

        with (
            patch("scraper.sources.ddg_brave.ingester.RunsRepo", mock_runs_cls),
            patch("scraper.sources.ddg_brave.ingester.ObservationsRepo", mock_obs_cls),
            patch("scraper.sources.ddg_brave.ingester.parse_ddg", return_value=[MagicMock()]),
            patch("scraper.sources.ddg_brave.ingester.classify", return_value=MagicMock()),
            patch(
                "scraper.sources.ddg_brave.ingester.query_to_observations",
                return_value=[fake_obs],
            ),
        ):
            report = await validate_companies(
                [("0403019261", "Delhaize", "Brussel")],
                pool,
                MagicMock(),
                brave_client=None,
                ddg_client=ddg_client,
                skip_recent_hours=0,
            )

        assert report.queries_processed == 1
        assert report.websites_confirmed == 1
