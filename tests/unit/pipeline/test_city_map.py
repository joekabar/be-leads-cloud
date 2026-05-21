from __future__ import annotations

from scraper.pipeline.city_map import get_postal_codes


class TestGetPostalCodes:
    def test_known_city_returns_list_with_codes(self) -> None:
        result = get_postal_codes("antwerpen")
        assert result is not None
        assert "2000" in result
        assert len(result) > 1

    def test_unknown_city_returns_none(self) -> None:
        assert get_postal_codes("nonexistent_city_xyz") is None

    def test_case_insensitive(self) -> None:
        lower = get_postal_codes("antwerpen")
        upper = get_postal_codes("ANTWERPEN")
        assert lower == upper
