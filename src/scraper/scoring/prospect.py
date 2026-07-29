"""Prospect scoring: how commercially interesting is a company to Saive?

Orthogonal to LeadScore (which measures data trust). ProspectScore answers
"how likely is this company to be a high-voltage / heavy-industry AI buyer?"
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import structlog

from scraper.db.fields import is_financial_field
from scraper.lib.errors import ScoringTimeoutError
from scraper.scoring.hv_prior import hv_probability

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

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
    """Return [0,1] — 1.0 requires both active status and a financial observation.

    Status observations are written as ``{"value": "active"}`` by both kbo_dump
    producers; ``"text"`` is still accepted so a source using that shape is not
    dropped. Reading only ``"text"`` made every company look inactive.
    """
    status_val = fields.get("status")
    status_text = ""
    if isinstance(status_val, dict):
        raw = status_val.get("value") or status_val.get("text") or ""
        status_text = str(raw).lower()
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


#: Rows per upsert batch. One call carrying ~2M parameter tuples wedged Phase F for
#: 25+ minutes (Postgres active/ClientRead, client idle at 0% CPU, 4.3 GB resident).
_UPSERT_CHUNK_SIZE = 5_000

#: Per-batch ceiling. Bounded batches fail fast instead of hanging indefinitely.
_UPSERT_TIMEOUT_S = 120.0


def _chunked[T](items: Sequence[T], chunk_size: int) -> Iterator[list[T]]:
    """Yield consecutive slices of *items* of at most *chunk_size* elements."""
    if chunk_size <= 0:
        raise ValueError(f"chunk_size must be positive, got {chunk_size}")
    for start in range(0, len(items), chunk_size):
        yield list(items[start : start + chunk_size])


async def refresh_prospect_scores(
    pool: asyncpg.Pool,
    *,
    chunk_size: int = _UPSERT_CHUNK_SIZE,
    timeout_s: float = _UPSERT_TIMEOUT_S,
) -> int:
    """Read companies_current, compute ProspectScore per KBO, bulk-upsert to prospect_scores.

    The upsert is sent in bounded batches, each with its own timeout. A single call
    carrying every tuple wedged in production, and being unbounded it had no timeout to
    break the deadlock. The timeout is passed natively to asyncpg rather than wrapping
    the call in ``asyncio.wait_for``: cancelling from outside makes asyncpg take its
    generic cancel path, which needs the same wedged socket and can hang in turn.

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
    params = [
        (
            s.kbo_number,
            s.hv_probability,
            s.business_activity,
            s.contact_quality,
            s.growth_signal,
            s.overall_prospect,
        )
        for s in scores
    ]

    async with pool.acquire() as conn:
        for batch in _chunked(params, chunk_size):
            try:
                await conn.executemany(upsert_sql, batch, timeout=timeout_s)
            except TimeoutError as exc:
                raise ScoringTimeoutError("prospect_scores", timeout_s) from exc

    logger.info(
        "prospect_scores_refreshed", kbos=len(scores), batches=-(-len(params) // chunk_size)
    )
    return len(scores)
