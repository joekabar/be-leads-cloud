"""Tests for ui/batch_runner.py — pool/PoliteClient wiring around run_batch."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from scraper.ui.batch_runner import run_batch_job


async def test_run_batch_job_wires_pool_and_returns_report() -> None:
    sentinel_report = MagicMock(name="BatchReport")
    pool = MagicMock()
    pool.close = AsyncMock()

    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("asyncpg.create_pool", new=AsyncMock(return_value=pool)),
        patch("httpx.AsyncClient", return_value=fake_client),
        patch("scraper.lib.http.limiter.load_from_toml", return_value=MagicMock()),
        patch(
            "scraper.pipeline.batch.run_batch",
            new=AsyncMock(return_value=sentinel_report),
        ) as mock_run_batch,
    ):
        config = MagicMock(name="BatchConfig")
        result = await run_batch_job("postgresql://x/y", config)

    assert result is sentinel_report
    # config is passed through as the first positional arg to run_batch
    assert mock_run_batch.await_args.args[0] is config
    pool.close.assert_awaited_once()


async def test_run_batch_job_raises_when_pool_is_none() -> None:
    with (
        patch("asyncpg.create_pool", new=AsyncMock(return_value=None)),
        patch("scraper.lib.http.limiter.load_from_toml", return_value=MagicMock()),
    ):
        try:
            await run_batch_job("postgresql://x/y", MagicMock())
        except RuntimeError as exc:
            assert "create_pool returned None" in str(exc)
        else:  # pragma: no cover - failure path
            raise AssertionError("expected RuntimeError when pool is None")
