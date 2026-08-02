"""Belgian city slug → postal code list lookup.

Loaded once from ``city_map.toml`` (next to this file), with ``lib/postcodes.toml``
as a fallback. The two files drifted: the UI city picker lists cities from
postcodes.toml, so a city offered there but missing from city_map.toml resolved to
None — which silently disabled goudengids city filtering for it. Merging the two
means every selectable city resolves, while the curated city_map entries stay
authoritative where they exist.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

_MAP: dict[str, list[str]] = {}
#: postal code -> city slug, built lazily from _MAP; only unambiguous codes are kept.
_REVERSE: dict[str, str] = {}


def _load() -> dict[str, list[str]]:
    merged: dict[str, list[str]] = {}

    # Fallback source first so curated city_map entries overwrite it.
    fallback = Path(__file__).parents[1] / "lib" / "postcodes.toml"
    if fallback.is_file():
        with fallback.open("rb") as fh:
            cities = tomllib.load(fh).get("cities", {})
        for slug, entry in cities.items():
            if not isinstance(entry, dict):
                continue
            codes = [str(c) for c in entry.get("postcodes", []) if str(c).strip()]
            if codes:
                merged[slug.lower()] = codes

    path = Path(__file__).parent / "city_map.toml"
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    for slug, v in data.items():
        merged[slug.lower()] = list(v["postal_codes"])

    return merged


def get_postal_codes(city_slug: str) -> list[str] | None:
    """Return postal codes for city_slug, or None if in neither source."""
    global _MAP
    if not _MAP:
        _MAP = _load()
    return _MAP.get(city_slug.lower())


def city_for_postal_code(postal_code: str) -> str | None:
    """Return the city slug a postal code belongs to, or None.

    The inverse of :func:`get_postal_codes`. goudengids listing cards frequently carry a
    postcode but no municipality — 358,414 of its 642,520 address observations, 56% — so
    the exported ``city`` column was blank for a third of rows even though the postcode
    that put them in the file was right there.

    A postcode shared by several configured cities returns None rather than guessing:
    filling in the wrong municipality is worse than leaving the column empty.
    """
    global _MAP, _REVERSE
    if not _REVERSE:
        if not _MAP:
            _MAP = _load()
        owners: dict[str, set[str]] = {}
        for slug, codes in _MAP.items():
            for code in codes:
                owners.setdefault(str(code).strip(), set()).add(slug)
        _REVERSE = {code: next(iter(s)) for code, s in owners.items() if len(s) == 1}
    return _REVERSE.get(str(postal_code).strip())
