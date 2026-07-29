"""CLI entry point: be-leads-discover-goudengids."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys


def cli_main() -> None:
    """be-leads-discover-goudengids: discover companies via goudengids.be / pagesdor.be."""
    from scraper.sources.goudengids.ingester import load_valid_sectors

    valid_sectors = load_valid_sectors()

    parser = argparse.ArgumentParser(
        description="Discover companies on goudengids.be or pagesdor.be by sector and city."
    )
    parser.add_argument(
        "--sector",
        required=True,
        help=f"Sector slug. Valid values: {', '.join(sorted(valid_sectors))}",
    )
    parser.add_argument("--city", required=True, help="City name (e.g. Antwerpen)")
    parser.add_argument(
        "--lang",
        default="nl",
        choices=["nl", "fr"],
        help="Language / domain: nl=goudengids.be, fr=pagesdor.be (default: nl)",
    )
    parser.add_argument("--max-pages", type=int, default=25, metavar="N")
    parser.add_argument(
        "--skip-recent-hours",
        type=int,
        default=24,
        metavar="N",
        help="Skip cards already ingested within N hours (default: 24; 0 = always fetch)",
    )
    parser.add_argument("--database-url", default=None, help="Postgres DSN")
    args = parser.parse_args()

    if args.sector not in valid_sectors:
        print(
            f"Error: unknown sector {args.sector!r}.\nValid sector slugs:",
            file=sys.stderr,
        )
        for slug in sorted(valid_sectors):
            print(f"  {slug}", file=sys.stderr)
        sys.exit(2)

    database_url = args.database_url
    if not database_url:
        from scraper.lib.config import load_settings

        try:
            settings = load_settings()
            database_url = settings.database_url
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)

    asyncio.run(
        _run(
            sector_slug=args.sector,
            city_slug=args.city,
            lang=args.lang,
            max_pages=args.max_pages,
            skip_recent_hours=args.skip_recent_hours,
            database_url=database_url,
        )
    )


async def _run(
    sector_slug: str,
    city_slug: str,
    lang: str,
    max_pages: int,
    skip_recent_hours: int,
    database_url: str,
) -> None:
    from scraper.db.pool import init_pool
    from scraper.lib.data_paths import PER_HOST_TOML
    from scraper.lib.http.limiter import load_from_toml
    from scraper.sources.goudengids.fetcher import BrowserListingFetcher
    from scraper.sources.goudengids.ingester import ingest_sector_city

    domain = "pagesdor.be" if lang == "fr" else "goudengids.be"

    pool = await init_pool(database_url)
    try:
        limiter = load_from_toml(PER_HOST_TOML)
        fetcher = BrowserListingFetcher(limiter, domain=domain)
        report = await ingest_sector_city(
            sector_slug=sector_slug,
            city_slug=city_slug,
            pool=pool,
            fetcher=fetcher,
            max_pages=max_pages,
            lang=lang,  # type: ignore[arg-type]
            skip_recent_hours=skip_recent_hours,
        )
    finally:
        await pool.close()

    result = {
        "sector": report.sector,
        "city": report.city,
        "pages_scanned": report.pages_scanned,
        "cards_found": report.cards_found,
        "cards_out_of_city": report.cards_out_of_city,
        "cards_with_phone": report.cards_with_phone,
        "cards_with_website": report.cards_with_website,
        "observations_inserted": report.observations_inserted,
        "placeholders_created": report.placeholders_created,
        "duration_s": round(report.duration_s, 2),
    }
    print(json.dumps(result))
