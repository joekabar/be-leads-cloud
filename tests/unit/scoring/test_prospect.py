from __future__ import annotations

import pytest

from scraper.scoring.prospect import ProspectScore, compute_prospect_score

_WEIGHTS = (0.45, 0.20, 0.20, 0.15)


def _score(**fields: object) -> ProspectScore:
    return compute_prospect_score("0123456789", dict(fields))


class TestComputeProspectScore:
    def test_empty_fields_returns_zeros(self) -> None:
        s = _score()
        assert s.hv_probability == 0.0
        assert s.business_activity == 0.0
        assert s.contact_quality == 0.0
        assert s.growth_signal == 0.0
        assert s.overall_prospect == 0.0

    def test_growth_signal_always_zero_phase0(self) -> None:
        s = _score(
            nace_code={"code": "35110"},
            status={"text": "active"},
            phone={"e164": "+3290000000"},
        )
        assert s.growth_signal == 0.0

    # ── hv_probability isolation ───────────────────────────────────────────────

    def test_t1_nace_drives_hv(self) -> None:
        s = _score(nace_code={"code": "35110"})
        assert s.hv_probability == pytest.approx(1.00)
        assert s.business_activity == 0.0
        assert s.contact_quality == 0.0

    def test_unknown_nace_gives_zero_hv(self) -> None:
        s = _score(nace_code={"code": "99999"})
        assert s.hv_probability == 0.0

    def test_missing_nace_gives_zero_hv(self) -> None:
        s = _score(status={"text": "active"})
        assert s.hv_probability == 0.0

    def test_nace_val_without_code_key(self) -> None:
        s = _score(nace_code={"description": "unknown"})
        assert s.hv_probability == 0.0

    # ── business_activity isolation ────────────────────────────────────────────

    def test_active_plus_financial_gives_1(self) -> None:
        s = _score(
            status={"text": "Actief"},
            revenue_2023={"eur": 500000},
        )
        assert s.business_activity == pytest.approx(1.0)
        assert s.hv_probability == 0.0
        assert s.contact_quality == 0.0

    def test_actief_nl_recognised(self) -> None:
        s = _score(status={"text": "actief"}, employees_2024={"count": 50})
        assert s.business_activity == pytest.approx(1.0)

    def test_active_without_financial_gives_half(self) -> None:
        s = _score(status={"text": "active"})
        assert s.business_activity == pytest.approx(0.5)

    def test_financial_without_active_gives_quarter(self) -> None:
        s = _score(revenue_2024={"eur": 100000})
        assert s.business_activity == pytest.approx(0.25)

    def test_inactive_status_gives_zero_activity(self) -> None:
        s = _score(status={"text": "stopped"})
        assert s.business_activity == 0.0

    def test_no_status_no_financial_gives_zero(self) -> None:
        s = _score(name={"text": "Acme"})
        assert s.business_activity == 0.0

    # ── contact_quality isolation ──────────────────────────────────────────────

    def test_all_three_contacts_gives_1(self) -> None:
        s = _score(
            phone={"e164": "+32470000000"},
            email={"address": "x@x.be"},
            website={"url": "https://x.be"},
        )
        assert s.contact_quality == pytest.approx(1.0)
        assert s.business_activity == 0.0

    def test_two_contacts(self) -> None:
        s = _score(phone={"e164": "+32470000000"}, email={"address": "x@x.be"})
        assert s.contact_quality == pytest.approx(2 / 3, abs=1e-5)

    def test_one_contact(self) -> None:
        s = _score(phone={"e164": "+32470000000"})
        assert s.contact_quality == pytest.approx(1 / 3, abs=1e-5)

    def test_no_contacts(self) -> None:
        s = _score(name={"text": "Acme"})
        assert s.contact_quality == 0.0

    # ── overall_prospect weighting ─────────────────────────────────────────────

    def test_weighting_formula_exact(self) -> None:
        s = _score(
            nace_code={"code": "35110"},  # hv=1.00
            status={"text": "active"},  # activity=0.5 (no financial)
            phone={"e164": "+32470"},  # cq=1/3
            email={"address": "x@x.be"},  # cq=2/3
            website={"url": "https://x"},  # cq=1.0
        )
        expected = (
            _WEIGHTS[0] * s.hv_probability
            + _WEIGHTS[1] * s.business_activity
            + _WEIGHTS[2] * s.contact_quality
            + _WEIGHTS[3] * s.growth_signal
        )
        assert s.overall_prospect == pytest.approx(expected, abs=1e-9)

    def test_overall_bounded_zero_to_one(self) -> None:
        for hv_code in ["35110", "43211", "99999"]:
            s = _score(
                nace_code={"code": hv_code},
                status={"text": "active"},
                revenue_2024={"eur": 1},
                phone={"e164": "+32470"},
                email={"address": "x@x.be"},
                website={"url": "https://x"},
            )
            assert 0.0 <= s.overall_prospect <= 1.0

    def test_kbo_number_preserved(self) -> None:
        s = compute_prospect_score("0987654321", {})
        assert s.kbo_number == "0987654321"

    def test_result_is_frozen_dataclass(self) -> None:
        s = _score()
        assert isinstance(s, ProspectScore)
        with pytest.raises((AttributeError, TypeError)):
            s.hv_probability = 0.99  # type: ignore[misc]
