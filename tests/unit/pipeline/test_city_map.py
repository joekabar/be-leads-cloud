from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from scraper.pipeline import city_map
from scraper.pipeline.city_map import city_for_postal_code, get_postal_codes

_CITY_MAP_TOML = Path(city_map.__file__).parent / "city_map.toml"
_POSTCODES_TOML = Path(city_map.__file__).parents[1] / "lib" / "postcodes.toml"


def _postcodes_toml() -> dict[str, list[str]]:
    with _POSTCODES_TOML.open("rb") as fh:
        cities = tomllib.load(fh)["cities"]
    return {slug: [str(p) for p in entry["postcodes"]] for slug, entry in cities.items()}


class TestGetPostalCodes:
    def test_known_city_returns_list_with_codes(self) -> None:
        result = get_postal_codes("antwerpen")
        assert result is not None
        assert "2000" in result
        assert len(result) > 1

    def test_unknown_city_returns_none(self) -> None:
        assert get_postal_codes("nonexistent_city_xyz") is None

    def test_case_insensitive(self) -> None:
        assert get_postal_codes("antwerpen") == get_postal_codes("ANTWERPEN")


class TestFallsBackToPostcodesToml:
    """city_map.toml is a supplement to the cities the UI offers.

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


class TestPostcodesTomlIsAuthoritative:
    """The precedence used to run the other way, and it silently corrupted the data.

    city_map.toml carried a second curated postcode list that OVERRODE postcodes.toml.
    An audit against the KBO registry found 13 of 15 curated cities wrong. Brugge is the
    case that surfaced it: the override said ["8000","8020","8200"], so 8310
    (Assebroek, Sint-Kruis) and 8380 (Zeebrugge, Lissewege, Dudzele) were unreachable —
    three sectors in the 2026-08-21 run fetched cards and wrote zero observations because
    every card was rejected as out-of-city — while 8020 (Oostkamp, a different
    municipality) was scraped and exported as if it were Brugge.
    """

    def test_city_map_may_not_override_postcodes_toml(self) -> None:
        with _CITY_MAP_TOML.open("rb") as fh:
            supplements = tomllib.load(fh)
        overlapping = set(supplements) & set(_postcodes_toml())
        offenders = {slug for slug in overlapping if "postal_codes" in supplements[slug]}
        assert offenders == set(), (
            "city_map.toml redefines postcodes for cities postcodes.toml already owns: "
            f"{sorted(offenders)}. It may only add new cities or declare alias_of."
        )

    def test_brugge_covers_its_submunicipalities(self) -> None:
        codes = get_postal_codes("brugge") or []
        assert "8310" in codes, "Assebroek and Sint-Kruis are Brugge"
        assert "8380" in codes, "Zeebrugge, Lissewege and Dudzele are Brugge"

    def test_brugge_excludes_oostkamp(self) -> None:
        assert "8020" not in (get_postal_codes("brugge") or []), "8020 is Oostkamp"


class TestNeighbouringMunicipalitiesAreNotTheCity:
    """A slug covers one legal municipality, not the surrounding ones.

    Each code below sat in the curated override and pulled a separate municipality's
    companies into the city's scrape and its export.
    """

    @pytest.mark.parametrize(
        ("city", "code", "belongs_to"),
        [
            ("kortrijk", "8520", "Kuurne"),
            ("kortrijk", "8530", "Harelbeke"),
            ("mechelen", "2850", "Boom"),
            ("mechelen", "2830", "Willebroek"),
            ("sint-niklaas", "9120", "Beveren"),
            ("sint-niklaas", "9160", "Lokeren"),
            ("aalst", "9340", "Lede"),
            ("aalst", "9400", "Ninove"),
            ("leuven", "3020", "Herent"),
            ("leuven", "3030", "no Belgian municipality at all"),
            ("liege", "4040", "Herstal"),
            ("hasselt", "3520", "Zonhoven"),
            ("hasselt", "3530", "Houthalen-Helchteren"),
            ("hasselt", "3720", "Kortessem"),
            ("mons", "7060", "Soignies"),
            ("charleroi", "6140", "Fontaine-l'Évêque"),
            ("oostende", "8401", "no Belgian municipality at all"),
        ],
    )
    def test_code_excluded(self, city: str, code: str, belongs_to: str) -> None:
        assert code not in (get_postal_codes(city) or []), f"{code} is {belongs_to}, not {city}"


class TestMissingSubmunicipalitiesRestored:
    @pytest.mark.parametrize(
        ("city", "code"),
        [
            ("namur", "5100"),  # Jambes — 7,409 registry entities
            ("namur", "5101"),  # Naninne, Wépion, Wierde, Dave
            ("mons", "7033"),  # Cuesmes
            ("mons", "7022"),  # Hyon
            ("charleroi", "6061"),  # Montignies-sur-Sambre
            ("charleroi", "6043"),  # Ransart
            ("antwerpen", "2150"),  # Borsbeek, merged into Antwerpen 2025-01-01
            ("aalst", "9310"),  # Moorsel, Baardegem, Herdersem
            ("mechelen", "2812"),  # Muizen
            ("gent", "9052"),  # Zwijnaarde
        ],
    )
    def test_code_present(self, city: str, code: str) -> None:
        assert code in (get_postal_codes(city) or []), f"{code} belongs to {city}"


class TestAliases:
    """Alternative spellings resolve to one canonical entry rather than duplicating it.

    They used to be separate entries holding a copy of the same list. Two owners for one
    postcode makes city_for_postal_code() return None (it refuses to guess), so the
    export's `city` column came out blank for every Gent, Liège, Mons and Namur row.
    """

    @pytest.mark.parametrize(
        ("alias", "canonical"),
        [("ghent", "gent"), ("luik", "liege"), ("bergen", "mons"), ("namen", "namur")],
    )
    def test_alias_resolves_to_canonical(self, alias: str, canonical: str) -> None:
        assert get_postal_codes(alias) == get_postal_codes(canonical)

    @pytest.mark.parametrize("code", ["9000", "9050", "4000", "7000", "5000"])
    def test_alias_does_not_block_reverse_lookup(self, code: str) -> None:
        assert city_for_postal_code(code) is not None, (
            f"{code} resolved to no city, which blanks the export's city column"
        )

    def test_reverse_lookup_maps_to_canonical_slug(self) -> None:
        assert city_for_postal_code("9000") == "gent"
        assert city_for_postal_code("4000") == "liege"


class TestNoPostcodeBelongsToTwoCities:
    def test_codes_are_unique_across_cities(self) -> None:
        owners: dict[str, list[str]] = {}
        for slug, codes in _postcodes_toml().items():
            for code in codes:
                owners.setdefault(code, []).append(slug)
        shared = {code: sorted(s) for code, s in owners.items() if len(s) > 1}
        assert shared == {}, f"postcodes claimed by more than one city: {shared}"
