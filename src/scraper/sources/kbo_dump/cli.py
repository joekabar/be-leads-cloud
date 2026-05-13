from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path

from stdnum.be import vat as be_vat

_MONTH_RE = re.compile(r"_(\d{4})_(\d{2})_(?:Full|Update)\.zip$", re.IGNORECASE)


def _detect_month(zip_path: Path) -> str | None:
    m = _MONTH_RE.search(zip_path.name)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    return None


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
    parser.add_argument(
        "--month",
        dest="month",
        default=None,
        metavar="YYYY-MM",
        help="Snapshot month label (auto-detected from filename if absent)",
    )
    parser.add_argument(
        "--sector-nace",
        dest="sector_nace",
        default=None,
        metavar="CODES",
        help="Comma-separated 2-digit NACE divisions to filter (e.g. '43,46')",
    )
    parser.add_argument(
        "--city",
        dest="city",
        default=None,
        metavar="NAMES",
        help="Comma-separated municipality names to filter (e.g. 'Antwerpen,Brussel')",
    )
    parser.add_argument(
        "--max-enterprises",
        dest="max_enterprises",
        type=int,
        default=None,
        metavar="N",
        help="Stop after N enterprises emitted — for development cycles",
    )
    parser.add_argument(
        "--truncate-first",
        dest="truncate_first",
        action="store_true",
        help="DELETE kbo_dump observations before ingest (see --yes safety rail)",
    )
    parser.add_argument(
        "--yes",
        dest="yes",
        action="store_true",
        help="Confirm --truncate-first when >100k existing kbo_dump rows exist",
    )
    args = parser.parse_args()

    zip_path = Path(args.zip)
    if not zip_path.exists():
        print(f"Error: ZIP not found: {zip_path}", file=sys.stderr)
        sys.exit(1)

    # Resolve month label: flag > filename auto-detect > error
    month_label: str | None = args.month
    if month_label is None:
        month_label = _detect_month(zip_path)
    if month_label is None:
        print(
            "Error: cannot determine snapshot month. "
            "Use --month YYYY-MM or rename the ZIP to match "
            "KboOpenData_N_YYYY_MM_(Full|Update).zip",
            file=sys.stderr,
        )
        sys.exit(1)

    sector_filter = [s.strip() for s in args.sector_nace.split(",")] if args.sector_nace else None
    city_filter = [c.strip() for c in args.city.split(",")] if args.city else None

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

    exit_code = asyncio.run(
        _run(
            zip_path=zip_path,
            database_url=database_url,
            refresh_view=not args.no_refresh,
            batch_size=args.batch_size,
            month_label=month_label,
            sector_filter=sector_filter,
            city_filter=city_filter,
            max_enterprises=args.max_enterprises,
            truncate_first=args.truncate_first,
            yes=args.yes,
        )
    )
    if exit_code:
        sys.exit(exit_code)


async def _run(
    zip_path: Path,
    database_url: str,
    refresh_view: bool,
    batch_size: int,
    month_label: str | None,
    sector_filter: list[str] | None,
    city_filter: list[str] | None,
    max_enterprises: int | None,
    truncate_first: bool,
    yes: bool,
) -> int:
    import json as _json

    from scraper.db.pool import init_pool
    from scraper.sources.kbo_dump.ingester import ingest_zip

    pool = await init_pool(database_url)
    try:
        if truncate_first and not yes:
            async with pool.acquire() as conn:
                existing = await conn.fetchval(
                    "SELECT count(*) FROM observations WHERE source = 'kbo_dump'"
                )
            if existing > 100_000:
                print(
                    f"REFUSE: --truncate-first would delete {existing} rows. "
                    "Re-run with --yes to confirm.",
                    file=sys.stderr,
                )
                return 2

        report = await ingest_zip(
            zip_path,
            pool,
            batch_size=batch_size,
            sector_filter=sector_filter,
            city_filter=city_filter,
            month_label=month_label,
            max_enterprises=max_enterprises,
            truncate_first=truncate_first,
            refresh_view=refresh_view,
        )
    finally:
        await pool.close()

    result = {
        "extract_type": report.extract_type,
        "snapshot_date": report.snapshot_date.isoformat(),
        "month_label": month_label,
        "enterprises_processed": report.enterprises_processed,
        "observations_inserted": report.observations_inserted,
        "phones_invalid_skipped": report.phones_invalid_skipped,
        "duration_s": round(report.duration_s, 2),
    }
    print(_json.dumps(result))
    return 0
