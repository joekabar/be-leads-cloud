"""CSV export of ranked prospect results from companies_current + prospect_scores."""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import asyncpg

from scraper.db.repositories.observations import _row_to_obs
from scraper.ui.data import _aggregate_row

_COLUMNS = [
    "kbo_number",
    "name",
    "postal_code",
    "city",
    "nace_code",
    "tier",
    "phone",
    "email",
    "website",
    "status",
    "founding_date",
    "revenue_2023",
    "revenue_2024",
    "employees_2024",
    "hv_probability",
    "business_activity",
    "contact_quality",
    "growth_signal",
    "overall_prospect",
]


def _tier(hv: float) -> str:
    if hv >= 0.80:
        return "T1"
    if hv >= 0.55:
        return "T2"
    if hv >= 0.30:
        return "T3"
    return "T4"


def _fmt(v: Any) -> str:
    if v is None:
        return ""
    return str(v)


async def export_csv(
    pool: asyncpg.Pool,
    out_path: Path,
    *,
    run_id: UUID | None = None,
) -> int:
    """Write a ranked CSV of all KBOs in companies_current joined with prospect_scores.

    When *run_id* is given, restricts to KBOs observed in that run. Otherwise
    exports all KBOs currently in the view. Returns the number of rows written.
    """
    now = datetime.now(tz=UTC)

    if run_id is not None:
        kbo_rows = await pool.fetch(
            "SELECT DISTINCT kbo_number FROM observations WHERE run_id = $1",
            run_id,
        )
    else:
        kbo_rows = await pool.fetch("SELECT DISTINCT kbo_number FROM companies_current")

    kbos = [str(r["kbo_number"]).strip() for r in kbo_rows]
    if not kbos:
        out_path.write_text("", encoding="utf-8")  # noqa: ASYNC240
        return 0

    # Bulk-fetch all observations for the target KBOs.

    obs_rows = await pool.fetch(
        "SELECT id, kbo_number, field, value, raw_value, source, source_url, "
        "observed_at, confidence, run_id FROM observations "
        "WHERE kbo_number = ANY($1::char(10)[])",
        kbos,
    )
    obs_by_kbo: dict[str, list[Any]] = {}
    for r in obs_rows:
        kbo = str(r["kbo_number"]).strip()
        obs_by_kbo.setdefault(kbo, []).append(_row_to_obs(r))

    # Bulk-fetch prospect scores.
    ps_rows = await pool.fetch(
        "SELECT kbo_number, hv_probability, business_activity, contact_quality, "
        "growth_signal, overall_prospect FROM prospect_scores "
        "WHERE kbo_number = ANY($1::char(10)[])",
        kbos,
    )
    prospect_map: dict[str, dict[str, float]] = {}
    for r in ps_rows:
        prospect_map[str(r["kbo_number"]).strip()] = {
            "hv_probability": float(r["hv_probability"]),
            "business_activity": float(r["business_activity"]),
            "contact_quality": float(r["contact_quality"]),
            "growth_signal": float(r["growth_signal"]),
            "overall_prospect": float(r["overall_prospect"]),
        }

    # Bulk-fetch financial years from observations.
    fin_rows = await pool.fetch(
        "SELECT kbo_number, field, value FROM observations "
        "WHERE kbo_number = ANY($1::char(10)[]) "
        "AND (field LIKE 'revenue_%' OR field LIKE 'employees_%')",
        kbos,
    )
    fin_by_kbo: dict[str, dict[str, float]] = {}
    for r in fin_rows:
        kbo = str(r["kbo_number"]).strip()
        val = dict(r["value"])
        raw = val.get("eur") or val.get("count")
        if raw is not None:
            fin_by_kbo.setdefault(kbo, {})[str(r["field"])] = float(raw)

    # Bulk-fetch address postal_code + city from companies_current.
    addr_rows = await pool.fetch(
        "SELECT kbo_number, value FROM companies_current "
        "WHERE field = 'address' AND kbo_number = ANY($1::char(10)[])",
        kbos,
    )
    addr_map: dict[str, dict[str, str]] = {}
    for r in addr_rows:
        kbo = str(r["kbo_number"]).strip()
        v = dict(r["value"])
        addr_map[kbo] = {
            "postal_code": str(v.get("postal_code", "") or ""),
            "city": str(v.get("city", "") or ""),
        }

    # Build result rows.
    result: list[dict[str, str]] = []
    for kbo in kbos:
        obs_list = obs_by_kbo.get(kbo, [])
        if not obs_list:
            continue
        base = _aggregate_row(kbo, obs_list, now)
        ps = prospect_map.get(kbo, {})
        fin = fin_by_kbo.get(kbo, {})
        addr = addr_map.get(kbo, {})
        hv = ps.get("hv_probability", 0.0)

        result.append(
            {
                "kbo_number": kbo,
                "name": _fmt(base.get("name")),
                "postal_code": addr.get("postal_code", ""),
                "city": addr.get("city", ""),
                "nace_code": _fmt(base.get("nace_code")),
                "tier": _tier(hv),
                "phone": _fmt(base.get("phone")),
                "email": _fmt(base.get("email")),
                "website": _fmt(base.get("website")),
                "status": _fmt(base.get("status")),
                "founding_date": _fmt(base.get("founding_date")),
                "revenue_2023": _fmt(fin.get("revenue_2023")),
                "revenue_2024": _fmt(fin.get("revenue_2024")),
                "employees_2024": _fmt(fin.get("employees_2024")),
                "hv_probability": _fmt(round(hv, 4)),
                "business_activity": _fmt(round(ps.get("business_activity", 0.0), 4)),
                "contact_quality": _fmt(round(ps.get("contact_quality", 0.0), 4)),
                "growth_signal": _fmt(round(ps.get("growth_signal", 0.0), 4)),
                "overall_prospect": _fmt(round(ps.get("overall_prospect", 0.0), 4)),
            }
        )

    result.sort(key=lambda r: float(r["overall_prospect"] or "0"), reverse=True)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_COLUMNS)
        writer.writeheader()
        writer.writerows(result)

    return len(result)


def cli_main() -> None:  # pragma: no cover
    parser = argparse.ArgumentParser(description="Export ranked prospect CSV from be-leads DB.")
    parser.add_argument("--run-id", default=None, help="UUID of a specific pipeline run")
    parser.add_argument("--out", required=True, help="Output CSV path")
    parser.add_argument("--database-url", default=None, help="PostgreSQL DSN")
    args = parser.parse_args()

    from scraper.lib.config import load_settings

    settings = load_settings()
    dsn = args.database_url or settings.database_url

    run_id: UUID | None = None
    if args.run_id:
        run_id = UUID(args.run_id)

    async def _run() -> None:
        async def _init_jsonb(conn: asyncpg.Connection) -> None:
            await conn.set_type_codec(
                "jsonb",
                encoder=json.dumps,
                decoder=json.loads,
                schema="pg_catalog",
            )

        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3, init=_init_jsonb)
        if pool is None:
            raise RuntimeError("asyncpg.create_pool returned None")
        try:
            n = await export_csv(pool, Path(args.out), run_id=run_id)
            print(f"Exported {n} rows to {args.out}")
        finally:
            await pool.close()

    asyncio.run(_run())
