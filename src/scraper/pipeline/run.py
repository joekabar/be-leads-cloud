"""Top-level entry: initialise pool + PoliteClient, run orchestrator."""

from __future__ import annotations

from pathlib import Path

import httpx

from scraper.db.pool import init_pool
from scraper.lib.http.client import PoliteClient
from scraper.lib.http.limiter import load_from_toml
from scraper.pipeline.orchestrator import PipelineConfig, PipelineReport, run_pipeline

_PER_HOST_TOML = (
    Path(__file__).parents[3]
    / ".claude"
    / "skills"
    / "polite-scraping"
    / "references"
    / "per-host.toml"
)


async def run(config: PipelineConfig) -> PipelineReport:
    """Initialise pool, polite_client, all source clients, then run orchestrator + consolidate."""
    from scraper.lib.config import load_settings

    database_url = config.database_url
    if not database_url:
        settings = load_settings()
        database_url = settings.database_url

    pool = await init_pool(database_url)
    limiter = load_from_toml(_PER_HOST_TOML)

    try:
        async with httpx.AsyncClient(follow_redirects=True) as http_client:
            polite_client = PoliteClient(inner=http_client, limiter=limiter)
            return await run_pipeline(config, pool, polite_client)
    finally:
        await pool.close()
