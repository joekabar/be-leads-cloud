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
