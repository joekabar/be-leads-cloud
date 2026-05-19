"""be-leads-kbo-stage CLI — stage a KBO Open Data ZIP into kbo_stage_* tables."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path


def cli_main() -> None:
    parser = argparse.ArgumentParser(
        description="Stage a KBO Open Data ZIP into kbo_stage_* tables (one-time per snapshot)."
    )
    parser.add_argument("zip_path", metavar="ZIP", help="Path to KboOpenData_*_Full.zip")
    parser.add_argument("--database-url", default=None, help="PostgreSQL DSN (env: DATABASE_URL)")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-stage even if this snapshot_date is already present (deletes old rows first)",
    )
    args = parser.parse_args()

    zip_path = Path(args.zip_path)
    if not zip_path.exists():
        print(f"Error: ZIP not found: {zip_path}", file=sys.stderr)
        sys.exit(2)

    from scraper.lib.config import load_settings

    settings = load_settings()
    dsn = args.database_url or settings.database_url

    async def _run() -> None:
        import json as _json

        import asyncpg

        from scraper.sources.kbo_dump.staging import stage_zip

        async def _init_jsonb(conn: asyncpg.Connection) -> None:
            await conn.set_type_codec(
                "jsonb",
                encoder=_json.dumps,
                decoder=_json.loads,
                schema="pg_catalog",
            )

        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=5, init=_init_jsonb)
        if pool is None:
            raise RuntimeError("asyncpg.create_pool returned None")
        try:
            report = await stage_zip(zip_path, pool, force=args.force)
        finally:
            await pool.close()

        result = {
            "snapshot_date": report.snapshot_date.isoformat(),
            "skipped": report.skipped,
            "rows": {
                "enterprise": report.rows_enterprise,
                "address": report.rows_address,
                "denomination": report.rows_denomination,
                "contact": report.rows_contact,
                "activity": report.rows_activity,
            },
            "duration_s": round(report.duration_s, 2),
        }
        print(json.dumps(result, indent=2))
        if report.skipped:
            print(
                f"Snapshot {report.snapshot_date} already staged. Use --force to re-stage.",
                file=sys.stderr,
            )
        else:
            print(
                f"Staged snapshot {report.snapshot_date} in {report.duration_s:.1f}s. "
                "Now run: be-leads-pipeline-batch --city <city> --all-sectors",
                file=sys.stderr,
            )

    try:
        asyncio.run(_run())
    except Exception as exc:
        print(f"Staging error: {exc}", file=sys.stderr)
        sys.exit(1)
