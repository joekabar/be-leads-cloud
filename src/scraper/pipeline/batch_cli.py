"""be-leads-pipeline-batch CLI entry point."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import date
from pathlib import Path


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Run the batch pipeline for city x sectors using staged KBO data."
    )
    p.add_argument("--city", required=True, help="City slug (e.g. antwerpen)")
    p.add_argument(
        "--sector",
        action="append",
        dest="sectors",
        default=[],
        metavar="SLUG",
        help="Sector slug (repeatable). Ignored when --all-sectors is set.",
    )
    p.add_argument(
        "--all-sectors",
        action="store_true",
        help="Run all sectors defined in _SECTOR_NACE_PREFIXES.",
    )
    p.add_argument(
        "--snapshot-date",
        default=None,
        metavar="YYYY-MM-DD",
        help="KBO snapshot date to use (default: latest staged date).",
    )
    p.add_argument("--lang", choices=["nl", "fr"], default="nl")
    p.add_argument("--max-pages", type=int, default=25, metavar="N")
    p.add_argument("--database-url", default=None)
    p.add_argument("--brave-key", default=None, help="env: BRAVE_SEARCH_API_KEY")
    p.add_argument("--nbb-key", default=None, help="env: NBB_CBSO_API_KEY")
    p.add_argument("--skip-kbo-dump", action="store_true")
    p.add_argument("--skip-goudengids", action="store_true")
    p.add_argument("--skip-kbopub", action="store_true")
    p.add_argument("--skip-nbb", action="store_true")
    p.add_argument("--skip-website", action="store_true")
    p.add_argument("--skip-search", action="store_true")
    p.add_argument(
        "--export-dir",
        default=None,
        metavar="PATH",
        help="Directory for post-batch CSV export (5000 rows per file by default).",
    )
    p.add_argument(
        "--export-chunk-size",
        type=int,
        default=5000,
        metavar="N",
        help="Rows per chunk CSV file (default: 5000). Used with --export-dir.",
    )
    p.add_argument(
        "--goudengids-skip-recent-hours",
        type=int,
        default=720,
        metavar="H",
        help="Skip goudengids sectors scraped within this many hours (default: 720 = 30 days).",
    )
    p.add_argument(
        "--ddg-brave-skip-recent-hours",
        type=int,
        default=168,
        metavar="H",
        help="Skip ddg/brave for KBOs validated within this many hours (default: 168 = 7 days).",
    )
    return p


def cli_main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    from scraper.pipeline.orchestrator import _SECTOR_NACE_PREFIXES

    if args.all_sectors:
        sectors = list(_SECTOR_NACE_PREFIXES.keys())
    elif args.sectors:
        unknown = [s for s in args.sectors if s not in _SECTOR_NACE_PREFIXES]
        if unknown:
            print(
                f"Error: unknown sector slug(s): {unknown}. "
                f"Valid slugs: {sorted(_SECTOR_NACE_PREFIXES)}",
                file=sys.stderr,
            )
            sys.exit(2)
        sectors = list(args.sectors)
    else:
        print("Error: supply --sector SLUG or --all-sectors", file=sys.stderr)
        sys.exit(2)

    snapshot_date: date | None = None
    if args.snapshot_date:
        try:
            snapshot_date = date.fromisoformat(args.snapshot_date)
        except ValueError:
            print(f"Error: invalid --snapshot-date {args.snapshot_date!r}", file=sys.stderr)
            sys.exit(2)

    brave_key = args.brave_key or os.environ.get("BRAVE_SEARCH_API_KEY")
    nbb_key = args.nbb_key or os.environ.get("NBB_CBSO_API_KEY")

    from scraper.lib.config import load_settings

    settings = load_settings()
    dsn = args.database_url or settings.database_url

    async def _run() -> None:
        import json as _json

        import asyncpg
        import httpx

        from scraper.lib.http.client import PoliteClient
        from scraper.lib.http.limiter import load_from_toml
        from scraper.pipeline.batch import BatchConfig, run_batch

        _per_host_toml = (
            Path(__file__).parents[3]
            / ".claude"
            / "skills"
            / "polite-scraping"
            / "references"
            / "per-host.toml"
        )

        async def _init_jsonb(conn: asyncpg.Connection) -> None:
            await conn.set_type_codec(
                "jsonb",
                encoder=_json.dumps,
                decoder=_json.loads,
                schema="pg_catalog",
            )

        pool = await asyncpg.create_pool(dsn, min_size=2, max_size=10, init=_init_jsonb)
        if pool is None:
            raise RuntimeError("asyncpg.create_pool returned None")

        limiter = load_from_toml(_per_host_toml)
        config = BatchConfig(
            city=args.city,
            sectors=sectors,
            snapshot_date=snapshot_date,
            lang=args.lang,
            max_pages=args.max_pages,
            nbb_subscription_key=nbb_key,
            brave_subscription_key=brave_key,
            do_kbo_dump=not args.skip_kbo_dump,
            do_goudengids=not args.skip_goudengids,
            do_kbopub=not args.skip_kbopub,
            do_nbb=not args.skip_nbb,
            do_website=not args.skip_website,
            do_search=not args.skip_search,
            export_dir=Path(args.export_dir) if args.export_dir else None,
            export_chunk_size=args.export_chunk_size,
            goudengids_skip_recent_hours=args.goudengids_skip_recent_hours,
            ddg_brave_skip_recent_hours=args.ddg_brave_skip_recent_hours,
        )
        try:
            async with httpx.AsyncClient(follow_redirects=True) as http_client:
                polite_client = PoliteClient(inner=http_client, limiter=limiter)
                report = await run_batch(config, pool, polite_client)
        finally:
            await pool.close()

        result = {
            "city": report.city,
            "sectors": len(report.sectors),
            "snapshot_date": report.snapshot_date.isoformat() if report.snapshot_date else None,
            "phase_a_kbos": report.phase_a_kbos,
            "goudengids_sectors_scraped": sum(
                1 for v in report.goudengids_per_sector.values() if v > 0
            ),
            "placeholders_resolved": report.placeholders_resolved,
            "companies_in_view": report.companies_in_view,
            "prospect_scores_computed": report.prospect_scores_computed,
            "sources_run": report.sources_run,
            "sources_failed": report.sources_failed,
            "export_files": [str(p) for p in report.export_files],
            "duration_s": round(report.duration_s, 2),
        }
        print(json.dumps(result, indent=2))
        print(
            f"city={report.city} sectors={len(report.sectors)} "
            f"kbos={report.phase_a_kbos} companies={report.companies_in_view} "
            f"duration_s={round(report.duration_s, 2)}",
            file=sys.stderr,
        )
        if report.sources_failed:
            print(f"FAILED sources: {list(report.sources_failed.keys())}", file=sys.stderr)

    try:
        asyncio.run(_run())
    except RuntimeError as exc:
        # Friendly message when staging data is missing.
        msg = str(exc)
        if "be-leads-kbo-stage" in msg or "No staged KBO data" in msg:
            print(f"Error: {msg}", file=sys.stderr)
        else:
            print(f"Batch error: {msg}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"Batch error: {exc}", file=sys.stderr)
        sys.exit(1)
