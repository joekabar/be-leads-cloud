from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path


def cli_main() -> None:
    """be-leads-fetch-nbb: fetch NBB CBSO financial data for one or more KBO numbers."""
    parser = argparse.ArgumentParser(
        description="Fetch NBB CBSO annual financial data for one or more KBO numbers."
    )
    parser.add_argument(
        "--kbos",
        required=True,
        help="Comma-separated KBO list or @file.txt (one KBO per line)",
    )
    parser.add_argument(
        "--years-back",
        type=int,
        default=None,
        metavar="N",
        help="Only emit observations for exercise_year >= current_year - N",
    )
    parser.add_argument(
        "--skip-recent-hours",
        type=int,
        default=24,
        metavar="N",
        help="Skip KBOs with a recent nbb_authentic observation (default: 24; 0 = always fetch)",
    )
    parser.add_argument(
        "--subscription-key",
        default=None,
        help="NBB CBSO subscription key (or env NBB_CBSO_API_KEY)",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Postgres DSN (defaults to DATABASE_URL env var)",
    )
    args = parser.parse_args()

    if args.kbos.startswith("@"):
        filepath = Path(args.kbos[1:])
        if not filepath.exists():
            print(f"Error: file not found: {filepath}", file=sys.stderr)
            sys.exit(2)
        kbos = [line.strip() for line in filepath.read_text().splitlines() if line.strip()]
    else:
        kbos = [k.strip() for k in args.kbos.split(",") if k.strip()]

    if not kbos:
        print("Error: no KBO numbers provided", file=sys.stderr)
        sys.exit(2)

    subscription_key = args.subscription_key or os.environ.get("NBB_CBSO_API_KEY", "")
    if not subscription_key:
        print(
            "Error: NBB CBSO subscription key required"
            " (--subscription-key or NBB_CBSO_API_KEY env)",
            file=sys.stderr,
        )
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
            kbos=kbos,
            database_url=database_url,
            subscription_key=subscription_key,
            skip_recent_hours=args.skip_recent_hours,
            years_back=args.years_back,
        )
    )


async def _run(
    kbos: list[str],
    database_url: str,
    subscription_key: str,
    skip_recent_hours: int,
    years_back: int | None,
) -> None:
    from scraper.db.pool import init_pool
    from scraper.lib.http.client import get_polite_client
    from scraper.lib.http.limiter import load_from_toml
    from scraper.sources.nbb_authentic.client import NbbClient
    from scraper.sources.nbb_authentic.ingester import ingest_kbos

    # parents[4] == project root (be-leads/): cli.py lives 5 levels deep.
    per_host_toml = (
        Path(__file__).parents[4]
        / ".claude"
        / "skills"
        / "polite-scraping"
        / "references"
        / "per-host.toml"
    )

    pool = await init_pool(database_url)
    try:
        limiter = load_from_toml(per_host_toml)
        async with get_polite_client(limiter) as polite_client:
            nbb_client = NbbClient(
                polite_client=polite_client,
                subscription_key=subscription_key,
            )
            report = await ingest_kbos(
                kbos,
                pool,
                nbb_client,
                skip_recent_hours=skip_recent_hours,
                years_back=years_back,
            )
    finally:
        await pool.close()

    result = {
        "kbos_processed": report.kbos_processed,
        "kbos_not_found": report.kbos_not_found,
        "references_total": report.references_total,
        "observations_inserted": report.observations_inserted,
        "duration_s": round(report.duration_s, 2),
    }
    print(json.dumps(result))
