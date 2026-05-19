"""Unit tests for _SECTOR_NACE_PREFIXES coverage and correctness."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from scraper.pipeline.orchestrator import _SECTOR_NACE_PREFIXES

_SECTORS_TOML = (
    Path(__file__).parents[3]
    / ".claude"
    / "skills"
    / "goudengids-listing"
    / "references"
    / "sectors.toml"
)


def _all_sector_keys() -> list[str]:
    with _SECTORS_TOML.open("rb") as fh:
        data = tomllib.load(fh)
    return [k for k, v in data.items() if isinstance(v, dict)]


class TestNacePrefixCoverage:
    def test_all_sectors_have_nace_prefix(self) -> None:
        missing = [s for s in _all_sector_keys() if s not in _SECTOR_NACE_PREFIXES]
        assert missing == [], f"Sectors missing NACE prefix: {missing}"

    def test_no_empty_prefix_lists(self) -> None:
        empty = [k for k, v in _SECTOR_NACE_PREFIXES.items() if not v]
        assert empty == [], f"Sectors with empty prefix list: {empty}"

    def test_prefixes_are_dotless(self) -> None:
        dotted = [
            (k, p) for k, prefixes in _SECTOR_NACE_PREFIXES.items() for p in prefixes if "." in p
        ]
        assert dotted == [], f"Prefixes must be dotless: {dotted}"

    @pytest.mark.parametrize(
        "sector, expected_prefix",
        [
            ("accountants", "6920"),
            ("advocaten", "6910"),
            ("notarissen", "6910"),
            ("belastingconsulenten", "6920"),
            ("huisartsen", "8621"),
            ("tandartsen", "8623"),
            ("apothekers", "4773"),
            ("vastgoedmakelaars", "6831"),
            ("restaurants", "5610"),
            ("hotels", "5510"),
            ("taxidiensten", "4932"),
            ("verhuisbedrijven", "4942"),
            ("transportbedrijven", "4941"),
            ("tuinaanleggers", "8130"),
            ("informaticabedrijven", "620"),
            ("informaticabedrijven", "631"),
            ("informaticabedrijven", "582"),
            ("zonnepaneleninstallateurs", "4321"),
            ("elektriciens", "4321"),
            ("metselaars", "4120"),
            ("garagisten", "4520"),
            # T1 industrial sectors
            ("energieproducenten", "3511"),
            ("energieproducenten", "3512"),
            ("chemiebedrijven", "201"),
            ("chemiebedrijven", "206"),
            ("farmaceutische-bedrijven", "212"),
            ("staalindustrie", "241"),
            ("petroleumraffinaderijen", "192"),
            # T2 industrial sectors
            ("waterzuivering", "3600"),
            ("automobielfabrieken", "291"),
            ("voedingsindustrie", "101"),
            ("voedingsindustrie", "105"),
            ("machinebouwers", "281"),
            # T1 new sectors
            ("datacenters", "6190"),
            ("spoortransport", "4920"),
            # T2 new sectors
            ("diervoederfabricage", "1091"),
            ("voedingsindustrie", "109"),
            ("textielfabricage", "131"),
            ("textielfabricage", "132"),
            # T3 industrial sectors
            ("ziekenhuizen", "8610"),
            ("havenactiviteiten", "5222"),
            ("logistiekverleners", "5210"),
            ("bouwbedrijven", "4212"),
            ("universiteiten", "8542"),
            # T3 new sectors
            ("grote-bedrijfsgebouwen", "6820"),
            ("steengroeven", "0812"),
            ("tuinbouwbedrijven-industrieel", "0113"),
            ("tuinbouwbedrijven-industrieel", "013"),
            ("intensieve-veehouderij", "0147"),
            ("snellaadstations", "4799"),
        ],
    )
    def test_known_sector_prefix(self, sector: str, expected_prefix: str) -> None:
        assert expected_prefix in _SECTOR_NACE_PREFIXES[sector], (
            f"{sector} should include prefix {expected_prefix}"
        )

    def test_elektriciens_does_not_include_plumbing_prefix(self) -> None:
        """432 was the old prefix — too broad, overlaps with plumbing (4322)."""
        assert "432" not in _SECTOR_NACE_PREFIXES["elektriciens"]

    def test_metselaars_does_not_include_finishing_prefix(self) -> None:
        """433 (building finishing) was wrong for bricklayers; must not be present."""
        assert "433" not in _SECTOR_NACE_PREFIXES["metselaars"]
