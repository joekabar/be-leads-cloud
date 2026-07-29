"""Goudengids returns nationwide results when a city has few matches.

Those cards were being stored under a run tagged with the requested city, silently
mislabelling out-of-area leads. Every card carries a postal code (even when the city
name is blank), so the postcode is the reliable filter.
"""

from __future__ import annotations

from scraper.sources.goudengids.ingester import card_in_city


class TestCardInCity:
    def test_keeps_card_with_matching_postcode(self) -> None:
        assert card_in_city("8400", {"8400", "8450"}) is True

    def test_drops_card_outside_city(self) -> None:
        assert card_in_city("2812", {"8400", "8450"}) is False

    def test_drops_card_without_postcode(self) -> None:
        """Unverifiable location must not be assumed in-city."""
        assert card_in_city(None, {"8400"}) is False
        assert card_in_city("", {"8400"}) is False
        assert card_in_city("   ", {"8400"}) is False

    def test_no_allowed_set_disables_filtering(self) -> None:
        """An unmapped city must not silently discard every result."""
        assert card_in_city("2812", set()) is True
        assert card_in_city(None, set()) is True

    def test_ignores_surrounding_whitespace(self) -> None:
        assert card_in_city(" 8400 ", {"8400"}) is True

    def test_matches_are_exact_not_prefix(self) -> None:
        """8400 must not match 8401 — postcodes are discrete, not prefixes."""
        assert card_in_city("8401", {"8400"}) is False
