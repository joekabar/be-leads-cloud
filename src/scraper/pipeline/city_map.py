"""Belgian city slug → postal code list lookup.

Load once at module level from city_map.toml (next to this file).
"""

from __future__ import annotations

import tomllib
from pathlib import Path

_MAP: dict[str, list[str]] = {}


def _load() -> dict[str, list[str]]:
    path = Path(__file__).parent / "city_map.toml"
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    return {slug: list(v["postal_codes"]) for slug, v in data.items()}


def get_postal_codes(city_slug: str) -> list[str] | None:
    """Return postal codes for city_slug, or None if not in map."""
    global _MAP
    if not _MAP:
        _MAP = _load()
    return _MAP.get(city_slug.lower())
