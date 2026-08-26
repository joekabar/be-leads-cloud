"""``be-leads-next-sectors`` — print the next slice of sectors to scrape for a city.

Drives the nightly chunked scrape: the scheduler asks which sectors still need work,
then passes them to ``be-leads-pipeline-batch``. Prints one slug per line, or nothing at
all when the city is fully covered, so the caller can skip the run.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import asyncpg

from scraper.lib.sector_nace import SECTOR_NACE_PREFIXES
from scraper.pipeline.sector_queue import (
    fetch_completed_sectors,
    goudengids_unscrapeable_sectors,
    select_pending_sectors,
)


def cli_main() -> None:  # pragma: no cover
    parser = argparse.ArgumentParser(
        description="Print the next sectors needing a goudengids scrape for a city."
    )
    parser.add_argument("--city", required=True, help="City slug, e.g. oostende")
    parser.add_argument("--limit", type=int, default=15, help="How many sectors to return")
    parser.add_argument(
        "--within-hours",
        type=int,
        default=None,
        help=(
            "Treat a sector as done only if scraped productively within this window. "
            "Omit for all-time: once scraped, a sector stays done until a refresh is "
            "explicitly requested."
        ),
    )
    parser.add_argument(
        "--cycle",
        action="store_true",
        help="When every sector is covered, start the rotation again instead of printing nothing",
    )
    parser.add_argument("--database-url", default=None)
    args = parser.parse_args()

    from scraper.lib.config import database_url

    dsn = args.database_url or database_url()
    if not dsn:
        print("DATABASE_URL is not set", file=sys.stderr)
        sys.exit(2)

    city = args.city.strip().lower()

    async def _run() -> list[str]:
        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
        if pool is None:
            raise RuntimeError("asyncpg.create_pool returned None")
        try:
            done = await fetch_completed_sectors(pool, city, within_hours=args.within_hours)
        finally:
            await pool.close()
        all_sectors = sorted(SECTOR_NACE_PREFIXES)
        return select_pending_sectors(
            all_sectors,
            done=done,
            limit=args.limit,
            cycle=args.cycle,
            unscrapeable=goudengids_unscrapeable_sectors(all_sectors),
        )

    for slug in asyncio.run(_run()):
        print(slug)
