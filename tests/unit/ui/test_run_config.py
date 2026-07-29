"""Tests for ui/run_config.py — UI inputs → BatchConfig mapping + sector validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from scraper.pipeline.batch import BatchConfig
from scraper.pipeline.orchestrator import _SECTOR_NACE_PREFIXES
from scraper.ui.run_config import build_batch_config


class TestBuildBatchConfig:
    def test_all_sectors_expands_to_every_known_slug(self) -> None:
        cfg = build_batch_config(city="antwerpen", sectors=[], all_sectors=True)
        assert isinstance(cfg, BatchConfig)
        assert cfg.sectors == list(_SECTOR_NACE_PREFIXES.keys())
        assert len(cfg.sectors) > 0

    def test_explicit_sectors_preserved_in_order(self) -> None:
        cfg = build_batch_config(
            city="antwerpen", sectors=["loodgieters", "elektriciens"], all_sectors=False
        )
        assert cfg.sectors == ["loodgieters", "elektriciens"]
        assert cfg.city == "antwerpen"

    def test_unknown_sector_raises_valueerror_naming_the_slug(self) -> None:
        with pytest.raises(ValueError, match="not-a-real-sector"):
            build_batch_config(city="antwerpen", sectors=["not-a-real-sector"])

    def test_no_sectors_and_not_all_raises(self) -> None:
        with pytest.raises(ValueError, match="sector"):
            build_batch_config(city="antwerpen", sectors=[], all_sectors=False)

    def test_nace_only_search_needs_no_sector(self) -> None:
        """Manual NACE codes are a valid search on their own."""
        cfg = build_batch_config(city="antwerpen", sectors=[], extra_nace_raw="3511, 35.12")
        assert cfg.sectors == []
        assert cfg.extra_nace == ["3511", "3512"]

    def test_nace_combined_with_sectors(self) -> None:
        cfg = build_batch_config(city="antwerpen", sectors=["elektriciens"], extra_nace_raw="3511")
        assert cfg.sectors == ["elektriciens"]
        assert cfg.extra_nace == ["3511"]

    def test_invalid_nace_raises_naming_the_input(self) -> None:
        with pytest.raises(ValueError, match="bogus"):
            build_batch_config(city="antwerpen", sectors=[], extra_nace_raw="bogus")

    def test_blank_nace_is_ignored(self) -> None:
        cfg = build_batch_config(city="antwerpen", sectors=[], all_sectors=True, extra_nace_raw="")
        assert cfg.extra_nace == []

    def test_empty_city_raises(self) -> None:
        with pytest.raises(ValueError, match="city"):
            build_batch_config(city="  ", sectors=[], all_sectors=True)

    def test_all_sectors_overrides_explicit_list(self) -> None:
        # When all_sectors is set, an explicit (even invalid) list is ignored — mirrors batch_cli.
        cfg = build_batch_config(city="gent", sectors=["whatever"], all_sectors=True)
        assert cfg.sectors == list(_SECTOR_NACE_PREFIXES.keys())

    def test_skip_flags_propagate(self) -> None:
        cfg = build_batch_config(
            city="antwerpen",
            sectors=["elektriciens"],
            do_goudengids=False,
            do_nbb=False,
        )
        assert cfg.do_goudengids is False
        assert cfg.do_nbb is False
        assert cfg.do_kbopub is True
        assert cfg.do_website is True

    def test_defaults_match_production_dedup_windows(self) -> None:
        cfg = build_batch_config(city="antwerpen", sectors=["elektriciens"])
        assert cfg.goudengids_skip_recent_hours == 720
        assert cfg.ddg_brave_skip_recent_hours == 168
        assert cfg.max_pages == 25
        assert cfg.lang == "nl"

    def test_passthrough_fields(self) -> None:
        cfg = build_batch_config(
            city="antwerpen",
            sectors=["elektriciens"],
            lang="fr",
            max_pages=3,
            export_dir=Path("/data/exports/run1"),
            export_chunk_size=1000,
            goudengids_skip_recent_hours=0,
            ddg_brave_skip_recent_hours=0,
            nbb_subscription_key="nbb-key",
            brave_subscription_key="brave-key",
        )
        assert cfg.lang == "fr"
        assert cfg.max_pages == 3
        assert cfg.export_dir == Path("/data/exports/run1")
        assert cfg.export_chunk_size == 1000
        assert cfg.goudengids_skip_recent_hours == 0
        assert cfg.ddg_brave_skip_recent_hours == 0
        assert cfg.nbb_subscription_key == "nbb-key"
        assert cfg.brave_subscription_key == "brave-key"
