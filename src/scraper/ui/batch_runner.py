"""Async entry that wires a pool + PoliteClient and runs the batch pipeline.

Mirrors ``pipeline/batch_cli.py::_run`` but takes a ready ``BatchConfig`` and a
DSN, so the Streamlit batch page can launch it via
:func:`scraper.ui.background.start_async_job`.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import asyncpg

    from scraper.pipeline.batch import BatchConfig, BatchReport


async def run_batch_job(dsn: str, config: BatchConfig) -> BatchReport:
    """Create a pool + PoliteClient, run the batch, close the pool, return the report."""
    import asyncpg
    import httpx

    from scraper.lib.data_paths import PER_HOST_TOML
    from scraper.lib.http.client import PoliteClient
    from scraper.lib.http.limiter import load_from_toml
    from scraper.pipeline.batch import run_batch

    async def _init_jsonb(conn: asyncpg.Connection) -> None:
        await conn.set_type_codec(
            "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
        )

    pool = await asyncpg.create_pool(dsn, min_size=2, max_size=10, init=_init_jsonb)
    if pool is None:
        raise RuntimeError("asyncpg.create_pool returned None")

    limiter = load_from_toml(PER_HOST_TOML)
    try:
        async with httpx.AsyncClient(follow_redirects=True) as http_client:
            polite_client = PoliteClient(inner=http_client, limiter=limiter)
            return await run_batch(config, pool, polite_client)
    finally:
        await pool.close()
