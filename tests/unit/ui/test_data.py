"""Unit tests for scraper.ui.data helpers (no DB required)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

from scraper.db.models import Observation
from scraper.ui.data import (
    _aggregate_row,
    _best_obs_value,
    _latest_financial,
    fetch_results_for_run,
)

_NOW = datetime(2026, 5, 13, 12, 0, 0, tzinfo=UTC)
_RUN = uuid4()
# Pipeline started_at used in fetch_results_for_run tests — one second before _NOW
# so obs with observed_at=_NOW satisfy the >= filter.
_STARTED_AT = datetime(2026, 5, 13, 11, 59, 59, tzinfo=UTC)


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
        result = asyncio.run(fetch_results_for_run(pool, _STARTED_AT))
        assert result == []

    def test_returns_row_for_matching_kbo(self) -> None:
        pool = AsyncMock()
        kbo_record = {"kbo_number": "0439401387"}
        obs_records = [
            _mock_record(field="name", value={"text": "Bellock NV"}),
            _mock_record(
                field="address",
                value={"street": "Lange Van", "postal_code": "2060", "city": "Antwerpen"},
            ),
        ]
        pool.fetch.side_effect = [[kbo_record], obs_records]
        rows = asyncio.run(fetch_results_for_run(pool, _STARTED_AT))
        assert len(rows) == 1
        assert rows[0]["kbo_number"] == "0439401387"
        assert rows[0]["name"] == "Bellock NV"

    def test_city_filter_excludes_non_matching(self) -> None:
        pool = AsyncMock()
        kbo_record = {"kbo_number": "0439401387"}
        obs_records = [
            _mock_record(
                field="address",
                value={"street": "Some Street", "postal_code": "9000", "city": "Gent"},
            ),
        ]
        pool.fetch.side_effect = [[kbo_record], obs_records]
        rows = asyncio.run(fetch_results_for_run(pool, _STARTED_AT, city="Antwerpen"))
        assert rows == []

    def test_city_filter_includes_matching(self) -> None:
        pool = AsyncMock()
        kbo_record = {"kbo_number": "0439401387"}
        obs_records = [
            _mock_record(
                field="address",
                value={"street": "Lange Van", "postal_code": "2060", "city": "Antwerpen"},
            ),
        ]
        pool.fetch.side_effect = [[kbo_record], obs_records]
        rows = asyncio.run(fetch_results_for_run(pool, _STARTED_AT, city="antwerpen"))
        assert len(rows) == 1

    def test_nace_filter_passes_placeholder_kbo_with_no_nace_obs(self) -> None:
        """Placeholder KBOs (no NACE data) must not be filtered out by sector filter."""
        # Placeholder KBOs are exactly 10 digits starting with 9 (bypass mod-97 checksum).
        placeholder = "9000000001"
        pool = AsyncMock()
        kbo_record = {"kbo_number": placeholder}
        obs_records = [
            _mock_record(
                kbo_number=placeholder,
                field="name",
                value={"text": "Elektro Janssen"},
                source="goudengids",
            ),
        ]
        pool.fetch.side_effect = [[kbo_record], obs_records]
        rows = asyncio.run(fetch_results_for_run(pool, _STARTED_AT, sector="elektriciens"))
        assert len(rows) == 1, "placeholder KBO with no NACE obs must not be filtered out"

    def test_nace_filter_excludes_known_wrong_sector(self) -> None:
        """KBOs with a NACE observation that doesn't match the sector are excluded."""
        pool = AsyncMock()
        kbo_record = {"kbo_number": "0439401387"}
        obs_records = [
            _mock_record(field="nace_code", value={"code": "4711"}),  # retail, not electrician
        ]
        pool.fetch.side_effect = [[kbo_record], obs_records]
        rows = asyncio.run(fetch_results_for_run(pool, _STARTED_AT, sector="elektriciens"))
        assert rows == [], "company with non-matching NACE must be excluded"

    def test_nace_filter_includes_matching_nace(self) -> None:
        """KBOs whose NACE observation matches the sector prefix are included."""
        pool = AsyncMock()
        kbo_record = {"kbo_number": "0439401387"}
        obs_records = [
            _mock_record(field="nace_code", value={"code": "43211"}),  # within 432 prefix (no dots)
        ]
        pool.fetch.side_effect = [[kbo_record], obs_records]
        rows = asyncio.run(fetch_results_for_run(pool, _STARTED_AT, sector="elektriciens"))
        assert len(rows) == 1

    def test_postcode_filter_excludes_non_matching(self) -> None:
        """Companies whose address postal_code is not in the postcodes set are excluded."""
        pool = AsyncMock()
        kbo_record = {"kbo_number": "0439401387"}
        obs_records = [
            _mock_record(
                field="address",
                value={"street": "X", "postal_code": "2018", "city": "Antwerpen"},
            ),
        ]
        pool.fetch.side_effect = [[kbo_record], obs_records]
        rows = asyncio.run(fetch_results_for_run(pool, _STARTED_AT, postcodes=("2000", "2020")))
        assert rows == [], "company with postcode 2018 must be excluded when filter is {2000,2020}"

    def test_postcode_filter_includes_matching(self) -> None:
        """Companies whose address postal_code is in the postcodes set are included."""
        pool = AsyncMock()
        kbo_record = {"kbo_number": "0439401387"}
        obs_records = [
            _mock_record(
                field="address",
                value={"street": "X", "postal_code": "2000", "city": "Antwerpen"},
            ),
        ]
        pool.fetch.side_effect = [[kbo_record], obs_records]
        rows = asyncio.run(fetch_results_for_run(pool, _STARTED_AT, postcodes=("2000", "2020")))
        assert len(rows) == 1

    def test_postcode_filter_none_disables_filter(self) -> None:
        """postcodes=None means no postcode filter is applied."""
        pool = AsyncMock()
        kbo_record = {"kbo_number": "0439401387"}
        obs_records = [
            _mock_record(
                field="address",
                value={"street": "X", "postal_code": "2018", "city": "Antwerpen"},
            ),
        ]
        pool.fetch.side_effect = [[kbo_record], obs_records]
        rows = asyncio.run(fetch_results_for_run(pool, _STARTED_AT, postcodes=None))
        assert len(rows) == 1

    def test_goudengids_discovery_scoped_to_sector(self) -> None:
        """KBO discovery query must pass sector slugs so goudengids results from
        a different sector run are not returned (prevents cross-run contamination)."""
        pool = AsyncMock()
        kbo_record = {"kbo_number": "9545074724"}  # SANIFLEX-style placeholder
        obs_records = [
            _mock_record(
                kbo_number="9545074724",
                field="address",
                value={"street": "X", "postal_code": "8400", "city": "Oostende"},
                source="goudengids",
            ),
        ]
        pool.fetch.side_effect = [[kbo_record], obs_records]
        asyncio.run(fetch_results_for_run(pool, _STARTED_AT, sector="bakkers", city="oostende"))
        # The discovery query (first fetch call) must include sector slugs as a
        # positional arg so the JOIN on run_log.sector_slug filters out companies
        # scraped under a different sector (e.g. loodgieters).
        first_call_args = pool.fetch.call_args_list[0][0]  # (sql, city%, nace%, slugs)
        assert len(first_call_args) == 4, (
            "city+sector discovery query must have 4 positional args: "
            "sql, city_pattern, nace_pattern, sector_slugs"
        )
        sector_slugs_arg = first_call_args[3]
        assert "bakkers" in sector_slugs_arg, "NL slug must be in sector_slugs arg"
        assert "boulangeries" in sector_slugs_arg, "FR slug must be in sector_slugs arg"

    def test_results_sorted_by_score_descending(self) -> None:
        pool = AsyncMock()
        kbo_records = [{"kbo_number": "0439401387"}, {"kbo_number": "0202239951"}]
        obs_bellock = [
            _mock_record(field="name", value={"text": "Bellock NV"}),
            _mock_record(field="phone", value={"e164": "+3232361306"}),
            _mock_record(
                field="address",
                value={"street": "X", "postal_code": "2060", "city": "Antwerpen"},
            ),
            _mock_record(field="website", value={"url": "https://bellock.be"}),
            _mock_record(field="founding_date", value={"iso": "1989-12-28"}),
        ]
        obs_minimal = [
            _mock_record(
                kbo_number="0202239951",
                field="name",
                value={"text": "Minimal NV"},
            ),
        ]
        pool.fetch.side_effect = [kbo_records, obs_bellock, obs_minimal]
        rows = asyncio.run(fetch_results_for_run(pool, _STARTED_AT))
        assert len(rows) == 2
        assert rows[0]["score_overall"] >= rows[1]["score_overall"]
