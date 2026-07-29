"""Unit tests for _build_filter_set NACE prefix matching."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from scraper.sources.kbo_dump.ingester import _build_filter_set
from scraper.sources.kbo_dump.parser import ActivityRow, AddressRow


def _activity(entity: str, nace: str) -> ActivityRow:
    return ActivityRow(
        entity_number=entity,
        activity_group="",
        nace_version="2008",
        nace_code=nace,
        classification="",
    )


def _address(entity: str, nl: str = "", fr: str = "") -> AddressRow:
    return AddressRow(
        entity_number=entity,
        type_of_address="",
        zipcode=None,
        municipality_nl=nl,
        municipality_fr=fr,
        street_nl=None,
        street_fr=None,
        house_number=None,
        box=None,
    )


_FAKE_ZIP = Path("fake.zip")


class TestBuildFilterSetNacePrefix:
    def test_exact_5digit_match(self) -> None:
        """A 5-digit filter term matches the exact NACE code."""
        activities = [_activity("0001", "62019"), _activity("0002", "47110")]
        with (
            patch(
                "scraper.sources.kbo_dump.ingester.iter_activities", return_value=iter(activities)
            ),
            patch("scraper.sources.kbo_dump.ingester.iter_addresses", return_value=iter([])),
        ):
            result = _build_filter_set(_FAKE_ZIP, sector_filter=["62019"], city_filter=None)
        assert result == {"0001"}

    def test_3digit_prefix_matches_dotless_5digit_code(self) -> None:
        """Prefix '620' must match dotless codes '62019', '62090', '62010', etc."""
        activities = [
            _activity("0001", "62019"),
            _activity("0002", "62090"),
            _activity("0003", "63110"),  # different prefix
            _activity("0004", "47110"),
        ]
        with (
            patch(
                "scraper.sources.kbo_dump.ingester.iter_activities", return_value=iter(activities)
            ),
            patch("scraper.sources.kbo_dump.ingester.iter_addresses", return_value=iter([])),
        ):
            result = _build_filter_set(_FAKE_ZIP, sector_filter=["620"], city_filter=None)
        assert result == {"0001", "0002"}

    def test_multiple_prefixes_union(self) -> None:
        """Providing ['620', '631'] captures entities matching either prefix."""
        activities = [
            _activity("0001", "62019"),
            _activity("0002", "63110"),
            _activity("0003", "58290"),
            _activity("0004", "47110"),  # no match
        ]
        with (
            patch(
                "scraper.sources.kbo_dump.ingester.iter_activities", return_value=iter(activities)
            ),
            patch("scraper.sources.kbo_dump.ingester.iter_addresses", return_value=iter([])),
        ):
            result = _build_filter_set(_FAKE_ZIP, sector_filter=["620", "631"], city_filter=None)
        assert result == {"0001", "0002"}

    def test_no_filter_returns_none(self) -> None:
        """Both filters None → function returns None (caller emits everything)."""
        result = _build_filter_set(_FAKE_ZIP, sector_filter=None, city_filter=None)
        assert result is None

    def test_sector_and_city_intersection(self) -> None:
        """When both filters are active, result is their intersection."""
        activities = [
            _activity("0001", "62019"),  # IT in Brugge
            _activity("0002", "62090"),  # IT in Gent
            _activity("0003", "47110"),  # retail in Brugge
        ]
        addresses = [
            _address("0001", nl="Brugge"),
            _address("0002", nl="Gent"),
            _address("0003", nl="Brugge"),
        ]
        with (
            patch(
                "scraper.sources.kbo_dump.ingester.iter_activities", return_value=iter(activities)
            ),
            patch("scraper.sources.kbo_dump.ingester.iter_addresses", return_value=iter(addresses)),
        ):
            result = _build_filter_set(_FAKE_ZIP, sector_filter=["620"], city_filter=["brugge"])
        assert result == {"0001"}

    def test_city_only_filter_no_sector(self) -> None:
        """Lines 152-156: city filter without sector filter (else branch)."""
        addresses = [
            _address("0001", nl="Brussel"),
            _address("0002", nl="Gent"),
        ]
        with (
            patch("scraper.sources.kbo_dump.ingester.iter_activities", return_value=iter([])),
            patch("scraper.sources.kbo_dump.ingester.iter_addresses", return_value=iter(addresses)),
        ):
            result = _build_filter_set(_FAKE_ZIP, sector_filter=None, city_filter=["brussel"])
        assert result == {"0001"}

    def test_city_only_filter_fr_municipality(self) -> None:
        """City filter matches FR municipality name."""
        addresses = [
            _address("0001", fr="Bruxelles"),
            _address("0002", nl="Gent"),
        ]
        with (
            patch("scraper.sources.kbo_dump.ingester.iter_activities", return_value=iter([])),
            patch("scraper.sources.kbo_dump.ingester.iter_addresses", return_value=iter(addresses)),
        ):
            result = _build_filter_set(_FAKE_ZIP, sector_filter=None, city_filter=["bruxelles"])
        assert result == {"0001"}
