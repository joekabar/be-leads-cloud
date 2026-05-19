from __future__ import annotations

import pytest

from scraper.scoring.hv_prior import _HV_PRIORS, hv_probability


class TestHvProbability:
    def test_empty_returns_zero(self) -> None:
        assert hv_probability([]) == 0.0

    def test_unknown_code_returns_zero(self) -> None:
        assert hv_probability(["99999"]) == 0.0

    def test_exact_4digit_match(self) -> None:
        assert hv_probability(["35110"]) == 1.00

    def test_exact_3digit_match(self) -> None:
        # "201" maps to 0.95; code "20100" should match via 3-digit prefix
        assert hv_probability(["20100"]) == pytest.approx(0.95)

    def test_t1_beats_t4_when_both_present(self) -> None:
        # 35110 → T1 (1.00), 43211 → T4 (0.30)
        result = hv_probability(["43211", "35110"])
        assert result == 1.00

    def test_t4_electricians(self) -> None:
        result = hv_probability(["43211"])
        assert result == pytest.approx(0.30)

    def test_t4_gp(self) -> None:
        result = hv_probability(["86210"])
        assert result == pytest.approx(0.05)

    def test_longest_prefix_wins_over_shorter(self) -> None:
        # Both "3511" (1.00) and "35" would be matched — longest wins
        result = hv_probability(["35110"])
        assert result == pytest.approx(1.00)

    def test_multiple_unknown_codes_return_zero(self) -> None:
        assert hv_probability(["99999", "88888", "77777"]) == 0.0

    def test_whitespace_stripped_from_code(self) -> None:
        assert hv_probability(["  35110  "]) == pytest.approx(1.00)

    def test_all_priors_in_range(self) -> None:
        for key, val in _HV_PRIORS.items():
            assert 0.0 <= val <= 1.0, f"Prior for {key!r} out of range: {val}"

    def test_all_prior_keys_dotless(self) -> None:
        for key in _HV_PRIORS:
            assert "." not in key, f"Prior key {key!r} contains a dot"

    @pytest.mark.parametrize(
        "code, expected",
        [
            ("35110", 1.00),  # T1 electricity generation
            ("20100", 0.95),  # T1 basic chemicals
            ("24100", 0.95),  # T1 steel
            ("29100", 0.75),  # T2 automotive mfg
            ("86100", 0.40),  # T3 hospitals
            ("43210", 0.30),  # T4 electricians
            ("86210", 0.05),  # T4 GP doctors
        ],
    )
    def test_tier_samples(self, code: str, expected: float) -> None:
        assert hv_probability([code]) == pytest.approx(expected)
