from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from scraper.db.models import Observation
from scraper.scoring.confidence import ScoringConfig
from scraper.scoring.ranking import HIGH_VALUE_FIELDS, LeadScore, compute_lead_score

_CFG = ScoringConfig()
_NOW = datetime(2026, 5, 13, 12, 0, 0, tzinfo=UTC)
_RUN_ID = uuid4()


def _obs(field: str, source: str = "kbo_dump", confidence: float = 0.9) -> Observation:
    return Observation(
        kbo_number="0439401387",
        field=field,
        value={"v": "x"},
        source=source,
        observed_at=_NOW,
        confidence=confidence,
        run_id=_RUN_ID,
    )


class TestComputeLeadScore:
    def test_empty_observations(self) -> None:
        score = compute_lead_score([], _CFG, _NOW)
        assert score.completeness == 0.0
        assert score.overall == 0.0

    def test_all_high_value_fields_populated(self) -> None:
        obs = [_obs(f) for f in HIGH_VALUE_FIELDS]
        score = compute_lead_score(obs, _CFG, _NOW)
        assert score.completeness == pytest.approx(1.0)
        assert score.overall > 0.8

    def test_sparse_only_name(self) -> None:
        # "name" is not in HIGH_VALUE_FIELDS
        obs = [_obs("name")]
        score = compute_lead_score(obs, _CFG, _NOW)
        assert score.completeness == pytest.approx(0.0)
        assert score.overall < 0.2

    def test_bellock_style_7_fields(self) -> None:
        fields = ["phone", "address", "founding_date", "website", "function_holder", "revenue_2023"]
        obs = [_obs(f) for f in fields]
        score = compute_lead_score(obs, _CFG, _NOW)
        assert score.completeness == pytest.approx(6 / 7)
        assert score.authority > 0.0
        assert score.recency == pytest.approx(1.0)
        assert score.overall > 0.7

    def test_recency_degrades_for_old_observations(self) -> None:
        old = _NOW - timedelta(days=180)
        obs = [
            Observation(
                kbo_number="0439401387",
                field=f,
                value={"v": "x"},
                source="kbo_dump",
                observed_at=old,
                confidence=0.9,
                run_id=_RUN_ID,
            )
            for f in HIGH_VALUE_FIELDS
        ]
        score = compute_lead_score(obs, _CFG, _NOW)
        assert score.recency == pytest.approx(0.0)

    def test_highest_confidence_wins_per_field(self) -> None:
        low = _obs("phone", confidence=0.3)
        high = _obs("phone", confidence=0.95)
        score1 = compute_lead_score([low], _CFG, _NOW)
        score2 = compute_lead_score([high], _CFG, _NOW)
        assert score2.authority >= score1.authority

    def test_lead_score_is_dataclass(self) -> None:
        obs = [_obs("phone")]
        score = compute_lead_score(obs, _CFG, _NOW)
        assert isinstance(score, LeadScore)
        assert score.kbo_number == "0439401387"

    def test_overall_bounded_zero_to_one(self) -> None:
        for n in range(8):
            obs = [_obs(f) for f in list(HIGH_VALUE_FIELDS)[:n]]
            score = compute_lead_score(obs, _CFG, _NOW)
            assert 0.0 <= score.overall <= 1.0
