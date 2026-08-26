"""``be-leads-next-city`` — print the city the nightly scrape should work on.

The rotation finishes one city before starting the next, so this prints the first city
in ``scrape_cities.toml`` order that still has a scrapeable sector outstanding, or
nothing at all when every city is complete — letting the caller skip the run.

Sector completion is all-time by default: once scraped, a city+sector stays done until
someone asks for a refresh with ``--within-hours``.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import asyncpg

from scraper.lib.sector_nace import SECTOR_NACE_PREFIXES
from scraper.pipeline.sector_queue import (
    fetch_completed_by_city,
    goudengids_unscrapeable_sectors,
    load_rotation_cities,
    select_next_city,
)


def cli_main() -> None:  # pragma: no cover
    parser = argparse.ArgumentParser(
        description="Print the next city needing a goudengids scrape, or nothing."
    )
    parser.add_argument(
        "--city",
        action="append",
        default=None,
        metavar="SLUG",
        help="Override the configured rotation. Repeatable, order is priority order.",
    )
    parser.add_argument(
        "--within-hours",
        type=int,
        default=None,
        help=(
            "Treat a sector as done only if scraped within this window. Omit for "
            "all-time (refresh only on command)."
        ),
    )
    parser.add_argument("--database-url", default=None)
    args = parser.parse_args()

    from scraper.lib.config import database_url

    dsn = args.database_url or database_url()
    if not dsn:
        print("DATABASE_URL is not set", file=sys.stderr)
        sys.exit(2)

    cities = args.city or load_rotation_cities()
    if not cities:
        print("No cities configured in scrape_cities.toml", file=sys.stderr)
        sys.exit(2)

    all_sectors = sorted(SECTOR_NACE_PREFIXES)
    unscrapeable = goudengids_unscrapeable_sectors(all_sectors)

    async def _run() -> str | None:
        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
        if pool is None:
            raise RuntimeError("asyncpg.create_pool returned None")
        try:
            completed = await fetch_completed_by_city(pool, cities, within_hours=args.within_hours)
        finally:
            await pool.close()
        return select_next_city(cities, all_sectors, completed, unscrapeable=unscrapeable)

    city = asyncio.run(_run())
    if city:
        print(city)
