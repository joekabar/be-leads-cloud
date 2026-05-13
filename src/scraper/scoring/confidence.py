from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

_PRIORS_TABLE: dict[tuple[str, str], float] = {
    ("kbo_dump", "phone"): 0.95,
    ("kbo_dump", "identity"): 1.00,
    ("kbo_dump", "address"): 0.95,
    ("kbo_dump", "founding"): 1.00,
    ("kbo_dump", "website"): 0.85,
    ("kbo_dump", "nace"): 1.00,
    ("kbo_dump", "status"): 1.00,
    ("kbo_dump", "email"): 0.85,
    ("kbopub", "phone"): 0.85,
    ("kbopub", "identity"): 1.00,
    ("kbopub", "address"): 0.95,
    ("kbopub", "founding"): 1.00,
    ("kbopub", "website"): 0.80,
    ("kbopub", "persons"): 0.95,
    ("kbopub", "status"): 1.00,
    ("nbb_authentic", "financial"): 1.00,
    ("goudengids", "phone"): 0.85,
    ("goudengids", "identity"): 0.85,
    ("goudengids", "address"): 0.80,
    ("goudengids", "founding"): 0.85,
    ("goudengids", "website"): 0.85,
    ("goudengids", "activity"): 0.70,
    ("website", "phone"): 0.75,
    ("website", "address"): 0.70,
    ("website", "website"): 1.00,
    ("website", "website_age"): 0.85,
    ("website", "persons"): 0.65,
    ("website", "email"): 0.85,
    ("website", "activity"): 0.80,
    ("brave", "website"): 0.55,
    ("brave", "cross_validation"): 0.55,
    ("ddg", "website"): 0.50,
    ("ddg", "cross_validation"): 0.50,
    ("manual", "phone"): 1.00,
    ("manual", "address"): 1.00,
    ("manual", "identity"): 1.00,
    ("manual", "founding"): 1.00,
    ("manual", "website"): 1.00,
    ("manual", "financial"): 1.00,
    ("manual", "persons"): 1.00,
}

_FIELD_FAMILY_MAP: dict[str, str] = {
    "phone": "phone",
    "name": "identity",
    "address": "address",
    "postal_code": "address",
    "founding_date": "founding",
    "website": "website",
    "website_age": "website_age",
    "nace_code": "nace",
    "function_holder": "persons",
    "activity_summary": "activity",
    "email": "email",
    "status": "status",
    "cross_validation": "cross_validation",
}


@dataclass(frozen=True, slots=True)
class ScoringConfig:
    base_priors: dict[tuple[str, str], float] = field(default_factory=lambda: dict(_PRIORS_TABLE))
    recency_decay_rate: float = 0.99
    recency_min: float = 0.30
    recency_max: float = 1.00
    consensus_boost_factor: float = 1.10
    consensus_max: float = 1.00


def field_family(field_name: str) -> str:
    """Map a specific field name to its prior family."""
    if field_name.startswith(("revenue_", "profit_", "employees_")):
        return "financial"
    return _FIELD_FAMILY_MAP.get(field_name, "other")


def base_prior(source: str, field_name: str, config: ScoringConfig) -> float:
    """Look up (source, field_family) prior. Falls back to 0.5 if missing."""
    family = field_family(field_name)
    return config.base_priors.get((source, family), 0.5)


def apply_recency_decay(
    base: float,
    observed_at: datetime,
    now: datetime,
    config: ScoringConfig,
) -> float:
    """base * decay_rate ** days_since, clamped to [min, max]."""
    days = max(0.0, (now - observed_at).total_seconds() / 86400.0)
    decayed = base * (config.recency_decay_rate**days)
    return float(max(config.recency_min, min(config.recency_max, decayed)))


def apply_consensus_boost(
    raw_confidence: float,
    agreeing_sources_count: int,
    config: ScoringConfig,
) -> float:
    """Multiply by boost_factor for each agreeing distinct source beyond the first."""
    extra = max(0, agreeing_sources_count - 1)
    boosted = raw_confidence * (config.consensus_boost_factor**extra)
    return min(config.consensus_max, boosted)
