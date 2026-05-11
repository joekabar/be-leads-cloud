from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from stdnum.be import vat as be_vat


def cli_validate() -> None:
    """be-leads-validate-kbo: validate a KBO enterprise number."""
    parser = argparse.ArgumentParser(description="Validate a KBO enterprise number")
    parser.add_argument("number", help="KBO number (dots/spaces/BE prefix accepted)")
    args = parser.parse_args()

    if be_vat.is_valid(args.number):
        print(f"valid: {be_vat.compact(args.number)}")
    else:
        print(f"invalid: {args.number!r}", file=sys.stderr)
        sys.exit(2)


def cli_main() -> None:
    """be-leads-ingest-kbo: ingest a KBO Open Data ZIP into Postgres."""
    parser = argparse.ArgumentParser(description="Ingest a KBO Open Data ZIP")
    parser.add_argument("--zip", required=True, help="Path to the KBO Open Data ZIP file")
    parser.add_argument(
        "--database-url",
        default=None,
        help="Postgres DSN (defaults to DATABASE_URL env var)",
    )
    parser.add_argument(
        "--no-refresh",
        action="store_true",
        help="Skip the companies_current materialised view refresh after ingest",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=5000,
        help="Observation batch size for bulk inserts (default: 5000)",
    )
    args = parser.parse_args()

    zip_path = Path(args.zip)
    if not zip_path.exists():
        print(f"Error: ZIP not found: {zip_path}", file=sys.stderr)
        sys.exit(1)

    # Resolve database URL
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
            zip_path=zip_path,
            database_url=database_url,
            refresh_view=not args.no_refresh,
            batch_size=args.batch_size,
        )
    )


async def _run(
    zip_path: Path,
    database_url: str,
    refresh_view: bool,
    batch_size: int,
) -> None:

    import json as _json

    from scraper.db.pool import init_pool
    from scraper.sources.kbo_dump.ingester import ingest_zip

    pool = await init_pool(database_url)
    try:
        report = await ingest_zip(
            zip_path,
            pool,
            batch_size=batch_size,
            refresh_view=refresh_view,
        )
    finally:
        await pool.close()

    result = {
        "extract_type": report.extract_type,
        "snapshot_date": report.snapshot_date.isoformat(),
        "enterprises_processed": report.enterprises_processed,
        "observations_inserted": report.observations_inserted,
        "phones_invalid_skipped": report.phones_invalid_skipped,
        "duration_s": round(report.duration_s, 2),
    }
    print(_json.dumps(result))
