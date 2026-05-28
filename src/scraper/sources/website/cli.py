"""CLI entry point: be-leads-enrich-website."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path


def cli_main() -> None:
    """be-leads-enrich-website: enrich companies with their own website data."""
    parser = argparse.ArgumentParser(description="Enrich companies by scraping their own websites.")

    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument(
        "--kbos-and-websites",
        metavar="FILE",
        help="TSV file with columns: kbo<TAB>url (one pair per line)",
    )
    source_group.add_argument(
        "--from-db",
        action="store_true",
        help="Read KBOs+websites from companies_current where field='website'",
    )

    parser.add_argument("--limit", type=int, default=None, metavar="N")
    parser.add_argument(
        "--concurrent-companies",
        type=int,
        default=15,
        metavar="N",
        help="Max simultaneous companies in-flight (default: 15)",
    )
    parser.add_argument(
        "--skip-recent-hours",
        type=int,
        default=168,
        metavar="N",
        help="Skip KBOs with website obs within N hours (default: 168 = 7 days; 0 = always)",
    )
    parser.add_argument("--database-url", default=None, help="Postgres DSN")

    args = parser.parse_args()

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
            kbos_and_websites_file=args.kbos_and_websites,
            from_db=args.from_db,
            limit=args.limit,
            concurrent_companies=args.concurrent_companies,
            skip_recent_hours=args.skip_recent_hours,
            database_url=database_url,
        )
    )


async def _run(
    kbos_and_websites_file: str | None,
    from_db: bool,
    limit: int | None,
    concurrent_companies: int,
    skip_recent_hours: int,
    database_url: str,
) -> None:
    from scraper.db.pool import init_pool
    from scraper.lib.data_paths import PER_HOST_TOML
    from scraper.lib.http.client import get_polite_client
    from scraper.lib.http.limiter import load_from_toml
    from scraper.sources.website.ingester import ingest_kbos

    pairs: list[tuple[str, str]] = []

    if kbos_and_websites_file is not None:
        tsv_text = await asyncio.to_thread(Path(kbos_and_websites_file).read_text, encoding="utf-8")
        for line in tsv_text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t", 1)
            if len(parts) == 2:
                pairs.append((parts[0].strip(), parts[1].strip()))

    pool = await init_pool(database_url)
    try:
        if from_db:
            rows = await pool.fetch(
                """
                SELECT kbo_number, value->>'url' AS url
                FROM observations
                WHERE field = 'website' AND value->>'url' IS NOT NULL
                GROUP BY kbo_number, value->>'url'
                ORDER BY kbo_number
                """
            )
            pairs = [(r["kbo_number"], r["url"]) for r in rows]

        if limit is not None:
            pairs = pairs[:limit]

        if not pairs:
            print(json.dumps({"kbos_processed": 0, "observations_inserted": 0}))
            return

        limiter = load_from_toml(PER_HOST_TOML)
        async with get_polite_client(limiter) as polite_client:
            report = await ingest_kbos(
                pairs,
                pool,
                polite_client,
                skip_recent_hours=skip_recent_hours,
                concurrent_companies=concurrent_companies,
            )
    finally:
        await pool.close()

    result = {
        "kbos_processed": report.kbos_processed,
        "pages_fetched": report.pages_fetched,
        "observations_inserted": report.observations_inserted,
        "fetch_failures": report.fetch_failures,
        "duration_s": round(report.duration_s, 2),
    }
    print(json.dumps(result))
