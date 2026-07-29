"""Unit tests for kbopub_html/ingester.py — no real network or DB needed."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scraper.lib.errors import BlockedError, KboNotFoundError
from scraper.sources.kbopub_html.ingester import _is_fresh, ingest_kbos


def _make_pool() -> AsyncMock:
    pool = AsyncMock()
    pool.execute.return_value = None
    pool.fetch.return_value = []
    pool.fetchrow.return_value = None

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


def _make_limiter() -> MagicMock:
    limiter = MagicMock()
    return limiter


# ── _is_fresh ─────────────────────────────────────────────────────────────────


class TestIsFresh:
    async def test_always_false_when_skip_hours_zero(self) -> None:
        pool = _make_pool()
        result = await _is_fresh(pool, "0403019261", skip_recent_hours=0)
        assert result is False
        pool.fetchrow.assert_not_called()

    async def test_true_when_recent_observation_exists(self) -> None:
        pool = _make_pool()
        pool.fetchrow.return_value = {"1": 1}
        result = await _is_fresh(pool, "0403019261", skip_recent_hours=24)
        assert result is True

    async def test_false_when_no_recent_observation(self) -> None:
        pool = _make_pool()
        pool.fetchrow.return_value = None
        result = await _is_fresh(pool, "0403019261", skip_recent_hours=24)
        assert result is False


# ── ingest_kbos ───────────────────────────────────────────────────────────────


class TestIngestKbos:
    async def test_empty_list_returns_zero_report(self) -> None:
        pool = _make_pool()
        limiter = _make_limiter()
        with patch("scraper.sources.kbopub_html.ingester.get_polite_client") as mock_client_ctx:
            client = AsyncMock()
            mock_client_ctx.return_value.__aenter__ = AsyncMock(return_value=client)
            mock_client_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            report = await ingest_kbos([], pool, limiter)
        assert report.kbos_processed == 0
        assert report.observations_inserted == 0

    async def test_invalid_kbo_counted_and_skipped(self) -> None:
        pool = _make_pool()
        limiter = _make_limiter()
        with patch("scraper.sources.kbopub_html.ingester.get_polite_client") as mock_client_ctx:
            client = AsyncMock()
            mock_client_ctx.return_value.__aenter__ = AsyncMock(return_value=client)
            mock_client_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            report = await ingest_kbos(["0000000000"], pool, limiter)
        assert report.kbos_invalid == 1
        assert report.kbos_processed == 0

    async def test_fresh_kbo_skipped(self) -> None:
        pool = _make_pool()
        pool.fetchrow.return_value = {"1": 1}  # is_fresh → True
        limiter = _make_limiter()
        with patch("scraper.sources.kbopub_html.ingester.get_polite_client") as mock_client_ctx:
            client = AsyncMock()
            mock_client_ctx.return_value.__aenter__ = AsyncMock(return_value=client)
            mock_client_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            # 0403019261 is a valid KBO (Colruyt)
            report = await ingest_kbos(["0403019261"], pool, limiter, skip_recent_hours=24)
        assert report.kbos_processed == 0
        assert report.kbos_not_found == 0

    async def test_kbo_not_found_counted_and_skipped(self) -> None:
        pool = _make_pool()
        pool.fetchrow.return_value = None  # not fresh
        limiter = _make_limiter()
        with (
            patch("scraper.sources.kbopub_html.ingester.get_polite_client") as mock_client_ctx,
            patch(
                "scraper.sources.kbopub_html.ingester.fetch_detail_page",
                side_effect=KboNotFoundError("0403019261", "https://kbopub.economie.fgov.be/"),
            ),
        ):
            client = AsyncMock()
            mock_client_ctx.return_value.__aenter__ = AsyncMock(return_value=client)
            mock_client_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            report = await ingest_kbos(["0403019261"], pool, limiter, skip_recent_hours=0)
        assert report.kbos_not_found == 1
        assert report.kbos_processed == 0

    async def test_blocked_error_propagates(self) -> None:
        pool = _make_pool()
        pool.fetchrow.return_value = None
        limiter = _make_limiter()
        with (
            patch("scraper.sources.kbopub_html.ingester.get_polite_client") as mock_client_ctx,
            patch(
                "scraper.sources.kbopub_html.ingester.fetch_detail_page",
                side_effect=BlockedError(403, "https://kbopub.economie.fgov.be/", "WAF block"),
            ),
        ):
            client = AsyncMock()
            mock_client_ctx.return_value.__aenter__ = AsyncMock(return_value=client)
            mock_client_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            with pytest.raises(BlockedError):
                await ingest_kbos(["0403019261"], pool, limiter, skip_recent_hours=0)

    async def test_successful_fetch_inserts_observations(self) -> None:
        pool = _make_pool()
        pool.fetchrow.return_value = None  # not fresh
        limiter = _make_limiter()

        from scraper.sources.kbopub_html.parser import FunctionHolderRow

        fake_holders = [
            FunctionHolderRow(
                role="Bestuurder",
                role_canonical="bestuurder",
                name="Jan Janssen",
                is_legal_person=False,
                linked_kbo=None,
                since=None,
                raw_html="<td>Jan Janssen</td>",
            )
        ]

        with (
            patch("scraper.sources.kbopub_html.ingester.get_polite_client") as mock_client_ctx,
            patch(
                "scraper.sources.kbopub_html.ingester.fetch_detail_page",
                return_value="<html>mock</html>",
            ),
            patch(
                "scraper.sources.kbopub_html.ingester.parse_function_holders",
                return_value=fake_holders,
            ),
        ):
            client = AsyncMock()
            mock_client_ctx.return_value.__aenter__ = AsyncMock(return_value=client)
            mock_client_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            report = await ingest_kbos(["0403019261"], pool, limiter, skip_recent_hours=0)

        assert report.kbos_processed == 1
        assert report.function_holders_total == 1
        assert report.observations_inserted == 1
