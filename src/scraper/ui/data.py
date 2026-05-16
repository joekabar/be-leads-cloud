"""DB queries consumed by the Streamlit UI."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    import asyncpg

from scraper.db.repositories.observations import _row_to_obs
from scraper.scoring.confidence import ScoringConfig
from scraper.scoring.ranking import compute_lead_score

_CFG = ScoringConfig()


def _best_obs_value(obs_list: list[Any], field: str) -> dict[str, Any] | None:
    """Return the value dict of the highest-confidence observation for a given field."""
    candidates = [o for o in obs_list if o.field == field]
    if not candidates:
        return None
    best = max(candidates, key=lambda o: (o.confidence, o.observed_at or datetime.min))
    return cast("dict[str, Any]", best.value)


def _all_obs_values(obs_list: list[Any], field: str) -> list[dict[str, Any]]:
    """Return *all* value dicts for a given field, sorted by confidence desc then observed_at desc.

    De-duplication is left to the caller — different sources can legitimately
    report the same value with different confidences, and the caller decides
    which key to dedupe by (e.g., phone.e164 vs phone.raw).
    """
    candidates = [o for o in obs_list if o.field == field]
    candidates.sort(key=lambda o: (o.confidence, o.observed_at or datetime.min), reverse=True)
    return [cast("dict[str, Any]", o.value) for o in candidates]


def _latest_financial(obs_list: list[Any], prefix: str) -> float | None:
    """Return the most recent financial value for a prefix (revenue/profit/employees)."""
    candidates = [o for o in obs_list if o.field.startswith(prefix + "_")]
    if not candidates:
        return None
    best = max(candidates, key=lambda o: o.field)  # latest year lexicographically
    raw = best.value.get("eur") or best.value.get("count")
    return cast("float | None", raw)


def _aggregate_row(kbo: str, obs_list: list[Any], now: datetime) -> dict[str, Any]:
    """Build the display dict expected by the results table."""
    score = compute_lead_score(obs_list, _CFG, now)

    legal_form_val = _best_obs_value(obs_list, "legal_form")
    name_val = _best_obs_value(obs_list, "name")
    address_val = _best_obs_value(obs_list, "address")
    phone_val = _best_obs_value(obs_list, "phone")
    website_val = _best_obs_value(obs_list, "website")
    founding_val = _best_obs_value(obs_list, "founding_date")
    status_val = _best_obs_value(obs_list, "status")
    nace_val = _best_obs_value(obs_list, "nace_code")
    activity_val = _best_obs_value(obs_list, "activity_summary")

    # Multi-value aggregations — keep order by confidence desc.
    phone_values = _all_obs_values(obs_list, "phone")
    phones_unique: list[str] = []
    for v in phone_values:
        e164 = v.get("e164", "")
        if e164 and e164 not in phones_unique:
            phones_unique.append(e164)

    email_values = _all_obs_values(obs_list, "email")
    emails_unique: list[str] = []
    for v in email_values:
        addr = v.get("address", "")
        if addr and addr not in emails_unique:
            emails_unique.append(addr)

    fh_candidates = [o for o in obs_list if o.field == "function_holder"]
    fh_names = [o.value.get("name", "") for o in fh_candidates if o.value.get("name")]
    unique_fh = list(dict.fromkeys(fh_names))
    fh_full: list[str] = []
    seen_fh: set[str] = set()
    for o in fh_candidates:
        name = str(o.value.get("name", "")).strip()
        role = str(o.value.get("role", "")).strip()
        if not name or name in seen_fh:
            continue
        seen_fh.add(name)
        fh_full.append(f"{name} ({role})" if role else name)

    # Sources contributing observations for this KBO.
    sources_count: dict[str, int] = {}
    for o in obs_list:
        sources_count[o.source] = sources_count.get(o.source, 0) + 1

    address_str = ""
    if address_val:
        parts = [
            address_val.get("street", ""),
            address_val.get("postal_code", ""),
            address_val.get("city", ""),
        ]
        address_str = " ".join(p for p in parts if p).strip()

    return {
        "kbo_number": kbo,
        "name": name_val.get("text", "") if name_val else "",
        "address": address_str,
        "phone": phone_val.get("e164", "") if phone_val else "",
        "phones_all": " | ".join(phones_unique),
        "email": emails_unique[0] if emails_unique else "",
        "emails_all": " | ".join(emails_unique),
        "website": website_val.get("url", "") if website_val else "",
        "website_summary": activity_val.get("text", "") if activity_val else "",
        "founding_date": founding_val.get("iso") if founding_val else None,
        "status": status_val.get("text", "") if status_val else "",
        "nace_code": nace_val.get("code", "") if nace_val else "",
        "nace_description": nace_val.get("description", "") if nace_val else "",
        "legal_form_code": legal_form_val.get("code", "") if legal_form_val else "",
        "legal_form_label": legal_form_val.get("label", "") if legal_form_val else "",
        "size_category": legal_form_val.get("size_category", "") if legal_form_val else "",
        "employees": _latest_financial(obs_list, "employees"),
        "revenue_latest": _latest_financial(obs_list, "revenue"),
        "function_holders": "; ".join(unique_fh[:5]),
        "function_holders_all": "; ".join(fh_full),
        "sources_count": sources_count,
        "score_overall": round(score.overall, 4),
    }


async def fetch_results_for_run(
    pool: asyncpg.Pool,
    started_at: datetime,
    *,
    sector: str | None = None,
    city: str | None = None,
    postcodes: tuple[str, ...] | None = None,
    min_score: float = 0.0,
    require_phone: bool = False,
    require_website: bool = False,
    require_email: bool = False,
    active_only: bool = False,
    founded_after: str | None = None,
    founded_before: str | None = None,
    min_revenue: float | None = None,
    min_employees: float | None = None,
    size_categories: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Pull rows matching sector+city from all-time DB observations.

    Uses city+NACE address joins for KBO discovery so that pre-loaded kbo_dump
    data is visible regardless of when it was ingested. Falls back to run-scoped
    *started_at* filtering when no city is provided (avoids a full table scan).
    Goudengids KBOs (sector-filtered at scrape time) are always included via a
    UNION branch so placeholder KBOs without NACE observations are not dropped.
    When *postcodes* is non-empty, restricts results to companies whose address
    postal_code matches one of those codes.

    Result filters (applied after aggregation, before sorting):
    - *min_score*: drop rows with score_overall < this value.
    - *require_phone* / *require_website*: drop rows without that field.
    - *founded_after* / *founded_before*: ISO date strings; drop rows whose
      founding_date falls outside the range. Rows with no founding_date pass
      through (we don't know, so don't filter).
    - *min_revenue* / *min_employees*: drop rows below threshold; rows where
      the value is unknown pass through.
    """
    now = datetime.now(tz=UTC)

    # Resolve NACE prefixes and both language slugs — needed for KBO discovery.
    nace_prefixes: list[str] | None = None
    sector_slugs: list[str] = []
    if sector:
        from scraper.pipeline.orchestrator import _SECTOR_NACE_PREFIXES, resolve_sector_slugs

        try:
            nl_slug, fr_slug = resolve_sector_slugs(sector)
            prefixes = _SECTOR_NACE_PREFIXES.get(nl_slug)
            nace_prefixes = list(prefixes) if prefixes else None
            sector_slugs = [s for s in [nl_slug, fr_slug] if s]
        except ValueError:
            nace_prefixes = None

    # KBO discovery: use city+NACE join when both are known for efficiency.
    if city and nace_prefixes:
        nace_patterns = [f"{p}%" for p in nace_prefixes]
        kbo_rows = await pool.fetch(
            "SELECT DISTINCT kbo_number FROM observations "
            "WHERE field = 'address' AND value->>'city' ILIKE $1 "
            "AND kbo_number IN ("
            "    SELECT DISTINCT kbo_number FROM observations "
            "    WHERE field = 'nace_code' AND value->>'code' LIKE ANY($2::text[])"
            ") "
            "UNION "
            # Goudengids KBOs carry no NACE obs; scope them via run_log.sector_slug
            # so companies scraped under a different sector run are excluded.
            "SELECT DISTINCT o.kbo_number FROM observations o "
            "JOIN run_log rl ON o.run_id = rl.run_id "
            "WHERE o.source = 'goudengids' AND o.field = 'address' "
            "AND o.value->>'city' ILIKE $1 AND rl.sector_slug = ANY($3::text[])",
            f"%{city}%",
            nace_patterns,
            sector_slugs,
        )
    elif city:
        kbo_rows = await pool.fetch(
            "SELECT DISTINCT kbo_number FROM observations "
            "WHERE field = 'address' AND value->>'city' ILIKE $1",
            f"%{city}%",
        )
    else:
        # No city — fall back to run-scoped query to avoid a full table scan.
        kbo_rows = await pool.fetch(
            "SELECT DISTINCT kbo_number FROM observations WHERE observed_at >= $1",
            started_at,
        )

    kbos = [str(r["kbo_number"]).strip() for r in kbo_rows]
    if not kbos:
        return []

    result: list[dict[str, Any]] = []
    for kbo in kbos:
        obs_rows = await pool.fetch(
            "SELECT id, kbo_number, field, value, raw_value, source, source_url, "
            "observed_at, confidence, run_id FROM observations WHERE kbo_number = $1",
            kbo,
        )
        obs_list = [_row_to_obs(r) for r in obs_rows]

        # Secondary NACE filter: exclude KBOs that have a NACE obs not matching the sector.
        # KBOs without any NACE observation (goudengids placeholders) pass through.
        if nace_prefixes:
            nace_obs = [o for o in obs_list if o.field == "nace_code"]
            if nace_obs and not any(
                any(str(o.value.get("code", "")).startswith(p) for p in nace_prefixes)
                for o in nace_obs
            ):
                continue

        # Secondary city filter: safety check for KBOs that slipped through the join.
        if city:
            addr_obs = [o for o in obs_list if o.field == "address"]
            city_lower = city.lower()
            if not any(city_lower in str(o.value.get("city", "")).lower() for o in addr_obs):
                continue

        # Postcode filter: restrict to companies whose address has one of the
        # selected postcodes. KBOs without any address obs are dropped here.
        if postcodes:
            addr_obs = [o for o in obs_list if o.field == "address"]
            company_postcodes = {str(o.value.get("postal_code", "")).strip() for o in addr_obs}
            if not company_postcodes & set(postcodes):
                continue

        row = _aggregate_row(kbo, obs_list, now)
        if not _passes_filters(
            row,
            min_score=min_score,
            require_phone=require_phone,
            require_website=require_website,
            require_email=require_email,
            active_only=active_only,
            founded_after=founded_after,
            founded_before=founded_before,
            min_revenue=min_revenue,
            min_employees=min_employees,
            size_categories=size_categories,
        ):
            continue
        result.append(row)

    result.sort(key=lambda r: r["score_overall"], reverse=True)
    return result


