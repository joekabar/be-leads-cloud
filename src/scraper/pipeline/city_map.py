"""Belgian city slug → postal code list lookup.

``lib/postcodes.toml`` is authoritative. ``city_map.toml`` (next to this file) may add
cities postcodes.toml does not define and declare aliases, but it may not override.

The precedence used to run the other way, and the curated overrides were the worse of
the pair: audited against the KBO registry, 13 of 15 of them were wrong — either short
of a city's own sub-municipalities (brugge lacked 8310 and 8380, so Assebroek,
Sint-Kruis, Zeebrugge, Lissewege and Dudzele could not be scraped at all) or reaching
into neighbouring ones (brugge included 8020, which is Oostkamp; kortrijk included
Kuurne and Harelbeke). Both directions are silent: the first loses companies that were
never fetched, the second sells a company as being in a city it is not in.

One list per city, in one file, is the invariant that keeps that from recurring.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

_MAP: dict[str, list[str]] = {}
#: alternative spelling -> canonical slug, e.g. "luik" -> "liege".
_ALIASES: dict[str, str] = {}
#: postal code -> city slug, built lazily from _MAP; only unambiguous codes are kept.
_REVERSE: dict[str, str] = {}


def _load() -> tuple[dict[str, list[str]], dict[str, str]]:
    merged: dict[str, list[str]] = {}
    aliases: dict[str, str] = {}

    # Authoritative source.
    primary = Path(__file__).parents[1] / "lib" / "postcodes.toml"
    if primary.is_file():
        with primary.open("rb") as fh:
            cities = tomllib.load(fh).get("cities", {})
        for slug, entry in cities.items():
            if not isinstance(entry, dict):
                continue
            codes = [str(c) for c in entry.get("postcodes", []) if str(c).strip()]
            if codes:
                merged[slug.lower()] = codes

    # Supplements: new cities and aliases only. An entry that redefines a city the
    # authoritative file already owns is ignored rather than applied — see the module
    # docstring for why, and test_city_map_may_not_override_postcodes_toml for the guard
    # that keeps this branch from being reached silently.
    path = Path(__file__).parent / "city_map.toml"
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    for raw_slug, v in data.items():
        if not isinstance(v, dict):
            continue
        slug = raw_slug.lower()
        target = v.get("alias_of")
        if target is not None:
            aliases[slug] = str(target).lower()
            continue
        codes = [str(c) for c in v.get("postal_codes", []) if str(c).strip()]
        if codes and slug not in merged:
            merged[slug] = codes

    return merged, aliases


def _ensure_loaded() -> None:
    global _MAP, _ALIASES
    if not _MAP:
        _MAP, _ALIASES = _load()


def get_postal_codes(city_slug: str) -> list[str] | None:
    """Return postal codes for city_slug, or None if in neither source.

    Aliases ("luik", "namen") resolve to their canonical entry, so the two spellings
    cannot drift apart and neither claims ownership of the postcodes twice.
    """
    _ensure_loaded()
    slug = city_slug.lower()
    return _MAP.get(_ALIASES.get(slug, slug))


def canonical_slug(city_slug: str) -> str | None:
    """Return the canonical slug for a spelling of a city, or None if unknown.

    Folds case, aliases ("luik" -> "liege") and stray whitespace, so values that reached
    the database before slug normalisation existed — ``run_log`` holds both "oostende"
    and "Oostende" — collapse to one city rather than being counted twice.
    """
    _ensure_loaded()
    slug = city_slug.strip().lower()
    slug = _ALIASES.get(slug, slug)
    return slug if slug in _MAP else None


def city_for_postal_code(postal_code: str) -> str | None:
    """Return the city slug a postal code belongs to, or None.

    The inverse of :func:`get_postal_codes`. goudengids listing cards frequently carry a
    postcode but no municipality — 358,414 of its 642,520 address observations, 56% — so
    the exported ``city`` column was blank for a third of rows even though the postcode
    that put them in the file was right there.

    A postcode shared by several configured cities returns None rather than guessing:
    filling in the wrong municipality is worse than leaving the column empty.
    """
    global _REVERSE
    if not _REVERSE:
        _ensure_loaded()
        owners: dict[str, set[str]] = {}
        for slug, codes in _MAP.items():
            for code in codes:
                owners.setdefault(str(code).strip(), set()).add(slug)
        _REVERSE = {code: next(iter(s)) for code, s in owners.items() if len(s) == 1}
    return _REVERSE.get(str(postal_code).strip())
