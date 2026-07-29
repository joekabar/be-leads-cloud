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


class TestFallsBackToPostcodesToml:
    """city_map.toml is a subset of the cities the UI offers.

    The UI picker lists cities from lib/postcodes.toml, so a city selectable there but
    absent from city_map.toml resolved to None — which silently disabled goudengids
    city filtering for it (observed live: 'goudengids_city_not_in_postcode_map
    city=oostende').
    """

    def test_oostende_resolves(self) -> None:
        result = get_postal_codes("oostende")
        assert result is not None, "oostende is offered by the UI and must resolve"
        assert "8400" in result

    def test_every_ui_city_resolves(self) -> None:
        from scraper.ui.components.pickers import load_city_options

        missing = [slug for slug, _, _ in load_city_options() if not get_postal_codes(slug)]
        assert missing == [], f"cities selectable in the UI with no postcodes: {missing}"

    def test_city_map_still_wins_when_present(self) -> None:
        """The curated map stays authoritative where it has an entry."""
        assert "2000" in (get_postal_codes("antwerpen") or [])
