from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from scraper.db.models import Observation

from scraper.scoring.confidence import ScoringConfig, apply_recency_decay, base_prior

HIGH_VALUE_FIELDS: tuple[str, ...] = (
    "phone",
    "address",
    "founding_date",
    "website",
    "function_holder",
    "revenue_2023",
    "revenue_2024",
)


@dataclass(frozen=True, slots=True)
class LeadScore:
    kbo_number: str
    completeness: float
    authority: float
    recency: float
    overall: float


def compute_lead_score(
    observations: list[Observation],
    config: ScoringConfig,
    now: datetime,
) -> LeadScore:
    """Aggregate per-(kbo, field) confidences into a 0-1 score for ranking."""
    if not observations:
        kbo = observations[0].kbo_number if observations else ""
        return LeadScore(kbo_number=kbo, completeness=0.0, authority=0.0, recency=0.0, overall=0.0)

    kbo = observations[0].kbo_number

    # Group by field, keep highest-confidence observation per field.
    best_by_field: dict[str, Observation] = {}
    for obs in observations:
        existing = best_by_field.get(obs.field)
        if existing is None or obs.confidence > existing.confidence:
            best_by_field[obs.field] = obs

    # Completeness: fraction of HIGH_VALUE_FIELDS that have at least one observation.
    populated_hvf = [f for f in HIGH_VALUE_FIELDS if f in best_by_field]
    completeness = len(populated_hvf) / len(HIGH_VALUE_FIELDS)

    # Authority: mean recency-decayed base_prior over populated HIGH_VALUE_FIELDS.
    if populated_hvf:
        authority_scores: list[float] = []
        for f in populated_hvf:
            obs = best_by_field[f]
            prior = base_prior(obs.source, f, config)
            oa = obs.observed_at or now
            authority_scores.append(apply_recency_decay(prior, oa, now, config))
        authority = sum(authority_scores) / len(authority_scores)
    else:
        authority = 0.0

    # Recency: 1.0 - mean(days_since / 90), clamped to [0, 1].
    if best_by_field:
        days_list: list[float] = []
        for obs in best_by_field.values():
            oa = obs.observed_at or now
            days_list.append(max(0.0, (now - oa).total_seconds() / 86400.0))
        mean_days = sum(days_list) / len(days_list)
        recency = max(0.0, min(1.0, 1.0 - mean_days / 90.0))
    else:
        recency = 0.0

    overall = 0.5 * completeness + 0.35 * authority + 0.15 * recency

    return LeadScore(
        kbo_number=kbo,
        completeness=completeness,
        authority=authority,
        recency=recency,
        overall=overall,
    )
