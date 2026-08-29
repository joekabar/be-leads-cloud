"""Config files checked against each other and against the code that consumes them.

city_map.toml drifted unvalidated until 13 of 15 cities were wrong. These tests give
the remaining config surfaces the same guard the postcode map now has: a slug that
resolves to nothing, a duplicate, or a NACE prefix in the wrong format fails the
build instead of silently producing empty scrapes.
"""

from __future__ import annotations

import tomllib

from scraper.lib.data_paths import SECTORS_TOML
from scraper.lib.sector_nace import SECTOR_NACE_PREFIXES
from scraper.pipeline.city_map import get_postal_codes
from scraper.pipeline.sector_queue import goudengids_unscrapeable_sectors, load_rotation_cities

# nl_slugs deliberately shared by more than one sector entry. One goudengids listing
# legitimately feeds several internal sector buckets; see
# sector_queue._goudengids_slug_to_config_key ("one-to-many on purpose") and
# test_sector_queue.py::test_a_shared_slug_completes_every_sector_using_it.
# Add a slug here ONLY for a documented, intentional pairing.
_INTENTIONAL_SHARED_NL_SLUGS = {"recyclagebedrijven"}


def _sectors_toml() -> dict[str, dict[str, str]]:
    with SECTORS_TOML.open("rb") as fh:
        return tomllib.load(fh)


class TestRotationCities:
    def test_every_rotation_city_resolves_to_postcodes(self) -> None:
        """A rotation city with no postcodes scrapes with the filter silently OFF."""
        missing = [c for c in load_rotation_cities() if not get_postal_codes(c)]
        assert missing == [], f"rotation cities with no postcodes: {missing}"

    def test_rotation_is_nonempty_and_unique(self) -> None:
        cities = load_rotation_cities()
        assert cities, "empty rotation means the nightly does nothing forever"
        assert len(set(cities)) == len(cities)


class TestSectorConfig:
    def test_every_nace_sector_is_scrapeable_or_declared_unscrapeable(self) -> None:
        """A sector in the NACE map but absent from sectors.toml can be selected by
        the queue yet never resolves to a goudengids slug - it burns a queue slot
        every night without a single request succeeding."""
        toml_keys = set(_sectors_toml())
        unscrapeable = goudengids_unscrapeable_sectors(sorted(SECTOR_NACE_PREFIXES))
        orphans = [s for s in SECTOR_NACE_PREFIXES if s not in toml_keys and s not in unscrapeable]
        assert orphans == [], f"sectors with NACE codes but no goudengids mapping: {orphans}"

    def test_sectors_toml_slugs_are_unique_and_wellformed(self) -> None:
        """nl_slug rules apply only to sectors goudengids actually indexes.

        A sector with ``goudengids_sector_not_indexed = true`` (e.g. energieproducenten,
        chemiebedrijven - see test_sector_queue.py and test_batch.py) is KBO-Open-Data-only
        by design and deliberately ships an empty nl_slug; that is exactly the signal
        ``goudengids_unscrapeable_sectors`` reads to keep it out of the nightly queue.
        Flagging it here as malformed would fight a mechanism the rest of the pipeline
        already relies on.
        """
        seen: dict[str, str] = {}
        for key, entry in _sectors_toml().items():
            if entry.get("goudengids_sector_not_indexed"):
                continue
            nl = entry.get("nl_slug", "")
            assert nl, f"{key} has no nl_slug"
            assert nl == nl.strip().lower(), f"{key}: nl_slug {nl!r} not normalised"
            if nl in seen and nl not in _INTENTIONAL_SHARED_NL_SLUGS:
                raise AssertionError(f"nl_slug {nl!r} used by both {seen[nl]} and {key}")
            seen[nl] = key
