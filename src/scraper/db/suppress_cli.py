"""``be-leads-suppress`` — record an objection or erasure request.

The person or company stays in ``observations``: that table is append-only, and its
provenance trail is what makes the dataset defensible. What changes is disclosure — every
export consults this list and refuses to emit a matching row.

Identify the subject by whatever they actually gave you. Objections arrive as "stop
calling this number" or "take my address off your list" far more often than as a company
number, so any of --kbo, --email or --phone will do, and several can be combined.

Usage:
    uv run be-leads-suppress --phone +3259701934 --reason "phoned to object, 2026-08-12"
    uv run be-leads-suppress --kbo 0439401387 --reason "erasure request by email"
    uv run be-leads-suppress --list
"""

from __future__ import annotations

import argparse
import asyncio
import sys


def _resolve_dsn(explicit: str | None) -> str:
    """Return the DSN to use, preferring an explicit ``--database-url``.

    ``load_settings()`` *raises* when DATABASE_URL is unset, so it must only be consulted
    when no DSN was passed on the command line. Calling it first made ``--database-url``
    unusable in exactly the situation it exists for — pointing the tool at a database
    other than the one in the environment.
    """
    if explicit:
        return explicit

    from scraper.lib.config import load_settings

    return load_settings().database_url


def cli_main() -> None:  # pragma: no cover
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kbo", default=None, metavar="NUMBER", help="10-digit KBO number")
    parser.add_argument("--email", default=None, metavar="ADDRESS")
    parser.add_argument("--phone", default=None, metavar="E164", help="e.g. +3259701934")
    parser.add_argument("--reason", default=None, help="Why the entry exists (required to add)")
    parser.add_argument("--by", default=None, metavar="NAME", help="Who recorded it")
    parser.add_argument("--list", action="store_true", help="Show current entries and exit")
    parser.add_argument("--database-url", default=None)
    args = parser.parse_args()

    import asyncpg

    # Argument validation before any database work, so a malformed command fails on the
    # thing that is actually wrong rather than on a connection it never needed.
    identifiers = [args.kbo, args.email, args.phone]
    if not args.list and not any(identifiers):
        print("Error: give at least one of --kbo, --email, --phone", file=sys.stderr)
        sys.exit(2)
    if not args.list and not args.reason:
        print(
            "Error: --reason is required; it is the record of why this entry exists",
            file=sys.stderr,
        )
        sys.exit(2)

    dsn = _resolve_dsn(args.database_url)

    async def _run() -> None:
        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
        if pool is None:
            raise RuntimeError("asyncpg.create_pool returned None")
        try:
            if args.list:
                rows = await pool.fetch(
                    "SELECT id, kbo_number, email, phone, reason, recorded_by, "
                    "created_at::date AS created FROM suppression_list ORDER BY id"
                )
                if not rows:
                    print("Suppression list is empty.")
                    return
                print(f"{len(rows)} entr{'y' if len(rows) == 1 else 'ies'}:")
                for r in rows:
                    who = r["kbo_number"] or r["email"] or r["phone"]
                    print(f"  [{r['id']}] {who}  ({r['created']})  {r['reason']}")
                return

            await pool.execute(
                "INSERT INTO suppression_list (kbo_number, email, phone, reason, recorded_by) "
                "VALUES ($1, $2, $3, $4, $5)",
                args.kbo,
                args.email,
                args.phone,
                args.reason,
                args.by,
            )
            target = args.kbo or args.email or args.phone
            print(f"Suppressed {target}. Future exports will omit it.")
            print("Note: existing CSV files already written are unaffected.")
        finally:
            await pool.close()

    asyncio.run(_run())