def _passes_filters(
    row: dict[str, Any],
    *,
    min_score: float,
    require_phone: bool,
    require_website: bool,
    require_email: bool,
    active_only: bool,
    founded_after: str | None,
    founded_before: str | None,
    min_revenue: float | None,
    min_employees: float | None,
    size_categories: list[str] | None = None,
) -> bool:
    """Return True if *row* satisfies all active filter criteria.

    Filters compose with AND. For optional fields (founding_date, revenue,
    employees, status, size_category) a row passes if the value is missing —
    we don't filter on unknowns, we just don't include them in the comparison.
    """
    if row.get("score_overall", 0.0) < min_score:
        return False
    if require_phone and not row.get("phone"):
        return False
    if require_website and not row.get("website"):
        return False
    if require_email and not row.get("email"):
        return False
    if active_only:
        status = str(row.get("status") or "").lower()
        if status and "active" not in status and "actief" not in status:
            return False
    founding = row.get("founding_date")
    if founding:
        if founded_after and founding < founded_after:
            return False
        if founded_before and founding > founded_before:
            return False
    if min_revenue is not None:
        rev = row.get("revenue_latest")
        if rev is not None and rev < min_revenue:
            return False
    if min_employees is not None:
        emp = row.get("employees")
        if emp is not None and emp < min_employees:
            return False
    if size_categories is not None:
        cat = row.get("size_category", "")
        if cat and cat not in size_categories:
            return False
    return True
