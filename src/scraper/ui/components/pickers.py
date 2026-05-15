"""Sector + city pickers that read from sectors.toml."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

_SECTORS_TOML = (
    Path(__file__).parents[4]
    / ".claude"
    / "skills"
    / "goudengids-listing"
    / "references"
    / "sectors.toml"
)

_KBO_ZIP_DIR = Path(__file__).parents[4] / "KBO_zip"
_KBO_ZIP_RE = re.compile(
    r"^KboOpenData_\d+_(\d{4})_(\d{2})_(\d{2})_(Full|Update)\.zip$",
    re.IGNORECASE,
)


def find_kbo_zips(base_dir: Path | None = None) -> list[tuple[Path, str]]:
    """Return [(zip_path, display_label), ...] sorted by mtime desc.

    Display label format: "YYYY-MM-DD (Full|Update)".
    Returns [] when the folder is missing, empty, or has no matching files.
    """
    folder = base_dir if base_dir is not None else _KBO_ZIP_DIR
    if not folder.is_dir():
        return []
    matches: list[tuple[Path, str, float]] = []
    for p in folder.iterdir():
        if not p.is_file():
            continue
        m = _KBO_ZIP_RE.match(p.name)
        if not m:
            continue
        label = f"{m.group(1)}-{m.group(2)}-{m.group(3)} ({m.group(4).title()})"
        matches.append((p, label, p.stat().st_mtime))
    matches.sort(key=lambda t: t[2], reverse=True)
    return [(p, label) for p, label, _ in matches]


def load_sector_options() -> list[tuple[str, str]]:
    """Return [(nl_slug, display_name), ...] sorted by display name."""
    with _SECTORS_TOML.open("rb") as fh:
        data: dict[str, Any] = tomllib.load(fh)
    options: list[tuple[str, str]] = []
    for entry in data.values():
        if isinstance(entry, dict) and "nl_slug" in entry:
            slug = str(entry["nl_slug"])
            display = str(entry.get("display", slug))
            options.append((slug, display))
    return sorted(options, key=lambda x: x[1])


def render_sector_picker() -> str:
    """Render selectbox. Returns selected NL slug."""
    import streamlit as st

    options = load_sector_options()
    labels = [f"{display} ({slug})" for slug, display in options]
    slugs = [slug for slug, _ in options]
    idx = st.selectbox("Sector", range(len(labels)), format_func=lambda i: labels[i])
    return str(slugs[idx])


def render_city_input(default: str = "Antwerpen") -> str:
    import streamlit as st

    return str(st.text_input("City", value=default))
