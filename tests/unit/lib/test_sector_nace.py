"""SECTOR_NACE_PREFIXES has a public home.

It was a private constant in pipeline/orchestrator.py imported by six modules across
layers — the same two-owners drift pattern that let city_map.toml and postcodes.toml
diverge until 13 of 15 cities were wrong.
"""

from __future__ import annotations

import re

from scraper.lib.sector_nace import SECTOR_NACE_PREFIXES


class TestSectorNacePrefixes:
    def test_is_nonempty_mapping(self) -> None:
        assert len(SECTOR_NACE_PREFIXES) > 50
        assert SECTOR_NACE_PREFIXES["elektriciens"] == ["4321"]

    def test_orchestrator_alias_is_the_same_object(self) -> None:
        """Back-compat: the old private name must not become a second copy."""
        from scraper.pipeline.orchestrator import _SECTOR_NACE_PREFIXES

        assert _SECTOR_NACE_PREFIXES is SECTOR_NACE_PREFIXES

    def test_prefixes_are_dotless_digits(self) -> None:
        """KBO Open Data stores NACE without dots: '4321', never '43.21'."""
        for slug, prefixes in SECTOR_NACE_PREFIXES.items():
            assert prefixes, f"{slug} maps to no prefixes"
            for p in prefixes:
                assert re.fullmatch(r"[0-9]{2,7}", p), f"{slug}: bad prefix {p!r}"
