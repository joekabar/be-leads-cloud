"""_aggregate_row must read the status shape the producers actually write.

Same defect class as the one fixed in scoring/prospect.py::_business_activity: both
kbo_dump producers write ``status = {"value": "active"}``, but this reader asked for
``status["text"]``. The consequences were worse here than a blank column:

``_passes_filters`` treats an empty status as "unknown, keep" (missing values pass).
Since status was ALWAYS empty, the active_only filter silently matched everything, so
dissolved companies passed a filter meant to exclude them. A blank status column in
every CSV export was the visible half of the bug.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from scraper.ui.data import _aggregate_row, _passes_filters


def _obs(field: str, value: dict[str, Any]) -> Any:
    """Minimal stand-in for an Observation row — _aggregate_row reads attributes."""

    class _O:
        pass

    o = _O()
    o.kbo_number = "0453702652"  # type: ignore[attr-defined]
    o.field = field  # type: ignore[attr-defined]
    o.value = value  # type: ignore[attr-defined]
    o.raw_value = None  # type: ignore[attr-defined]
    o.source = "kbo_dump"  # type: ignore[attr-defined]
    o.source_url = None  # type: ignore[attr-defined]
    o.observed_at = datetime.now(tz=UTC)  # type: ignore[attr-defined]
    o.confidence = 0.95  # type: ignore[attr-defined]
    o.run_id = uuid4()  # type: ignore[attr-defined]
    return o


_NOW = datetime.now(tz=UTC)


class TestStatusValueKey:
    def test_value_key_is_read(self) -> None:
        row = _aggregate_row("0453702652", [_obs("status", {"value": "active"})], _NOW)
        assert row["status"] == "active"

    def test_text_key_still_supported(self) -> None:
        """Kept as a fallback so any legacy observation still renders."""
        row = _aggregate_row("0453702652", [_obs("status", {"text": "active"})], _NOW)
        assert row["status"] == "active"

    def test_missing_status_is_empty(self) -> None:
        row = _aggregate_row("0453702652", [_obs("name", {"text": "Bakkerij Nico"})], _NOW)
        assert row["status"] == ""


def _filter(row: dict[str, Any]) -> bool:
    return _passes_filters(
        row,
        min_score=0.0,
        require_phone=False,
        require_website=False,
        require_email=False,
        active_only=True,
        founded_after=None,
        founded_before=None,
        min_revenue=None,
        min_employees=None,
    )


class TestActiveFilterActuallyFilters:
    def test_dissolved_company_is_excluded(self) -> None:
        """The regression this bug caused: with status always blank, a dissolved
        company passed the active-only filter."""
        assert _filter({"status": "dissolved"}) is False

    def test_active_company_passes(self) -> None:
        assert _filter({"status": "active"}) is True

    def test_dutch_actief_passes(self) -> None:
        assert _filter({"status": "actief"}) is True

    def test_unknown_status_is_kept(self) -> None:
        """Missing values pass — absence of data is not evidence of inactivity."""
        assert _filter({"status": ""}) is True
