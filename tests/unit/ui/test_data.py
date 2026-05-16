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

    def test_aggregates_all_phones_dedup_by_e164(self) -> None:
        obs = [
            _obs("phone", {"e164": "+3232361306"}, source="goudengids", conf=0.85),
            _obs("phone", {"e164": "+32475999930"}, source="website", conf=0.75),
            _obs("phone", {"e164": "+3232361306"}, source="kbo_dump", conf=0.95),  # dup
        ]
        row = _aggregate_row("0439401387", obs, _NOW)
        assert row["phones_all"].count("+3232361306") == 1
        assert "+32475999930" in row["phones_all"]
        # Highest-confidence value remains in `phone` (single best).
        assert row["phone"] == "+3232361306"

    def test_aggregates_all_emails_dedup(self) -> None:
        obs = [
            _obs("email", {"address": "a@x.be"}, source="website", conf=0.85),
            _obs("email", {"address": "b@x.be"}, source="website", conf=0.50),
        ]
        row = _aggregate_row("0439401387", obs, _NOW)
        assert "a@x.be" in row["emails_all"]
        assert "b@x.be" in row["emails_all"]
        assert row["email"] == "a@x.be"  # best (higher confidence)

    def test_function_holders_all_uncapped_with_roles(self) -> None:
        obs = [
            _obs("function_holder", {"name": f"Person {i}", "role": "director"}) for i in range(8)
        ]
        row = _aggregate_row("0439401387", obs, _NOW)
        # function_holders is capped at 5; function_holders_all is not.
        assert row["function_holders"].count(";") == 4  # 5 entries → 4 separators
        assert row["function_holders_all"].count(";") == 7  # 8 entries → 7 separators
        assert "(director)" in row["function_holders_all"]

    def test_nace_description_surfaced_from_obs(self) -> None:
        obs = [_obs("nace_code", {"code": "43211", "description": "Electrical installation"})]
        row = _aggregate_row("0439401387", obs, _NOW)
        assert row["nace_code"] == "43211"
        assert row["nace_description"] == "Electrical installation"

    def test_status_surfaced_from_obs(self) -> None:
        obs = [_obs("status", {"text": "active"})]
        row = _aggregate_row("0439401387", obs, _NOW)
        assert row["status"] == "active"

    def test_website_summary_from_activity_summary(self) -> None:
        obs = [_obs("activity_summary", {"text": "We install solar panels."})]
        row = _aggregate_row("0439401387", obs, _NOW)
        assert row["website_summary"] == "We install solar panels."

    def test_sources_count_counts_observations_per_source(self) -> None:
        obs = [
            _obs("name", {"text": "X"}, source="kbo_dump"),
            _obs("address", {"street": "S"}, source="kbo_dump"),
            _obs("phone", {"e164": "+3232361306"}, source="goudengids"),
        ]
        row = _aggregate_row("0439401387", obs, _NOW)
        assert row["sources_count"] == {"kbo_dump": 2, "goudengids": 1}


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
            _mock_record(
                field="nace_code", value={"code": "43211"}
            ),  # within 4321 prefix (no dots)
        ]
        pool.fetch.side_effect = [[kbo_record], obs_records]
        rows = asyncio.run(fetch_results_for_run(pool, _STARTED_AT, sector="elektriciens"))
        assert len(rows) == 1

    def test_nace_filter_includes_second_prefix(self) -> None:
        """Company matching the *second* sector prefix (not just the first) must be included."""
        pool = AsyncMock()
        kbo_record = {"kbo_number": "0439401387"}
        obs_records = [
            # informaticabedrijven has prefixes ["620", "631", "582"].
            # 63110 = data processing / hosting — matches "631" prefix.
            _mock_record(field="nace_code", value={"code": "63110"}),
        ]
        pool.fetch.side_effect = [[kbo_record], obs_records]
        rows = asyncio.run(fetch_results_for_run(pool, _STARTED_AT, sector="informaticabedrijven"))
        assert len(rows) == 1, "company with NACE 63110 (second prefix) must not be filtered out"

    def test_nace_filter_includes_third_prefix(self) -> None:
        """Company matching the *third* sector prefix must be included."""
        pool = AsyncMock()
        kbo_record = {"kbo_number": "0439401387"}
        obs_records = [
            # informaticabedrijven prefix "582" covers software publishing (58210, 58290).
            _mock_record(field="nace_code", value={"code": "58290"}),
        ]
        pool.fetch.side_effect = [[kbo_record], obs_records]
        rows = asyncio.run(fetch_results_for_run(pool, _STARTED_AT, sector="informaticabedrijven"))
        assert len(rows) == 1, "company with NACE 58290 (third prefix) must not be filtered out"

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

    def test_min_score_filter_drops_low_quality(self) -> None:
        pool = AsyncMock()
        kbo_record = {"kbo_number": "9000000001"}
        obs_records = [
            _mock_record(
                kbo_number="9000000001",
                field="name",
                value={"text": "Tiny Co"},
                source="goudengids",
                confidence=0.85,
            ),
        ]
        pool.fetch.side_effect = [[kbo_record], obs_records]
        rows = asyncio.run(fetch_results_for_run(pool, _STARTED_AT, min_score=0.9))
        assert rows == [], "low-score row must be filtered when min_score=0.9"

    def test_require_phone_filter(self) -> None:
        pool = AsyncMock()
        kbo_record = {"kbo_number": "0439401387"}
        obs_records = [_mock_record(field="name", value={"text": "Bellock NV"})]  # no phone
        pool.fetch.side_effect = [[kbo_record], obs_records]
        rows = asyncio.run(fetch_results_for_run(pool, _STARTED_AT, require_phone=True))
        assert rows == [], "row without phone must be filtered when require_phone=True"

    def test_require_website_filter_allows_when_present(self) -> None:
        pool = AsyncMock()
        kbo_record = {"kbo_number": "0439401387"}
        obs_records = [
            _mock_record(field="website", value={"url": "https://x.be", "tld": "be"}),
        ]
        pool.fetch.side_effect = [[kbo_record], obs_records]
        rows = asyncio.run(fetch_results_for_run(pool, _STARTED_AT, require_website=True))
        assert len(rows) == 1

    def test_founded_after_filter_drops_older_company(self) -> None:
        pool = AsyncMock()
        kbo_record = {"kbo_number": "0439401387"}
        obs_records = [_mock_record(field="founding_date", value={"iso": "1985-01-01"})]
        pool.fetch.side_effect = [[kbo_record], obs_records]
        rows = asyncio.run(fetch_results_for_run(pool, _STARTED_AT, founded_after="2000-01-01"))
        assert rows == []

    def test_founded_date_unknown_passes_through(self) -> None:
        """Companies with no founding_date observation must not be filtered out."""
        pool = AsyncMock()
        kbo_record = {"kbo_number": "0439401387"}
        obs_records = [_mock_record(field="name", value={"text": "X"})]
        pool.fetch.side_effect = [[kbo_record], obs_records]
        rows = asyncio.run(fetch_results_for_run(pool, _STARTED_AT, founded_after="2000-01-01"))
        assert len(rows) == 1, "unknown founding_date must pass through"

    def test_min_revenue_filter(self) -> None:
        pool = AsyncMock()
        kbo_record = {"kbo_number": "0439401387"}
        obs_records = [_mock_record(field="revenue_2023", value={"eur": 100_000.0})]
        pool.fetch.side_effect = [[kbo_record], obs_records]
        rows = asyncio.run(fetch_results_for_run(pool, _STARTED_AT, min_revenue=1_000_000.0))
        assert rows == []

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


