from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from scraper.db.models import Observation

_RUN_ID = uuid.uuid4()
_VALID_KBO = "BE0439401387"
_COMPACT_KBO = "0439401387"


def _base(**kwargs: object) -> dict[str, object]:
    return {
        "kbo_number": _VALID_KBO,
        "field": "phone",
        "value": {"e164": "+3232361306"},
        "source": "kbo_dump",
        "confidence": 0.95,
        "run_id": _RUN_ID,
        **kwargs,
    }


def test_kbo_compaction() -> None:
    obs = Observation(**_base())  # type: ignore[arg-type]
    assert obs.kbo_number == _COMPACT_KBO


def test_kbo_with_dots_compacted() -> None:
    obs = Observation(**_base(kbo_number="0439.401.387"))  # type: ignore[arg-type]
    assert obs.kbo_number == _COMPACT_KBO


def test_invalid_kbo_raises() -> None:
    with pytest.raises(ValidationError):
        Observation(**_base(kbo_number="INVALID"))  # type: ignore[arg-type]


def test_unknown_field_raises() -> None:
    with pytest.raises(ValidationError):
        Observation(**_base(field="not_a_real_field"))  # type: ignore[arg-type]


def test_financial_field_accepted() -> None:
    obs = Observation(**_base(field="revenue_2023", value={"value": 30326, "currency": "EUR"}))  # type: ignore[arg-type]
    assert obs.field == "revenue_2023"


def test_unknown_source_raises() -> None:
    with pytest.raises(ValidationError):
        Observation(**_base(source="made_up_source"))  # type: ignore[arg-type]


def test_observation_is_frozen() -> None:
    obs = Observation(**_base())  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        obs.confidence = 0.5  # type: ignore[misc]
