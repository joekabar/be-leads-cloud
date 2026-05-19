"""be-leads-cleanup-stage CLI — delete old KBO staging snapshots, keep the N most recent."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys


def cli_main() -> None:
    parser = argparse.ArgumentParser(
        description="Delete old kbo_stage_* snapshots, keeping the N most recent."
    )
    parser.add_argument(
        "--keep",
        type=int,
        default=3,
        metavar="N",
        help="Number of most-recent snapshots to keep (default: 3)",
    )
    parser.add_argument("--database-url", default=None, help="PostgreSQL DSN (env: DATABASE_URL)")
    args = parser.parse_args()

    if args.keep < 1:
        print("Error: --keep must be >= 1", file=sys.stderr)
        sys.exit(2)

    from scraper.lib.config import load_settings

    settings = load_settings()
    dsn = args.database_url or settings.database_url

    async def _run() -> None:
        import json as _json

        import asyncpg

        from scraper.sources.kbo_dump.staging import cleanup_old_snapshots

        async def _init_jsonb(conn: asyncpg.Connection) -> None:
            await conn.set_type_codec(
                "jsonb",
                encoder=_json.dumps,
                decoder=_json.loads,
                schema="pg_catalog",
            )

        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2, init=_init_jsonb)
        if pool is None:
            raise RuntimeError("asyncpg.create_pool returned None")
        try:
            deleted = await cleanup_old_snapshots(pool, keep_n=args.keep)
        finally:
            await pool.close()

        total = sum(deleted.values())
        print(json.dumps({"deleted_per_table": deleted, "total_rows_deleted": total}, indent=2))
        if total == 0:
            print(
                f"Nothing to delete — fewer than {args.keep} snapshots present.",
                file=sys.stderr,
            )
        else:
            print(f"Deleted {total} rows across {len(deleted)} tables.", file=sys.stderr)

    try:
        asyncio.run(_run())
    except Exception as exc:
        print(f"Cleanup error: {exc}", file=sys.stderr)
        sys.exit(1)
