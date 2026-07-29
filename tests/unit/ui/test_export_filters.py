"""Selection filters for export_csv: postcode, required field, revenue ceiling.

The export previously had exactly two modes — every KBO in companies_current, or one
run_id. Neither answers "small businesses in this city that have a phone", which is the
normal shape of a lead request, so the filters are built into the selection SQL rather
than applied afterwards in Python: the unfiltered set is 1.96M KBOs.

The revenue ceiling deliberately KEEPS companies with no published revenue. Micro
enterprises file abbreviated accounts and legitimately report no turnover; dropping them
would discard most of a small-business list.
"""

from __future__ import annotations

from typing import Any

import pytest

from scraper.ui.export import build_selection_sql


class TestBuildSelectionSql:
    def test_no_filters_selects_whole_view(self) -> None:
        sql, params = build_selection_sql()
        assert "DISTINCT kbo_number FROM companies_current" in sql
        assert params == []

    def test_run_id_takes_precedence(self) -> None:
        sql, params = build_selection_sql(run_id="a-run-id")
        assert "observations WHERE run_id" in sql
        assert params == ["a-run-id"]

    def test_postcodes_filter_reads_address_jsonb(self) -> None:
        sql, params = build_selection_sql(postcodes=["8400", "8401"])
        # postal_code lives inside the address JSONB, not in its own column.
        assert "'address'" in sql
        assert "postal_code" in sql
        assert params == [["8400", "8401"]]

    def test_require_fields_counts_matching_fields(self) -> None:
        sql, params = build_selection_sql(require_fields=["phone"])
        assert "count(DISTINCT" in sql
        assert "= 1" in sql
        assert params == [["phone"]]

    def test_multiple_required_fields_all_must_be_present(self) -> None:
        sql, _ = build_selection_sql(require_fields=["phone", "email"])
        # A company must have every requested field, not any of them.
        assert "= 2" in sql

    def test_max_revenue_excludes_only_proven_larger(self) -> None:
        sql, params = build_selection_sql(max_revenue=2_000_000)
        assert "NOT EXISTS" in sql
        assert "revenue_" in sql
        assert params == [2_000_000]

    def test_filters_combine(self) -> None:
        sql, params = build_selection_sql(
            postcodes=["8400"], require_fields=["phone"], max_revenue=2_000_000
        )
        assert "postal_code" in sql
        assert "EXISTS" in sql
        assert "NOT EXISTS" in sql
        assert params == [["8400"], ["phone"], 2_000_000]

    def test_params_are_numbered_in_order(self) -> None:
        sql, _ = build_selection_sql(
            postcodes=["8400"], require_fields=["phone"], max_revenue=2_000_000
        )
        for n in (1, 2, 3):
            assert f"${n}" in sql

    def test_empty_postcodes_is_not_a_filter(self) -> None:
        """An unknown city resolves to no postcodes; that must not silently
        select every company in the country."""
        with pytest.raises(ValueError, match="postcodes"):
            build_selection_sql(postcodes=[])

    def test_empty_require_fields_is_not_a_filter(self) -> None:
        sql, params = build_selection_sql(require_fields=[])
        assert "EXISTS" not in sql
        assert params == []


class TestResolveCityPostcodes:
    def test_known_city_returns_postcodes(self) -> None:
        from scraper.ui.export import resolve_city_postcodes

        assert resolve_city_postcodes(["oostende"]) == ["8400", "8401"]

    def test_multiple_cities_are_unioned(self) -> None:
        from scraper.ui.export import resolve_city_postcodes

        result = resolve_city_postcodes(["oostende", "brugge"])
        assert "8400" in result
        assert "8000" in result

    def test_unknown_city_raises_rather_than_matching_nothing(self) -> None:
        from scraper.ui.export import resolve_city_postcodes

        with pytest.raises(ValueError, match="Unknown city"):
            resolve_city_postcodes(["not-a-real-city"])

    def test_result_is_deduplicated(self) -> None:
        from scraper.ui.export import resolve_city_postcodes

        result = resolve_city_postcodes(["oostende", "oostende"])
        assert len(result) == len(set(result))


class TestExportCsvUsesFilters:
    async def test_export_passes_filters_into_selection(self) -> None:
        """export_csv must build its KBO list from the filtered SQL, not fetch
        everything and filter in Python."""
        from unittest.mock import MagicMock

        from scraper.ui.export import export_csv

        seen: list[str] = []
        pool = MagicMock()

        async def _fetch(sql: str, *args: Any, **kwargs: Any) -> list[Any]:
            seen.append(sql)
            return []

        pool.fetch = _fetch

        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as d:
            await export_csv(
                pool,
                Path(d) / "out.csv",
                postcodes=["8400"],
                require_fields=["phone"],
                max_revenue=2_000_000,
            )

        assert seen, "no query was issued"
        assert "postal_code" in seen[0]
        assert "NOT EXISTS" in seen[0]
