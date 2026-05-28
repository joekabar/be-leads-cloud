"""Unit tests for scraper.ui.components.pickers helpers."""

from __future__ import annotations

import time
from pathlib import Path

from scraper.ui.components.pickers import find_kbo_zips, load_city_options, load_sector_options


class TestFindKboZips:
    def test_returns_empty_list_when_folder_missing(self, tmp_path: Path) -> None:
        missing = tmp_path / "does_not_exist"
        assert find_kbo_zips(missing) == []

    def test_returns_empty_list_when_folder_empty(self, tmp_path: Path) -> None:
        empty = tmp_path / "KBO_zip"
        empty.mkdir()
        assert find_kbo_zips(empty) == []

    def test_returns_only_matching_zip_names(self, tmp_path: Path) -> None:
        d = tmp_path / "KBO_zip"
        d.mkdir()
        (d / "KboOpenData_0360_2026_05_15_Full.zip").write_bytes(b"x")
        (d / "random.zip").write_bytes(b"x")
        (d / "notes.txt").write_text("x")
        result = find_kbo_zips(d)
        names = [p.name for p, _ in result]
        assert names == ["KboOpenData_0360_2026_05_15_Full.zip"]

    def test_label_includes_parsed_date_and_extract_type(self, tmp_path: Path) -> None:
        d = tmp_path / "KBO_zip"
        d.mkdir()
        (d / "KboOpenData_0360_2026_05_15_Full.zip").write_bytes(b"x")
        (d / "KboOpenData_0361_2026_06_15_Update.zip").write_bytes(b"x")
        result = {p.name: label for p, label in find_kbo_zips(d)}
        assert result["KboOpenData_0360_2026_05_15_Full.zip"] == "2026-05-15 (Full)"
        assert result["KboOpenData_0361_2026_06_15_Update.zip"] == "2026-06-15 (Update)"

    def test_sorted_newest_first_by_mtime(self, tmp_path: Path) -> None:
        d = tmp_path / "KBO_zip"
        d.mkdir()
        older = d / "KboOpenData_0359_2026_04_15_Full.zip"
        newer = d / "KboOpenData_0360_2026_05_15_Full.zip"
        older.write_bytes(b"x")
        time.sleep(0.05)
        newer.write_bytes(b"x")
        result = find_kbo_zips(d)
        assert result[0][0].name == newer.name, "newest mtime must come first"
        assert result[1][0].name == older.name


class TestLoadCityOptions:
    def test_returns_tuples_with_slug_display_postcodes(self) -> None:
        options = load_city_options()
        assert len(options) > 0
        for slug, display, postcodes in options:
            assert slug
            assert display
            assert isinstance(postcodes, list)
            assert all(isinstance(p, str) and p for p in postcodes)

    def test_sorted_by_display_name(self) -> None:
        options = load_city_options()
        displays = [d for _, d, _ in options]
        assert displays == sorted(displays)

    def test_oostende_present_with_8400(self) -> None:
        options = load_city_options()
        by_slug = {slug: (display, postcodes) for slug, display, postcodes in options}
        assert "oostende" in by_slug
        _, postcodes = by_slug["oostende"]
        assert "8400" in postcodes

    def test_antwerpen_present_with_2000(self) -> None:
        options = load_city_options()
        by_slug = {slug: (display, postcodes) for slug, display, postcodes in options}
        assert "antwerpen" in by_slug
        _, postcodes = by_slug["antwerpen"]
        assert "2000" in postcodes


class TestLoadSectorOptions:
    def test_returns_non_empty_list(self) -> None:
        options = load_sector_options()
        assert len(options) > 0

    def test_each_entry_is_slug_display_tuple(self) -> None:
        options = load_sector_options()
        for slug, display in options:
            assert isinstance(slug, str)
            assert isinstance(display, str)

    def test_sorted_by_display(self) -> None:
        options = load_sector_options()
        displays = [d for _, d in options]
        assert displays == sorted(displays)

    def test_elektriciens_present(self) -> None:
        options = load_sector_options()
        slugs = [s for s, _ in options]
        assert "elektriciens" in slugs


class TestLoadCityOptionsEdgeCases:
    def test_non_dict_entry_skipped(self) -> None:
        from unittest.mock import mock_open, patch

        toml_data = {
            "cities": {
                "bad_entry": "not-a-dict",
                "gent": {"display": "Gent", "postcodes": ["9000"]},
            }
        }

        with patch("scraper.ui.components.pickers._POSTCODES_TOML") as mock_path:
            mock_path.open = mock_open()
            with patch("tomllib.load", return_value=toml_data):
                options = load_city_options()
        slugs = [s for s, _, _ in options]
        assert "bad_entry" not in slugs

    def test_empty_postcodes_skipped(self) -> None:
        from unittest.mock import mock_open, patch

        toml_data = {
            "cities": {
                "empty_city": {"display": "Empty", "postcodes": []},
                "gent": {"display": "Gent", "postcodes": ["9000"]},
            }
        }

        with patch("scraper.ui.components.pickers._POSTCODES_TOML") as mock_path:
            mock_path.open = mock_open()
            with patch("tomllib.load", return_value=toml_data):
                options = load_city_options()
        slugs = [s for s, _, _ in options]
        assert "empty_city" not in slugs
        assert "gent" in slugs


class TestFindKboZipsSubdir:
    def test_subdirectory_is_skipped(self, tmp_path: Path) -> None:
        d = tmp_path / "KBO_zip"
        d.mkdir()
        subdir = d / "subdir"
        subdir.mkdir()
        (d / "KboOpenData_0360_2026_05_15_Full.zip").write_bytes(b"x")
        result = find_kbo_zips(d)
        assert len(result) == 1


class TestRenderFunctionsWithMockedSt:
    def test_render_sector_picker_returns_string(self) -> None:
        import sys
        from unittest.mock import MagicMock

        st = MagicMock()
        st.selectbox.return_value = 0
        orig = sys.modules.get("streamlit")
        sys.modules["streamlit"] = st
        try:
            from scraper.ui.components.pickers import render_sector_picker

            result = render_sector_picker()
            assert isinstance(result, str)
        finally:
            if orig is None:
                sys.modules.pop("streamlit", None)
            else:
                sys.modules["streamlit"] = orig

    def test_render_city_input_returns_string(self) -> None:
        import sys
        from unittest.mock import MagicMock

        st = MagicMock()
        st.text_input.return_value = "Gent"
        orig = sys.modules.get("streamlit")
        sys.modules["streamlit"] = st
        try:
            from scraper.ui.components.pickers import render_city_input

            result = render_city_input("Gent")
            assert result == "Gent"
        finally:
            if orig is None:
                sys.modules.pop("streamlit", None)
            else:
                sys.modules["streamlit"] = orig
