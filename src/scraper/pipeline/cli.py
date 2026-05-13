"""be-leads-pipeline CLI entry point."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Run the Belgian B2B lead pipeline for a sector x city."
    )
    p.add_argument("--sector", required=True, help="Sector slug (NL or FR, e.g. electriciens)")
    p.add_argument("--city", required=True, help="City name (e.g. antwerpen)")
    p.add_argument("--max-pages", type=int, default=5, metavar="N")
    p.add_argument("--lang", choices=["nl", "fr"], default="nl")
    p.add_argument(
        "--use-fixture",
        action="store_true",
        help="Use synthetic kbo_dump fixture from tests/golden/kbo_dump/synthetic_mini/",
    )
    p.add_argument("--fixture-zip", default=None, metavar="PATH", help="Path to a real KBO ZIP")
    p.add_argument("--skip-kbo-dump", action="store_true")
    p.add_argument("--skip-goudengids", action="store_true")
    p.add_argument("--skip-kbopub", action="store_true")
    p.add_argument("--skip-nbb", action="store_true")
    p.add_argument("--skip-website", action="store_true")
    p.add_argument("--skip-search", action="store_true")
    p.add_argument("--database-url", default=None)
    p.add_argument(
        "--brave-key",
        default=None,
        help="Brave Search API key (env: BRAVE_SEARCH_API_KEY)",
    )
    p.add_argument(
        "--nbb-key",
        default=None,
        help="NBB CBSO subscription key (env: NBB_CBSO_API_KEY)",
    )
    return p


def cli_main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    from scraper.pipeline.orchestrator import PipelineConfig, resolve_sector_slugs

    try:
        nl_slug, _ = resolve_sector_slugs(args.sector)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(2)

    brave_key = args.brave_key or os.environ.get("BRAVE_SEARCH_API_KEY")
    nbb_key = args.nbb_key or os.environ.get("NBB_CBSO_API_KEY")

    config = PipelineConfig(
        sector=args.sector,
        city=args.city,
        sector_slug=nl_slug,
        max_pages=args.max_pages,
        lang=args.lang,
        use_fixture=args.use_fixture,
        fixture_zip_path=Path(args.fixture_zip) if args.fixture_zip else None,
        do_kbo_dump=not args.skip_kbo_dump,
        do_goudengids=not args.skip_goudengids,
        do_kbopub=not args.skip_kbopub,
        do_nbb=not args.skip_nbb,
        do_website=not args.skip_website,
        do_search=not args.skip_search,
        nbb_subscription_key=nbb_key,
        brave_subscription_key=brave_key,
        database_url=args.database_url,
    )

    from scraper.pipeline.run import run

    try:
        report = asyncio.run(run(config))
    except Exception as exc:
        print(f"Pipeline error: {exc}", file=sys.stderr)
        sys.exit(1)

    result = {
        "sector": report.sector,
        "city": report.city,
        "sources_run": report.sources_run,
        "sources_skipped": report.sources_skipped,
        "sources_failed": report.sources_failed,
        "observations_inserted_per_source": report.observations_inserted_per_source,
        "placeholders_created": report.placeholders_created,
        "placeholders_resolved": report.placeholders_resolved,
        "companies_in_view": report.companies_in_view,
        "duration_s": round(report.duration_s, 2),
    }

    print(json.dumps(result))

    summary_lines = [
        f"sector={report.sector} city={report.city}",
        f"sources_run={report.sources_run}",
        f"companies_in_view={report.companies_in_view}",
        f"duration_s={round(report.duration_s, 2)}",
    ]
    if report.sources_failed:
        summary_lines.append(f"FAILED: {list(report.sources_failed.keys())}")
    print("\n".join(summary_lines), file=sys.stderr)
