from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path


def cli_main() -> None:
    """be-leads-fetch-kbopub: fetch kbopub function holders for a list of KBO numbers."""
    parser = argparse.ArgumentParser(
        description="Fetch kbopub function holders for one or more KBO numbers."
    )
    parser.add_argument(
        "--kbos",
        required=True,
        help="Comma-separated KBO list or @file.txt (one KBO per line)",
    )
    parser.add_argument("--lang", choices=["nl", "fr"], default="nl", help="Page language")
    parser.add_argument(
        "--skip-recent-hours",
        type=int,
        default=24,
        metavar="N",
        help="Skip KBOs already fetched within N hours (default: 24; 0 = always fetch)",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Postgres DSN (defaults to DATABASE_URL env var)",
    )
    args = parser.parse_args()

    # Parse KBO list from --kbos argument.
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

    # Resolve database URL.
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
            lang=args.lang,
            skip_recent_hours=args.skip_recent_hours,
        )
    )


async def _run(
    kbos: list[str],
    database_url: str,
    lang: str,
    skip_recent_hours: int,
) -> None:

    from scraper.db.pool import init_pool
    from scraper.lib.http.limiter import load_from_toml
    from scraper.sources.kbopub_html.ingester import ingest_kbos

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
        report = await ingest_kbos(
            kbos,
            pool,
            limiter,
            lang=lang,  # type: ignore[arg-type]
            skip_recent_hours=skip_recent_hours,
        )
    finally:
        await pool.close()

    result = {
        "kbos_processed": report.kbos_processed,
        "kbos_not_found": report.kbos_not_found,
        "kbos_invalid": report.kbos_invalid,
        "function_holders_total": report.function_holders_total,
        "observations_inserted": report.observations_inserted,
        "duration_s": round(report.duration_s, 2),
    }
    print(json.dumps(result))
