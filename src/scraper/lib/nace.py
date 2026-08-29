"""Parse and normalise user-supplied NACE codes from the UI search parameters.

Lets an operator target NACE prefixes directly instead of being limited to the
predefined sector slugs in ``SECTOR_NACE_PREFIXES`` (``lib/sector_nace.py``).

KBO Open Data stores NACE codes **without dots** (``43211``, not ``43.21``), and the
staging filter matches with ``nace_code LIKE '<prefix>%'``. Anything entered here is
therefore reduced to bare digits and used as a prefix.
"""

from __future__ import annotations

import re

from scraper.lib.errors import InvalidNaceError

#: Separators accepted between codes in a single input box.
_SPLIT_RE = re.compile(r"[,;\s]+")

#: A normalised code: 1-5 digits. Shorter values are legitimate prefixes (e.g. "43"
#: matches all of division 43); longer than 5 is a typo, not a NACE code.
_VALID_RE = re.compile(r"^\d{1,5}$")


def normalize_nace(raw: str) -> str:
    """Return *raw* as a bare-digit NACE prefix.

    Accepts the dotted form people copy out of official tables (``43.21``) as well as
    the dotless form KBO uses. Raises InvalidNaceError on anything else.
    """
    cleaned = raw.strip().replace(".", "")
    if not _VALID_RE.match(cleaned):
        raise InvalidNaceError(raw)
    return cleaned


def parse_nace_input(raw: str) -> list[str]:
    """Split a free-text NACE box into normalised prefixes, order-preserving and unique.

    Accepts commas, semicolons, spaces and newlines as separators so the operator can
    paste a list in whatever shape they have it. An empty box yields an empty list;
    a single bad entry raises rather than being silently dropped, so a typo cannot
    quietly narrow the search.
    """
    if not raw or not raw.strip():
        return []

    seen: dict[str, None] = {}
    for token in _SPLIT_RE.split(raw.strip()):
        if not token:
            continue
        seen.setdefault(normalize_nace(token), None)
    return list(seen)
