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

    name_val = _best_obs_value(obs_list, "name")
    address_val = _best_obs_value(obs_list, "address")
    phone_val = _best_obs_value(obs_list, "phone")
    website_val = _best_obs_value(obs_list, "website")
    founding_val = _best_obs_value(obs_list, "founding_date")

    fh_candidates = [o for o in obs_list if o.field == "function_holder"]
    fh_names = [o.value.get("name", "") for o in fh_candidates if o.value.get("name")]
    unique_fh = list(dict.fromkeys(fh_names))

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
        "website": website_val.get("url", "") if website_val else "",
        "founding_date": founding_val.get("iso") if founding_val else None,
        "employees": _latest_financial(obs_list, "employees"),
        "revenue_latest": _latest_financial(obs_list, "revenue"),
        "function_holders": "; ".join(unique_fh[:5]),
        "score_overall": round(score.overall, 4),
    }


async def fetch_results_for_run(
    pool: asyncpg.Pool,
    started_at: datetime,
    *,
    sector: str | None = None,
    city: str | None = None,
    postcodes: tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    """Pull rows matching sector+city from all-time DB observations.

    Uses city+NACE address joins for KBO discovery so that pre-loaded kbo_dump
    data is visible regardless of when it was ingested. Falls back to run-scoped
    *started_at* filtering when no city is provided (avoids a full table scan).
    Goudengids KBOs (sector-filtered at scrape time) are always included via a
    UNION branch so placeholder KBOs without NACE observations are not dropped.
    When *postcodes* is non-empty, restricts results to companies whose address
    postal_code matches one of those codes.
    """
    now = datetime.now(tz=UTC)

    # Resolve NACE prefix and both language slugs — needed for KBO discovery.
    nace_prefix: str | None = None
    sector_slugs: list[str] = []
    if sector:
        from scraper.pipeline.orchestrator import _SECTOR_NACE_PREFIXES, resolve_sector_slugs

        try:
            nl_slug, fr_slug = resolve_sector_slugs(sector)
            prefixes = _SECTOR_NACE_PREFIXES.get(nl_slug)
            nace_prefix = prefixes[0] if prefixes else None
            sector_slugs = [s for s in [nl_slug, fr_slug] if s]
        except ValueError:
            nace_prefix = None

    # KBO discovery: use city+NACE join when both are known for efficiency.
    if city and nace_prefix:
        kbo_rows = await pool.fetch(
            "SELECT DISTINCT kbo_number FROM observations "
            "WHERE field = 'address' AND value->>'city' ILIKE $1 "
            "AND kbo_number IN ("
            "    SELECT DISTINCT kbo_number FROM observations "
            "    WHERE field = 'nace_code' AND value->>'code' LIKE $2"
            ") "
            "UNION "
            # Goudengids KBOs carry no NACE obs; scope them via run_log.sector_slug
            # so companies scraped under a different sector run are excluded.
            "SELECT DISTINCT o.kbo_number FROM observations o "
            "JOIN run_log rl ON o.run_id = rl.run_id "
            "WHERE o.source = 'goudengids' AND o.field = 'address' "
            "AND o.value->>'city' ILIKE $1 AND rl.sector_slug = ANY($3::text[])",
            f"%{city}%",
            f"{nace_prefix}%",
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
        if nace_prefix:
            nace_obs = [o for o in obs_list if o.field == "nace_code"]
            if nace_obs and not any(
                str(o.value.get("code", "")).startswith(nace_prefix) for o in nace_obs
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

        result.append(_aggregate_row(kbo, obs_list, now))

    result.sort(key=lambda r: r["score_overall"], reverse=True)
    return result
