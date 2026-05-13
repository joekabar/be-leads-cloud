"""CLI entry point: be-leads-search-validate."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path


def cli_main() -> None:
    """be-leads-search-validate: cross-validate companies via Brave/DDG."""
    parser = argparse.ArgumentParser(
        description="Cross-validate company data using Brave Search API and/or DuckDuckGo."
    )

    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument(
        "--inputs",
        metavar="FILE",
        help="TSV file: kbo<TAB>name<TAB>city per line",
    )
    source_group.add_argument(
        "--from-db",
        action="store_true",
        help="Pull placeholder KBOs (9-prefix) from companies_current where source=goudengids",
    )

    parser.add_argument("--limit", type=int, default=None, metavar="N")
    parser.add_argument(
        "--engine",
        choices=["brave", "ddg", "auto"],
        default="auto",
        help="Engine to use: brave, ddg, or auto (brave→ddg fallback). Default: auto",
    )
    parser.add_argument(
        "--template",
        choices=["1", "2", "3"],
        default="1",
        help="Query template (default: 1 = name+city)",
    )
    parser.add_argument(
        "--skip-recent-hours",
        type=int,
        default=168,
        metavar="N",
        help="Skip KBOs with search obs within N hours (default: 168 = 7 days; 0 = always)",
    )
    parser.add_argument(
        "--brave-key",
        default=None,
        help="Brave subscription key (default: $BRAVE_SEARCH_API_KEY)",
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

    brave_key = args.brave_key or os.environ.get("BRAVE_SEARCH_API_KEY")

    asyncio.run(
        _run(
            inputs_file=args.inputs,
            from_db=args.from_db,
            limit=args.limit,
            engine=args.engine,
            skip_recent_hours=args.skip_recent_hours,
            brave_key=brave_key,
            database_url=database_url,
        )
    )


async def _run(
    inputs_file: str | None,
    from_db: bool,
    limit: int | None,
    engine: str,
    skip_recent_hours: int,
    brave_key: str | None,
    database_url: str,
) -> None:

    from scraper.db.pool import init_pool
    from scraper.lib.http.client import get_polite_client
    from scraper.lib.http.limiter import load_from_toml
    from scraper.sources.ddg_brave.brave_client import BraveClient
    from scraper.sources.ddg_brave.ddg_client import DdgClient
    from scraper.sources.ddg_brave.ingester import validate_companies

    per_host_toml = (
        Path(__file__).parents[4]
        / ".claude"
        / "skills"
        / "polite-scraping"
        / "references"
        / "per-host.toml"
    )

    inputs: list[tuple[str, str, str]] = []

    if inputs_file is not None:
        text = await asyncio.to_thread(Path(inputs_file).read_text, encoding="utf-8")
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t", 2)
            if len(parts) == 3:
                inputs.append((parts[0].strip(), parts[1].strip(), parts[2].strip()))

    pool = await init_pool(database_url)
    try:
        if from_db:
            rows = await pool.fetch(
                """
                SELECT DISTINCT kbo_number,
                       value->>'text' AS name,
                       value->>'city'  AS city
                FROM observations
                WHERE field = 'name'
                  AND kbo_number LIKE '9%'
                  AND value->>'text' IS NOT NULL
                ORDER BY kbo_number
                """
            )
            inputs = [
                (r["kbo_number"], r["name"] or "", r["city"] or "") for r in rows if r["name"]
            ]

        if limit is not None:
            inputs = inputs[:limit]

        if not inputs:
            print(json.dumps({"queries_processed": 0, "observations_inserted": 0}))
            return

        limiter = load_from_toml(per_host_toml)

        use_brave = engine in ("brave", "auto") and brave_key is not None
        use_ddg = engine in ("ddg", "auto")

        async with get_polite_client(limiter) as polite_client:
            brave = BraveClient(polite_client, brave_key) if use_brave and brave_key else None
            ddg = DdgClient() if use_ddg else None

            report = await validate_companies(
                inputs,
                pool,
                polite_client,
                brave_client=brave,
                ddg_client=ddg,
                skip_recent_hours=skip_recent_hours,
                use_ddg_fallback=use_ddg,
            )
    finally:
        await pool.close()

    result = {
        "queries_processed": report.queries_processed,
        "brave_queries": report.brave_queries,
        "ddg_queries": report.ddg_queries,
        "brave_quota_exhausted": report.brave_quota_exhausted,
        "observations_inserted": report.observations_inserted,
        "websites_confirmed": report.websites_confirmed,
        "duration_s": round(report.duration_s, 2),
    }
    print(json.dumps(result))
