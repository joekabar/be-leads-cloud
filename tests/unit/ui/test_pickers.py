"""Unit tests for scraper.ui.components.pickers helpers."""

from __future__ import annotations

import time
from pathlib import Path

from scraper.ui.components.pickers import find_kbo_zips, load_city_options


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
