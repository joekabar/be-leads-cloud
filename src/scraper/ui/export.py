"""CSV export of ranked prospect results from companies_current + prospect_scores."""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

import asyncpg

from scraper.db.repositories.observations import _row_to_obs
from scraper.lib.nace_labels import nace_label
from scraper.pipeline.city_map import get_postal_codes
from scraper.ui.data import _aggregate_row

if TYPE_CHECKING:
    from collections.abc import Sequence

_COLUMNS = [
    "kbo_number",
    "name",
    "postal_code",
    "city",
    "nace_code",
    "nace_label",
    "activity_summary",
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


def resolve_city_postcodes(cities: Sequence[str]) -> list[str]:
    """Map city slugs to the union of their postal codes, order-preserving.

    Raises ``ValueError`` on an unknown slug rather than returning an empty list: a
    silent miss would widen the export to the whole country instead of narrowing it.
    """
    out: list[str] = []
    for city in cities:
        codes = get_postal_codes(city)
        if not codes:
            raise ValueError(f"Unknown city slug: {city!r}")
        for code in codes:
            if code not in out:
                out.append(code)
    return out


def build_selection_sql(
    *,
    run_id: UUID | str | None = None,
    postcodes: Sequence[str] | None = None,
    require_fields: Sequence[str] | None = None,
    max_revenue: float | None = None,
) -> tuple[str, list[Any]]:
    """Build the SQL that picks which KBOs to export, plus its parameters.

    Filtering happens here, in the selection query, rather than in Python after the
    fetch: unfiltered, ``companies_current`` holds ~1.96M KBOs.

    *max_revenue* excludes only companies with a *published* revenue above the ceiling.
    Companies with no revenue on file are kept — micro enterprises file abbreviated
    accounts and legitimately publish no turnover, so dropping them would remove most
    of a small-business list.
    """
    if run_id is not None:
        return "SELECT DISTINCT kbo_number FROM observations WHERE run_id = $1", [run_id]

    if postcodes is not None and not postcodes:
        raise ValueError("postcodes filter is empty — refusing to select every company")

    params: list[Any] = []
    where: list[str] = []

    # Only integer placeholder indices and list lengths are interpolated below; every
    # caller-supplied value travels as a bound $n parameter. Hence the S608 suppressions.
    if postcodes:
        params.append(list(postcodes))
        # postal_code lives inside the address JSONB, not in its own column.
        where.append(
            f"c.field = 'address' AND c.value->>'postal_code' = ANY(${len(params)}::text[])"
        )

    if require_fields:
        params.append(list(require_fields))
        where.append(
            "(SELECT count(DISTINCT f.field) FROM companies_current f "  # noqa: S608
            f"WHERE f.kbo_number = c.kbo_number AND f.field = ANY(${len(params)}::text[])) "
            f"= {len(require_fields)}"
        )

    if max_revenue is not None:
        params.append(max_revenue)
        where.append(
            "NOT EXISTS (SELECT 1 FROM companies_current r "  # noqa: S608
            "WHERE r.kbo_number = c.kbo_number "
            "AND r.field ~ '^revenue_[0-9]{4}$' "
            f"AND (r.value->>'value')::numeric > ${len(params)})"
        )

    if not where:
        return "SELECT DISTINCT kbo_number FROM companies_current", []

    return (
        "SELECT DISTINCT c.kbo_number FROM companies_current c WHERE "  # noqa: S608
        + " AND ".join(where),
        params,
    )


async def export_csv(
    pool: asyncpg.Pool,
    out_path: Path,
    *,
    run_id: UUID | None = None,
    chunk_size: int = 0,
    postcodes: Sequence[str] | None = None,
    require_fields: Sequence[str] | None = None,
    max_revenue: float | None = None,
) -> int | list[Path]:
    """Write a ranked CSV of all KBOs in companies_current joined with prospect_scores.

    When *run_id* is given, restricts to KBOs observed in that run. Otherwise
    exports all KBOs currently in the view.

    When *chunk_size* is 0 (default), writes a single CSV to *out_path* and returns
    the row count as ``int``.

    When *chunk_size* > 0, treats *out_path* as a directory, writes
    ``leads_part_NNNN.csv`` chunk files (1-indexed), and returns a ``list[Path]``
    of the files written.  Raises ``ValueError`` if *out_path* is an existing
    regular file.
    """
    if chunk_size > 0 and out_path.is_file():  # noqa: ASYNC240
        raise ValueError("--out must be a directory when --chunk-size > 0")

    now = datetime.now(tz=UTC)

    select_sql, select_params = build_selection_sql(
        run_id=run_id,
        postcodes=postcodes,
        require_fields=require_fields,
        max_revenue=max_revenue,
    )
    kbo_rows = await pool.fetch(select_sql, *select_params)

    kbos = [str(r["kbo_number"]).strip() for r in kbo_rows]

    # Drop placeholders that consolidation merged into a real KBO **that this export also
    # selects**. Their observations were re-emitted under that KBO, so keeping both ships
    # the same company twice — 559 of 1,674 rows in the 2026-08-01 Oostende export.
    #
    # The membership test is essential, not defensive. A company listed on goudengids in
    # Oostende can be registered at an address elsewhere, so the real KBO fails a
    # city-filtered selection while the placeholder passes it. Dropping such a placeholder
    # unconditionally orphaned 147 real leads — 13% of the file — with no representative
    # left at all. Unmatched placeholders stay for the same reason: they are the only
    # record of those companies.
    matched_rows = await pool.fetch(
        "SELECT placeholder_kbo, real_kbo FROM consolidation_state WHERE real_kbo IS NOT NULL"
    )
    selected = set(kbos)
    merged = {
        str(r["placeholder_kbo"]).strip()
        for r in matched_rows
        if str(r["real_kbo"]).strip() in selected
    }
    if merged:
        kbos = [k for k in kbos if k not in merged]

    if not kbos:
        if chunk_size > 0:
            return []
        out_path.parent.mkdir(parents=True, exist_ok=True)
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
                # A bare code says nothing about the business. Prefer the official KBO
                # label; fall back to a description the observation carried itself.
                "nace_label": _fmt(
                    nace_label(base.get("nace_code"), base.get("nace_version"))
                    or base.get("nace_description")
                ),
                # Website-derived prose, present for only ~875 of 1.96M companies.
                "activity_summary": _fmt(base.get("website_summary")),
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

    if chunk_size == 0:
        # Default: single-file behaviour (backwards compatible).
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=_COLUMNS)
            writer.writeheader()
            writer.writerows(result)
        return len(result)

    # Chunked mode: write to a directory.
    if not result:
        return []

    out_path.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240
    written: list[Path] = []
    for i, start in enumerate(range(0, len(result), chunk_size), start=1):
        chunk = result[start : start + chunk_size]
        chunk_path = out_path / f"leads_part_{i:04d}.csv"
        with chunk_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=_COLUMNS)
            writer.writeheader()
            writer.writerows(chunk)
        written.append(chunk_path)
    return written


