"""Sector + city pickers that read from sectors.toml."""

from __future__ import annotations

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
