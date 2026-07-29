"""Unit tests for pipeline/run.py — covers the pool-init + PoliteClient setup path."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_http_cm() -> MagicMock:
    """Return a mock for `async with httpx.AsyncClient(...) as client:`."""
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=MagicMock())
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _make_pool() -> AsyncMock:
    pool = AsyncMock()
    pool.close = AsyncMock()
    return pool


def _make_config(database_url: str | None = "postgresql://localhost/leads_test"):
    from scraper.pipeline.orchestrator import PipelineConfig

    return PipelineConfig(
        sector="elektriciens",
        city="antwerpen",
        sector_slug="elektriciens",
        database_url=database_url,
    )


class TestRun:
    async def test_run_returns_pipeline_report(self) -> None:
        from scraper.pipeline.orchestrator import PipelineReport
        from scraper.pipeline.run import run

        mock_report = MagicMock(spec=PipelineReport)
        mock_pool = _make_pool()

        with (
            patch("scraper.pipeline.run.init_pool", new=AsyncMock(return_value=mock_pool)),
            patch("scraper.pipeline.run.load_from_toml", return_value=MagicMock()),
            patch("scraper.pipeline.run.run_pipeline", new=AsyncMock(return_value=mock_report)),
            patch("scraper.pipeline.run.httpx.AsyncClient", return_value=_make_http_cm()),
            patch("scraper.pipeline.run.PoliteClient", return_value=MagicMock()),
        ):
            result = await run(_make_config())

        assert result is mock_report
        mock_pool.close.assert_called_once()

    async def test_run_uses_config_database_url_directly(self) -> None:
        from scraper.pipeline.run import run

        mock_pool = _make_pool()

        with (
            patch(
                "scraper.pipeline.run.init_pool", new=AsyncMock(return_value=mock_pool)
            ) as mock_init,
            patch("scraper.pipeline.run.load_from_toml", return_value=MagicMock()),
            patch("scraper.pipeline.run.run_pipeline", new=AsyncMock(return_value=MagicMock())),
            patch("scraper.pipeline.run.httpx.AsyncClient", return_value=_make_http_cm()),
            patch("scraper.pipeline.run.PoliteClient", return_value=MagicMock()),
        ):
            await run(_make_config("postgresql://direct/url"))

        mock_init.assert_called_once_with("postgresql://direct/url")

    async def test_run_loads_settings_when_database_url_none(self) -> None:
        from scraper.pipeline.run import run

        mock_pool = _make_pool()
        mock_settings = MagicMock()
        mock_settings.database_url = "postgresql://from_settings/leads"

        with (
            patch("scraper.pipeline.run.init_pool", new=AsyncMock(return_value=mock_pool)),
            patch("scraper.pipeline.run.load_from_toml", return_value=MagicMock()),
            patch("scraper.pipeline.run.run_pipeline", new=AsyncMock(return_value=MagicMock())),
            patch("scraper.pipeline.run.httpx.AsyncClient", return_value=_make_http_cm()),
            patch("scraper.pipeline.run.PoliteClient", return_value=MagicMock()),
            patch("scraper.lib.config.load_settings", return_value=mock_settings),
        ):
            await run(_make_config(None))

        mock_pool.close.assert_called_once()

    async def test_run_closes_pool_on_exception(self) -> None:
        from scraper.pipeline.run import run

        mock_pool = _make_pool()

        with (
            patch("scraper.pipeline.run.init_pool", new=AsyncMock(return_value=mock_pool)),
            patch("scraper.pipeline.run.load_from_toml", return_value=MagicMock()),
            patch(
                "scraper.pipeline.run.run_pipeline",
                new=AsyncMock(side_effect=RuntimeError("boom")),
            ),
            patch("scraper.pipeline.run.httpx.AsyncClient", return_value=_make_http_cm()),
            patch("scraper.pipeline.run.PoliteClient", return_value=MagicMock()),
            pytest.raises(RuntimeError, match="boom"),
        ):
            await run(_make_config())

        mock_pool.close.assert_called_once()
