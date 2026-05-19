"""Check kbopub enrichment for Oostende elektriciens."""

import asyncio
import os

import asyncpg


async def check() -> None:
    url = os.environ.get("DATABASE_URL", "postgresql://leads:leads@localhost:5432/leads")
    conn = await asyncpg.connect(url)

    elec_oos = await conn.fetch(
        "SELECT DISTINCT o1.kbo_number "
        "FROM observations o1 "
        "JOIN observations o2 ON o1.kbo_number = o2.kbo_number "
        "WHERE o1.field = 'address' AND o1.value->>'city' ILIKE '%Oostende%' "
        "AND o2.field = 'nace_code' AND o2.value->>'code' LIKE '4321%'"
    )
    kbo_list = [r["kbo_number"] for r in elec_oos]
    print(f"Elektriciens in Oostende (real KBOs): {len(kbo_list)}")

    kbopub_enriched = await conn.fetchval(
        "SELECT COUNT(DISTINCT kbo_number) FROM observations "
        "WHERE source='kbopub' AND kbo_number=ANY($1)",
        kbo_list,
    )
    print(f"kbopub-enriched: {kbopub_enriched}")

    samples = await conn.fetch(
        "SELECT DISTINCT o.kbo_number, o.value->>'name' as name, o.value->>'role' as role "
        "FROM observations o "
        "WHERE o.source='kbopub' AND o.field='function_holder' AND o.kbo_number=ANY($1) "
        "LIMIT 5",
        kbo_list,
    )
    print("Sample function holders:")
    for s in samples:
        nm = (s["name"] or "").encode("ascii", "replace").decode()
        print(f"  {s['kbo_number']}  {nm} ({s['role']})")

    # Goudengids companies for Oostende elektriciens
    gg_oos = await conn.fetchval(
        "SELECT COUNT(DISTINCT o.kbo_number) FROM observations o "
        "JOIN run_log rl ON o.run_id = rl.run_id "
        "WHERE o.source='goudengids' AND o.field='address' "
        "AND o.value->>'city' ILIKE '%Oostende%' "
        "AND rl.sector_slug IN ('elektriciens', 'electriciens')"
    )
    print(f"Goudengids Oostende elektriciens (placeholder KBOs): {gg_oos}")

    # Website observations for Oostende
    web_oos = await conn.fetchval(
        "SELECT COUNT(DISTINCT o.kbo_number) FROM observations o "
        "WHERE o.source='website' AND o.kbo_number=ANY($1)",
        kbo_list,
    )
    print(f"Website-enriched (of elektriciens): {web_oos}")

    # NBB observations for Oostende elektriciens
    nbb_oos = await conn.fetchval(
        "SELECT COUNT(DISTINCT o.kbo_number) FROM observations o "
        "WHERE o.source='nbb' AND o.kbo_number=ANY($1)",
        kbo_list,
    )
    print(f"NBB-enriched (of elektriciens): {nbb_oos}")

    await conn.close()


asyncio.run(check())
