from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from scraper.sources.nbb_authentic.parser import FilingData
from scraper.sources.nbb_authentic.transformer import filing_to_observations

_KBO = "0439401387"
_RUN_ID = uuid4()
_SNAPSHOT = datetime(2026, 5, 11, 12, 0, 0, tzinfo=UTC)

_FULL_FILING = FilingData(
    reference_number="2024-00000148",
    exercise_year=2023,
    revenue=285000,
    profit_loss=18000,
    employees_fte=3.2,
    model_type="ABBREVIATED",
)

_NO_REVENUE_FILING = FilingData(
    reference_number="2024-00012345",
    exercise_year=2023,
    revenue=None,
    profit_loss=8500,
    employees_fte=1.5,
    model_type="MICRO",
)

_ALL_NULL_FILING = FilingData(
    reference_number="2024-00099999",
    exercise_year=2023,
    revenue=None,
    profit_loss=None,
    employees_fte=None,
    model_type="MICRO",
)


# ---------------------------------------------------------------------------
# Count of emitted observations
# ---------------------------------------------------------------------------


def test_full_filing_emits_three_observations() -> None:
    obs = filing_to_observations(_KBO, _FULL_FILING, _RUN_ID, _SNAPSHOT)
    assert len(obs) == 3


def test_null_revenue_emits_two_observations() -> None:
    obs = filing_to_observations(_KBO, _NO_REVENUE_FILING, _RUN_ID, _SNAPSHOT)
    assert len(obs) == 2


def test_all_null_emits_no_observations() -> None:
    obs = filing_to_observations(_KBO, _ALL_NULL_FILING, _RUN_ID, _SNAPSHOT)
    assert len(obs) == 0


# ---------------------------------------------------------------------------
# Field names match exercise_year
# ---------------------------------------------------------------------------


def test_field_names_contain_exercise_year() -> None:
    obs = filing_to_observations(_KBO, _FULL_FILING, _RUN_ID, _SNAPSHOT)
    fields = {o.field for o in obs}
    assert fields == {"revenue_2023", "profit_2023", "employees_2023"}


def test_field_name_uses_exercise_year_not_deposit_year() -> None:
    filing = FilingData(
        reference_number="2025-00001234",
        exercise_year=2024,
        revenue=100000,
        profit_loss=5000,
        employees_fte=None,
        model_type="ABBREVIATED",
    )
    obs = filing_to_observations(_KBO, filing, _RUN_ID, _SNAPSHOT)
    fields = {o.field for o in obs}
    assert "revenue_2024" in fields
    assert "profit_2024" in fields


# ---------------------------------------------------------------------------
# JSONB shape
# ---------------------------------------------------------------------------


def test_revenue_observation_jsonb_shape() -> None:
    obs = filing_to_observations(_KBO, _FULL_FILING, _RUN_ID, _SNAPSHOT)
    rev = next(o for o in obs if o.field == "revenue_2023")
    assert rev.value["value"] == 285000
    assert rev.value["currency"] == "EUR"
    assert rev.value["filing_ref"] == "2024-00000148"
    assert rev.value["model_type"] == "ABBREVIATED"


def test_profit_observation_jsonb_shape() -> None:
    obs = filing_to_observations(_KBO, _FULL_FILING, _RUN_ID, _SNAPSHOT)
    pft = next(o for o in obs if o.field == "profit_2023")
    assert pft.value["value"] == 18000
    assert pft.value["currency"] == "EUR"
    assert pft.value["filing_ref"] == "2024-00000148"


def test_employees_observation_jsonb_no_currency() -> None:
    obs = filing_to_observations(_KBO, _FULL_FILING, _RUN_ID, _SNAPSHOT)
    emp = next(o for o in obs if o.field == "employees_2023")
    assert emp.value["value"] == 3.2
    assert "currency" not in emp.value
    assert emp.value["filing_ref"] == "2024-00000148"


def test_no_revenue_obs_value_shape() -> None:
    obs = filing_to_observations(_KBO, _NO_REVENUE_FILING, _RUN_ID, _SNAPSHOT)
    fields = {o.field for o in obs}
    assert "revenue_2023" not in fields
    pft = next(o for o in obs if o.field == "profit_2023")
    assert pft.value["model_type"] == "MICRO"


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


def test_confidence_is_1_00() -> None:
    obs = filing_to_observations(_KBO, _FULL_FILING, _RUN_ID, _SNAPSHOT)
    for o in obs:
        assert o.confidence == 1.00


def test_source_is_nbb_authentic() -> None:
    obs = filing_to_observations(_KBO, _FULL_FILING, _RUN_ID, _SNAPSHOT)
    for o in obs:
        assert o.source == "nbb_authentic"


def test_source_url_contains_kbo_and_ref() -> None:
    obs = filing_to_observations(_KBO, _FULL_FILING, _RUN_ID, _SNAPSHOT)
    for o in obs:
        assert o.source_url is not None
        assert _KBO in o.source_url
        assert "2024-00000148" in o.source_url


def test_kbo_number_propagated() -> None:
    obs = filing_to_observations(_KBO, _FULL_FILING, _RUN_ID, _SNAPSHOT)
    for o in obs:
        assert o.kbo_number == _KBO


def test_run_id_propagated() -> None:
    obs = filing_to_observations(_KBO, _FULL_FILING, _RUN_ID, _SNAPSHOT)
    for o in obs:
        assert o.run_id == _RUN_ID