def cli_main() -> None:  # pragma: no cover
    import sys

    parser = argparse.ArgumentParser(description="Export ranked prospect CSV from be-leads DB.")
    parser.add_argument("--run-id", default=None, help="UUID of a specific pipeline run")
    parser.add_argument(
        "--out", required=True, help="Output CSV path (or directory when --chunk-size > 0)"
    )
    parser.add_argument("--database-url", default=None, help="PostgreSQL DSN")
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=0,
        help="Split output into chunk files of this many rows (0 = single file, default)",
    )
    parser.add_argument(
        "--city",
        action="append",
        default=None,
        metavar="SLUG",
        help="Restrict to a city by slug, e.g. oostende. Repeatable.",
    )
    parser.add_argument(
        "--require-field",
        action="append",
        default=None,
        metavar="FIELD",
        help="Only export companies having this field, e.g. phone. Repeatable (all must match).",
    )
    parser.add_argument(
        "--max-revenue",
        type=float,
        default=None,
        help=(
            "Exclude companies whose published revenue exceeds this. Companies with no "
            "revenue on file are KEPT (micro enterprises file abbreviated accounts)."
        ),
    )
    args = parser.parse_args()

    chunk_size: int = args.chunk_size
    out_path = Path(args.out)

    if chunk_size > 0 and out_path.is_file():
        print(
            f"Error: --out must be a directory when --chunk-size > 0, but '{args.out}' is a file."
        )
        sys.exit(2)

    from scraper.lib.config import load_settings

    settings = load_settings()
    dsn = args.database_url or settings.database_url

    run_id: UUID | None = None
    if args.run_id:
        run_id = UUID(args.run_id)

    try:
        postcodes = resolve_city_postcodes(args.city) if args.city else None
    except ValueError as exc:
        print(f"Error: {exc}")
        sys.exit(2)

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
            result = await export_csv(
                pool,
                out_path,
                run_id=run_id,
                chunk_size=chunk_size,
                postcodes=postcodes,
                require_fields=args.require_field,
                max_revenue=args.max_revenue,
            )
            if isinstance(result, list):
                total = 0
                for p in result:
                    with p.open(encoding="utf-8") as fh:
                        row_count = sum(1 for _ in fh) - 1  # subtract header
                    total += row_count
                    print(str(p))
                print(f"Exported {total} rows across {len(result)} file(s) to {args.out}")
            else:
                print(f"Exported {result} rows to {args.out}")
        finally:
            await pool.close()

    asyncio.run(_run())
