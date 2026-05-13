"""Unit tests for scraper.ui.data helpers (no DB required)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

from scraper.db.models import Observation
from scraper.ui.data import (
    _aggregate_row,
    _best_obs_value,
    _latest_financial,
    fetch_results_for_run,
)

_NOW = datetime(2026, 5, 13, 12, 0, 0, tzinfo=UTC)
_RUN = uuid4()


def _obs(field: str, value: dict, source: str = "kbo_dump", conf: float = 0.9) -> Observation:
    return Observation(
        kbo_number="0439401387",
        field=field,
        value=value,
        source=source,
        observed_at=_NOW,
        confidence=conf,
        run_id=_RUN,
    )


def _mock_record(**kwargs) -> dict:  # type: ignore[type-arg]
    """Return a dict whose items match what _row_to_obs reads."""
    defaults: dict = {
        "id": 1,
        "kbo_number": "0439401387",
        "field": "name",
        "value": {"text": "Bellock NV"},
        "raw_value": None,
        "source": "kbo_dump",
        "source_url": None,
        "observed_at": _NOW,
        "confidence": 0.9,
        "run_id": _RUN,
    }
    defaults.update(kwargs)
    return defaults


class TestBestObsValue:
    def test_returns_highest_confidence(self) -> None:
        obs = [
            _obs("phone", {"e164": "+3232361306"}, conf=0.5),
            _obs("phone", {"e164": "+32470123456"}, conf=0.9),
        ]
        result = _best_obs_value(obs, "phone")
        assert result == {"e164": "+32470123456"}

    def test_returns_none_when_missing(self) -> None:
        obs = [_obs("name", {"text": "Bellock"})]
        assert _best_obs_value(obs, "phone") is None

    def test_returns_single_observation(self) -> None:
        obs = [_obs("website", {"url": "https://bellock.be", "tld": "be"})]
        result = _best_obs_value(obs, "website")
        assert result is not None
        assert result["url"] == "https://bellock.be"


class TestLatestFinancial:
    def test_returns_latest_year(self) -> None:
        obs = [
            _obs("revenue_2022", {"eur": 1_000_000}),
            _obs("revenue_2023", {"eur": 1_500_000}),
        ]
        assert _latest_financial(obs, "revenue") == 1_500_000

    def test_returns_none_when_absent(self) -> None:
        obs = [_obs("name", {"text": "Bellock"})]
        assert _latest_financial(obs, "revenue") is None

    def test_employees_prefix(self) -> None:
        obs = [_obs("employees_2023", {"count": 42})]
        assert _latest_financial(obs, "employees") == 42


class TestAggregateRow:
    def test_full_row(self) -> None:
        obs = [
            _obs("name", {"text": "Bellock NV", "lang": "nl"}),
            _obs("phone", {"e164": "+3232361306"}),
            _obs(
                "address",
                {"street": "Lange Van Bloerstraat", "postal_code": "2060", "city": "Antwerpen"},
            ),
            _obs("website", {"url": "https://bellock.be", "tld": "be"}),
            _obs("founding_date", {"iso": "1989-12-28"}),
            _obs("function_holder", {"name": "Boonen Peter", "role": "director"}),
            _obs("revenue_2023", {"eur": 1_500_000}),
        ]
        row = _aggregate_row("0439401387", obs, _NOW)
        assert row["kbo_number"] == "0439401387"
        assert row["name"] == "Bellock NV"
        assert row["phone"] == "+3232361306"
        assert "Antwerpen" in row["address"]
        assert row["website"] == "https://bellock.be"
        assert row["founding_date"] == "1989-12-28"
        assert "Boonen" in row["function_holders"]
        assert row["revenue_latest"] == 1_500_000
        assert 0.0 <= row["score_overall"] <= 1.0

    def test_empty_observations(self) -> None:
        row = _aggregate_row("0439401387", [], _NOW)
        assert row["kbo_number"] == "0439401387"
        assert row["name"] == ""
        assert row["score_overall"] == 0.0

    def test_multiple_function_holders_joined(self) -> None:
        obs = [
            _obs("function_holder", {"name": "Alice Smith"}),
            _obs("function_holder", {"name": "Bob Jones"}),
        ]
        row = _aggregate_row("0439401387", obs, _NOW)
        assert "Alice Smith" in row["function_holders"]
        assert "Bob Jones" in row["function_holders"]


class TestFetchResultsForRun:
    def test_empty_run_returns_empty_list(self) -> None:
        pool = AsyncMock()
        pool.fetch.return_value = []
        run_id: UUID = uuid4()
        result = asyncio.run(fetch_results_for_run(pool, run_id))
        assert result == []

    def test_returns_row_for_matching_kbo(self) -> None:
        pool = AsyncMock()
        run_id: UUID = uuid4()
        kbo_record = {"kbo_number": "0439401387"}
        obs_records = [
            _mock_record(field="name", value={"text": "Bellock NV"}, run_id=run_id),
            _mock_record(
                field="address",
                value={"street": "Lange Van", "postal_code": "2060", "city": "Antwerpen"},
                run_id=run_id,
            ),
        ]
        pool.fetch.side_effect = [[kbo_record], obs_records]
        rows = asyncio.run(fetch_results_for_run(pool, run_id))
        assert len(rows) == 1
        assert rows[0]["kbo_number"] == "0439401387"
        assert rows[0]["name"] == "Bellock NV"

    def test_city_filter_excludes_non_matching(self) -> None:
        pool = AsyncMock()
        run_id: UUID = uuid4()
        kbo_record = {"kbo_number": "0439401387"}
        obs_records = [
            _mock_record(
                field="address",
                value={"street": "Some Street", "postal_code": "9000", "city": "Gent"},
                run_id=run_id,
            ),
        ]
        pool.fetch.side_effect = [[kbo_record], obs_records]
        rows = asyncio.run(fetch_results_for_run(pool, run_id, city="Antwerpen"))
        assert rows == []

    def test_city_filter_includes_matching(self) -> None:
        pool = AsyncMock()
        run_id: UUID = uuid4()
        kbo_record = {"kbo_number": "0439401387"}
        obs_records = [
            _mock_record(
                field="address",
                value={"street": "Lange Van", "postal_code": "2060", "city": "Antwerpen"},
                run_id=run_id,
            ),
        ]
        pool.fetch.side_effect = [[kbo_record], obs_records]
        rows = asyncio.run(fetch_results_for_run(pool, run_id, city="antwerpen"))
        assert len(rows) == 1

    def test_results_sorted_by_score_descending(self) -> None:
        pool = AsyncMock()
        run_id: UUID = uuid4()
        kbo_records = [{"kbo_number": "0439401387"}, {"kbo_number": "0202239951"}]
        obs_bellock = [
            _mock_record(field="name", value={"text": "Bellock NV"}, run_id=run_id),
            _mock_record(field="phone", value={"e164": "+3232361306"}, run_id=run_id),
            _mock_record(
                field="address",
                value={"street": "X", "postal_code": "2060", "city": "Antwerpen"},
                run_id=run_id,
            ),
            _mock_record(field="website", value={"url": "https://bellock.be"}, run_id=run_id),
            _mock_record(field="founding_date", value={"iso": "1989-12-28"}, run_id=run_id),
        ]
        obs_minimal = [
            _mock_record(
                kbo_number="0202239951",
                field="name",
                value={"text": "Minimal NV"},
                run_id=run_id,
            ),
        ]
        pool.fetch.side_effect = [kbo_records, obs_bellock, obs_minimal]
        rows = asyncio.run(fetch_results_for_run(pool, run_id))
        assert len(rows) == 2
        assert rows[0]["score_overall"] >= rows[1]["score_overall"]
