"""Quick run summary."""

import asyncio
import os

import asyncpg


async def main() -> None:
    url = os.environ.get("DATABASE_URL", "postgresql://leads:leads@localhost:5432/leads")
    conn = await asyncpg.connect(url)
    rows = await conn.fetch(
        "SELECT run_id, sector_slug, city_slug, started_at FROM run_log ORDER BY started_at DESC LIMIT 5"
    )
    for r in rows:
        cnt = await conn.fetchval(
            "SELECT COUNT(DISTINCT kbo_number) FROM observations WHERE run_id=$1", r["run_id"]
        )
        src = await conn.fetch(
            "SELECT DISTINCT source FROM observations WHERE run_id=$1", r["run_id"]
        )
        sources = [s["source"] for s in src]
        print(
            f"{r['started_at'].strftime('%H:%M')}  {r['sector_slug']:15s} "
            f"{r['city_slug']:10s}  {cnt:5d} KBOs  sources={sources}"
        )
    await conn.close()


asyncio.run(main())
