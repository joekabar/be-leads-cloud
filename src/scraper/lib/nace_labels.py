"""NACE code → human-readable description, from the official KBO code table.

``nace_code`` observations carry only a bare number (``{"code": "43320", "version":
"2025"}``), which tells a reader nothing about what the company does. The KBO Open Data
ZIP ships the official descriptions in ``code.csv``; ``scripts/generate_nace_labels.py``
extracts them into ``nace_labels.toml`` next to this module.

Bundled rather than staged on purpose: the ``kbo_stage_*`` tables are UNLOGGED, so crash
recovery empties them, and an export joined against them would silently lose the column.
These labels change only when a new NACE version is published.
"""

from __future__ import annotations

import tomllib
from functools import lru_cache

from scraper.lib.data_paths import NACE_LABELS_TOML

#: Versions observed in production, newest first. 2025 covers ~1.23M companies,
#: 2008 ~17k and 2003 ~14k.
_DEFAULT_VERSION = "2025"


@lru_cache(maxsize=1)
def load_nace_labels() -> dict[str, dict[str, str]]:
    """Return ``{"nace2025": {code: description}, ...}``, parsed once per process."""
    with NACE_LABELS_TOML.open("rb") as fh:
        data = tomllib.load(fh)
    return {k: v for k, v in data.items() if isinstance(v, dict)}


def nace_label(code: str | None, version: str | None = None) -> str | None:
    """Return the description for *code*, or ``None`` when nothing matches.

    Lookup is longest-prefix within a single version, mirroring
    ``scoring/hv_prior.py``: a code with no exact entry resolves to its parent group
    (``01999`` → the ``01`` group) rather than to nothing, and codes longer than five
    characters — 15 rows in production carry six or seven — are truncated down to a
    known prefix.

    Never falls back to another NACE version: codes are reused with different meanings
    across taxonomies, so a cross-version match could attach a plainly wrong description.
    An unrecognised *version* uses the current one rather than failing.
    """
    if not code:
        return None
    code = code.strip()
    if not code:
        return None

    labels = load_nace_labels()
    table = labels.get(f"nace{version}") if version else None
    if table is None:
        table = labels.get(f"nace{_DEFAULT_VERSION}", {})

    for length in range(len(code), 0, -1):
        found = table.get(code[:length])
        if found:
            return found
    return None