class TestSizeCategory:
    def test_aggregate_row_nv_is_large(self) -> None:
        obs = [_obs("legal_form", {"code": "014", "label": "NV", "size_category": "Large"})]
        row = _aggregate_row("0439401387", obs, _NOW)
        assert row["size_category"] == "Large"
        assert row["legal_form_label"] == "NV"

    def test_aggregate_row_bv_is_sme(self) -> None:
        obs = [_obs("legal_form", {"code": "017", "label": "BV", "size_category": "SME"})]
        row = _aggregate_row("0439401387", obs, _NOW)
        assert row["size_category"] == "SME"

    def test_aggregate_row_eenmanszaak_is_solo(self) -> None:
        obs = [_obs("legal_form", {"code": "010", "label": "Eenmanszaak", "size_category": "Solo"})]
        row = _aggregate_row("0439401387", obs, _NOW)
        assert row["size_category"] == "Solo"

    def test_aggregate_row_no_legal_form_obs_returns_empty_string(self) -> None:
        obs = [_obs("name", {"text": "Unknown Co"})]
        row = _aggregate_row("0439401387", obs, _NOW)
        assert row["size_category"] == ""
        assert row["legal_form_label"] == ""

    def test_size_filter_excludes_non_matching_category(self) -> None:
        pool = AsyncMock()
        kbo_record = {"kbo_number": "0439401387"}
        obs_records = [
            _mock_record(
                field="legal_form",
                value={"code": "010", "label": "Eenmanszaak", "size_category": "Solo"},
            ),
        ]
        pool.fetch.side_effect = [[kbo_record], obs_records]
        rows = asyncio.run(
            fetch_results_for_run(pool, _STARTED_AT, size_categories=["SME", "Large"])
        )
        assert rows == [], "Solo company must be excluded when filter is SME+Large"

    def test_size_filter_includes_matching_category(self) -> None:
        pool = AsyncMock()
        kbo_record = {"kbo_number": "0439401387"}
        obs_records = [
            _mock_record(
                field="legal_form",
                value={"code": "017", "label": "BV", "size_category": "SME"},
            ),
        ]
        pool.fetch.side_effect = [[kbo_record], obs_records]
        rows = asyncio.run(
            fetch_results_for_run(pool, _STARTED_AT, size_categories=["SME", "Large"])
        )
        assert len(rows) == 1

    def test_size_filter_none_passes_all(self) -> None:
        """size_categories=None means no filter — all rows pass regardless of size."""
        pool = AsyncMock()
        kbo_record = {"kbo_number": "0439401387"}
        obs_records = [
            _mock_record(
                field="legal_form",
                value={"code": "010", "label": "Eenmanszaak", "size_category": "Solo"},
            ),
        ]
        pool.fetch.side_effect = [[kbo_record], obs_records]
        rows = asyncio.run(fetch_results_for_run(pool, _STARTED_AT, size_categories=None))
        assert len(rows) == 1

    def test_size_filter_unknown_size_passes_through(self) -> None:
        """Companies with no legal_form observation (size_category='') pass the filter."""
        pool = AsyncMock()
        kbo_record = {"kbo_number": "0439401387"}
        obs_records = [_mock_record(field="name", value={"text": "Mystery Co"})]
        pool.fetch.side_effect = [[kbo_record], obs_records]
        rows = asyncio.run(fetch_results_for_run(pool, _STARTED_AT, size_categories=["SME"]))
        assert len(rows) == 1, "company with unknown size must pass through (don't filter unknowns)"
