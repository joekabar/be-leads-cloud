from __future__ import annotations

import argparse
import asyncio
import re
from pathlib import Path

import asyncpg

_MIGRATION_RE = re.compile(r"^(\d+)_.*\.sql$")


async def apply_pending(pool: asyncpg.Pool, migrations_dir: Path) -> int:
    """Apply SQL migration files whose version number exceeds the current max.

    Files must match NNN_*.sql. Each file runs in its own transaction together
    with the schema_version INSERT. Returns the new max version (or 0 if none applied).
    """
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_version (
                version    INTEGER     PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        row = await conn.fetchrow("SELECT COALESCE(MAX(version), 0) AS v FROM schema_version")
        current = int(row["v"])

    files = sorted(
        (f for f in migrations_dir.iterdir() if _MIGRATION_RE.match(f.name)),  # noqa: ASYNC240
        key=lambda f: int(_MIGRATION_RE.match(f.name).group(1)),  # type: ignore[union-attr]
    )

    applied = current
    for f in files:
        version = int(_MIGRATION_RE.match(f.name).group(1))  # type: ignore[union-attr]
        if version <= current:
            continue
        sql = f.read_text(encoding="utf-8")
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute(sql)
            await conn.execute(
                "INSERT INTO schema_version (version) VALUES ($1) ON CONFLICT DO NOTHING",
                version,
            )
        applied = version

    return applied


def cli_main() -> None:
    parser = argparse.ArgumentParser(description="Apply be-leads DB migrations.")
    parser.add_argument("--database-url", default=None, help="PostgreSQL DSN")
    parser.add_argument(
        "--migrations-dir",
        default=None,
        help="Directory containing NNN_*.sql files",
    )
    args = parser.parse_args()

    from scraper.lib.config import load_settings

    settings = load_settings()
    dsn = args.database_url or settings.database_url

    migrations_dir = Path(args.migrations_dir) if args.migrations_dir else Path(__file__).parent

    async def _run() -> None:
        import json

        async def _init_jsonb(conn: asyncpg.Connection) -> None:
            await conn.set_type_codec(
                "jsonb",
                encoder=json.dumps,
                decoder=json.loads,
                schema="pg_catalog",
            )

        loop = asyncio.get_running_loop()
        deadline = loop.time() + 30
        delay = 1.0
        pool: asyncpg.Pool | None = None
        last_exc: BaseException = RuntimeError("never connected")
        while loop.time() < deadline:
            try:
                pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2, init=_init_jsonb)
                break
            except (OSError, asyncpg.CannotConnectNowError) as exc:
                last_exc = exc
                print(f"Postgres not ready ({exc!s}), retrying in {delay:.0f}s…")
                await asyncio.sleep(delay)
                delay = min(delay * 1.5, 5.0)
        if pool is None:
            raise RuntimeError(f"Could not connect to Postgres after 30s: {last_exc}") from last_exc
        try:
            new_version = await apply_pending(pool, migrations_dir)
            print(f"Migrations applied. Schema version: {new_version}")
        finally:
            await pool.close()

    asyncio.run(_run())
