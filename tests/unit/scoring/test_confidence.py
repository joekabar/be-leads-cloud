from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from scraper.scoring.confidence import (
    ScoringConfig,
    apply_consensus_boost,
    apply_recency_decay,
    base_prior,
    field_family,
)

_CFG = ScoringConfig()


class TestFieldFamily:
    def test_phone(self) -> None:
        assert field_family("phone") == "phone"

    def test_name_is_identity(self) -> None:
        assert field_family("name") == "identity"

    def test_address(self) -> None:
        assert field_family("address") == "address"

    def test_postal_code_is_address(self) -> None:
        assert field_family("postal_code") == "address"

    def test_founding_date(self) -> None:
        assert field_family("founding_date") == "founding"

    def test_website(self) -> None:
        assert field_family("website") == "website"

    def test_nace_code(self) -> None:
        assert field_family("nace_code") == "nace"

    def test_function_holder_is_persons(self) -> None:
        assert field_family("function_holder") == "persons"

    def test_financial_revenue(self) -> None:
        assert field_family("revenue_2023") == "financial"

    def test_financial_profit(self) -> None:
        assert field_family("profit_2024") == "financial"

    def test_financial_employees(self) -> None:
        assert field_family("employees_2022") == "financial"

    def test_unknown_field_is_other(self) -> None:
        assert field_family("xxx_unknown") == "other"

    def test_activity_summary(self) -> None:
        assert field_family("activity_summary") == "activity"

    def test_status(self) -> None:
        assert field_family("status") == "status"


class TestBasePrior:
    def test_kbo_dump_phone(self) -> None:
        assert base_prior("kbo_dump", "phone", _CFG) == pytest.approx(0.95)

    def test_kbo_dump_identity(self) -> None:
        assert base_prior("kbo_dump", "name", _CFG) == pytest.approx(1.00)

    def test_nbb_financial(self) -> None:
        assert base_prior("nbb_authentic", "revenue_2023", _CFG) == pytest.approx(1.00)

    def test_brave_website(self) -> None:
        assert base_prior("brave", "website", _CFG) == pytest.approx(0.55)

    def test_ddg_website(self) -> None:
        assert base_prior("ddg", "website", _CFG) == pytest.approx(0.50)

    def test_unknown_source_fallback(self) -> None:
        assert base_prior("unknown_source", "phone", _CFG) == pytest.approx(0.5)

    def test_known_source_unknown_family_fallback(self) -> None:
        assert base_prior("kbo_dump", "xxx_unknown", _CFG) == pytest.approx(0.5)

    def test_goudengids_phone(self) -> None:
        assert base_prior("goudengids", "phone", _CFG) == pytest.approx(0.85)

    def test_website_source_website_field(self) -> None:
        assert base_prior("website", "website", _CFG) == pytest.approx(1.00)


class TestRecencyDecay:
    def _now(self) -> datetime:
        return datetime(2026, 5, 13, 12, 0, 0, tzinfo=UTC)

    def test_30_days_ago(self) -> None:
        observed = self._now() - timedelta(days=30)
        result = apply_recency_decay(0.95, observed, self._now(), _CFG)
        expected = 0.95 * (0.99**30)
        assert result == pytest.approx(expected, abs=1e-4)
        assert result > _CFG.recency_min

    def test_very_old_clamped_to_floor(self) -> None:
        observed = self._now() - timedelta(days=5 * 365)
        result = apply_recency_decay(0.40, observed, self._now(), _CFG)
        assert result == pytest.approx(_CFG.recency_min)

    def test_today_no_decay(self) -> None:
        result = apply_recency_decay(0.95, self._now(), self._now(), _CFG)
        assert result == pytest.approx(0.95)

    def test_high_base_clamps_to_max(self) -> None:
        result = apply_recency_decay(1.05, self._now(), self._now(), _CFG)
        assert result == pytest.approx(_CFG.recency_max)

    def test_decay_is_monotonically_decreasing(self) -> None:
        base = 0.9
        now = self._now()
        results = [
            apply_recency_decay(base, now - timedelta(days=d), now, _CFG) for d in range(0, 400, 30)
        ]
        for a, b in zip(results, results[1:]):
            assert a >= b


class TestConsensusBoost:
    def test_single_source_no_boost(self) -> None:
        result = apply_consensus_boost(0.85, agreeing_sources_count=1, config=_CFG)
        assert result == pytest.approx(0.85)

    def test_two_sources_one_extra(self) -> None:
        result = apply_consensus_boost(0.85, agreeing_sources_count=2, config=_CFG)
        assert result == pytest.approx(0.85 * 1.10)

    def test_three_sources_capped(self) -> None:
        result = apply_consensus_boost(0.85, agreeing_sources_count=3, config=_CFG)
        expected = 0.85 * 1.10 * 1.10
        assert result == pytest.approx(min(1.00, expected))

    def test_high_base_clamped_to_one(self) -> None:
        result = apply_consensus_boost(0.99, agreeing_sources_count=3, config=_CFG)
        assert result == pytest.approx(1.00)

    def test_zero_sources_treated_as_first(self) -> None:
        # agreeing=0 means no sources — same as single (no negative exponent)
        result = apply_consensus_boost(0.85, agreeing_sources_count=0, config=_CFG)
        assert result == pytest.approx(0.85)
