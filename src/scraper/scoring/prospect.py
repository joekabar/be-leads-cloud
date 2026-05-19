"""Prospect scoring: how commercially interesting is a company to Saive?

Orthogonal to LeadScore (which measures data trust). ProspectScore answers
"how likely is this company to be a high-voltage / heavy-industry AI buyer?"
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import structlog

from scraper.db.fields import is_financial_field
from scraper.scoring.hv_prior import hv_probability

if TYPE_CHECKING:
    import asyncpg

logger = structlog.get_logger()

_WEIGHTS = (0.45, 0.20, 0.20, 0.15)  # hv · activity · contact · growth


@dataclass(frozen=True, slots=True)
class ProspectScore:
    kbo_number: str
    hv_probability: float
    business_activity: float
    contact_quality: float
    growth_signal: float
    overall_prospect: float


def _business_activity(fields: dict[str, Any]) -> float:
    """Return [0,1] — 1.0 requires both active status and a financial observation."""
    status_val = fields.get("status")
    status_text = ""
    if isinstance(status_val, dict):
        status_text = str(status_val.get("text", "")).lower()
    is_active = "active" in status_text or "actief" in status_text

    has_financial = any(is_financial_field(f) for f in fields)

    if is_active and has_financial:
        return 1.0
    if is_active:
        return 0.5
    if has_financial:
        return 0.25
    return 0.0


def _contact_quality(fields: dict[str, Any]) -> float:
    """Return mean of three binary contact-reachability signals ∈ {0, 1/3, 2/3, 1}."""
    signals = int("phone" in fields) + int("email" in fields) + int("website" in fields)
    return round(signals / 3, 6)


def compute_prospect_score(kbo: str, fields: dict[str, Any]) -> ProspectScore:
    """Compute ProspectScore from a {field: value_dict} mapping for a single KBO."""
    nace_val = fields.get("nace_code")
    nace_codes = (
        [str(nace_val["code"])] if isinstance(nace_val, dict) and nace_val.get("code") else []
    )

    hv = hv_probability(nace_codes)
    act = _business_activity(fields)
    cq = _contact_quality(fields)
    gs = 0.0  # phase 0 placeholder — populated when growth-signal sources land

    overall = round(
        _WEIGHTS[0] * hv + _WEIGHTS[1] * act + _WEIGHTS[2] * cq + _WEIGHTS[3] * gs,
        6,
    )
    return ProspectScore(
        kbo_number=kbo,
        hv_probability=hv,
        business_activity=act,
        contact_quality=cq,
        growth_signal=gs,
        overall_prospect=overall,
    )


async def refresh_prospect_scores(pool: asyncpg.Pool) -> int:
    """Read companies_current, compute ProspectScore per KBO, bulk-upsert to prospect_scores.

    Returns the number of KBOs upserted.
    """
    rows = await pool.fetch(
        "SELECT kbo_number, field, value FROM companies_current ORDER BY kbo_number"
    )

    # Group rows by KBO — companies_current has at most one row per (kbo, field).
    fields_by_kbo: dict[str, dict[str, Any]] = {}
    for row in rows:
        kbo = str(row["kbo_number"]).strip()
        fields_by_kbo.setdefault(kbo, {})[str(row["field"])] = dict(row["value"])

    if not fields_by_kbo:
        return 0

    scores = [compute_prospect_score(kbo, fields) for kbo, fields in fields_by_kbo.items()]

    upsert_sql = """
        INSERT INTO prospect_scores
            (kbo_number, hv_probability, business_activity, contact_quality,
             growth_signal, overall_prospect, computed_at)
        VALUES ($1, $2, $3, $4, $5, $6, NOW())
        ON CONFLICT (kbo_number) DO UPDATE SET
            hv_probability    = EXCLUDED.hv_probability,
            business_activity = EXCLUDED.business_activity,
            contact_quality   = EXCLUDED.contact_quality,
            growth_signal     = EXCLUDED.growth_signal,
            overall_prospect  = EXCLUDED.overall_prospect,
            computed_at       = EXCLUDED.computed_at
    """
    await pool.executemany(
        upsert_sql,
        [
            (
                s.kbo_number,
                s.hv_probability,
                s.business_activity,
                s.contact_quality,
                s.growth_signal,
                s.overall_prospect,
            )
            for s in scores
        ],
    )
    logger.info("prospect_scores_refreshed", kbos=len(scores))
    return len(scores)
