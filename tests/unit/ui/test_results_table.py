"""Unit tests for results_table helpers (no Streamlit required)."""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import MagicMock

from scraper.ui.components.results_table import (
    _missing_fields,
    _sources_compact,
    render_company_details,
    render_results_table,
)


def _install_streamlit_stub() -> MagicMock:
    """Install a MagicMock as the 'streamlit' module so render functions don't crash."""
    stub = MagicMock()
    stub.column_config = MagicMock()

    # st.columns(n) returns a list of n context-manager-capable mocks.
    class _Ctx:
        def __enter__(self) -> MagicMock:
            return MagicMock()

        def __exit__(self, *a: Any) -> None:
            return None

    stub.columns.side_effect = lambda n: [_Ctx() for _ in range(n)]
    stub.expander.return_value.__enter__ = lambda self: self
    stub.expander.return_value.__exit__ = lambda self, *a: None
    sys.modules["streamlit"] = stub
    return stub


class TestMissingFields:
    def test_full_row_returns_empty_string(self) -> None:
        row = {
            "phone": "+3232361306",
            "website": "https://x.be",
            "address": "Y",
            "founding_date": "1989-12-28",
            "function_holders": "A",
            "revenue_latest": 1000.0,
            "email": "info@x.be",
            "status": "active",
        }
        assert _missing_fields(row) == ""

    def test_empty_row_returns_all_fields(self) -> None:
        result = _missing_fields({})
        for field in ("phone", "website", "address", "founding_date", "email", "status"):
            assert field in result

    def test_empty_string_counted_as_missing(self) -> None:
        row = {"phone": "+3232361306", "email": "", "website": "https://x.be"}
        result = _missing_fields(row)
        assert "email" in result
        assert "phone" not in result
        assert "website" not in result

    def test_zero_revenue_counted_as_present(self) -> None:
        row = {"revenue_latest": 0}
        result = _missing_fields(row)
        assert "revenue_latest" not in result


class TestSourcesCompact:
    def test_empty_returns_empty_string(self) -> None:
        assert _sources_compact({}) == ""
        assert _sources_compact({"sources_count": {}}) == ""
        assert _sources_compact({"sources_count": None}) == ""

    def test_returns_sorted_source_names(self) -> None:
        row = {"sources_count": {"website": 5, "goudengids": 3, "kbo_dump": 10}}
        result = _sources_compact(row)
        assert result == "goudengids, kbo_dump, website"


class TestRenderResultsTable:
    """Smoke-test the render path with a streamlit stub to exercise branches."""

    def setup_method(self) -> None:
        self.stub = _install_streamlit_stub()

    def test_no_rows_emits_info_and_returns(self) -> None:
        render_results_table([])
        # st.info should have been called when rows is empty
        assert self.stub.info.called

    def test_renders_table_with_rows(self) -> None:
        rows = [
            {
                "kbo_number": "0439401387",
                "name": "Bellock NV",
                "phone": "+3232361306",
                "website": "https://x.be",
                "score_overall": 0.85,
            }
        ]
        # MagicMock can't be turned into a DataFrame, so we patch pandas too
        from unittest.mock import patch

        with patch("pandas.DataFrame") as fake_df:
            fake_df.return_value.columns = [
                "kbo_number",
                "name",
                "phone",
                "website",
                "score_overall",
            ]
            fake_df.return_value.to_csv.return_value = "csv"
            fake_df.return_value.__getitem__.return_value = fake_df.return_value
            render_results_table(rows)
        assert self.stub.dataframe.called
        assert self.stub.download_button.called

    def test_diagnostic_per_row_adds_columns(self) -> None:
        rows = [
            {
                "kbo_number": "0439401387",
                "name": "X",
                "phone": "",
                "website": "https://x.be",
                "sources_count": {"goudengids": 4},
                "score_overall": 0.5,
            }
        ]
        from unittest.mock import patch

        with patch("pandas.DataFrame") as fake_df:
            fake_df.return_value.columns = [
                "kbo_number",
                "name",
                "phone",
                "website",
                "score_overall",
                "missing_fields",
                "sources",
            ]
            fake_df.return_value.to_csv.return_value = "csv"
            fake_df.return_value.__getitem__.return_value = fake_df.return_value
            render_results_table(rows, show_diagnostic_per_row=True)
            # The enriched rows passed to DataFrame must include the inspector cols.
            call_arg = fake_df.call_args[0][0]
            assert "missing_fields" in call_arg[0]
            assert "sources" in call_arg[0]
            assert "phone" in call_arg[0]["missing_fields"]  # phone is empty
            assert call_arg[0]["sources"] == "goudengids"


class TestRenderCompanyDetails:
    def test_renders_without_raising_when_streamlit_stubbed(self) -> None:
        stub = _install_streamlit_stub()
        row = {
            "kbo_number": "0439401387",
            "name": "Bellock NV",
            "website_summary": "We make stuff.",
            "phones_all": "+3232361306 | +32475999930",
            "emails_all": "info@x.be",
            "founding_date": "1989-12-28",
            "status": "active",
            "nace_code": "43211",
            "nace_description": "Electrical installation",
            "function_holders_all": "Boonen Peter (director); Jane Doe",
            "sources_count": {"kbo_dump": 5, "kbopub": 2},
        }
        render_company_details(row)
        # Sanity: streamlit.markdown was called multiple times for the section headers.
        assert stub.markdown.call_count >= 4
