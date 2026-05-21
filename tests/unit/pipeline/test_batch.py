"""Unit tests for batch.py (no DB required)."""

from __future__ import annotations

import pytest

from scraper.pipeline.batch import BatchConfig, BatchReport, _resolve_goudengids_slug


class TestBatchConfig:
    def test_defaults(self) -> None:
        cfg = BatchConfig(city="antwerpen", sectors=["elektriciens"])
        assert cfg.lang == "nl"
        assert cfg.max_pages == 25
        assert cfg.snapshot_date is None
        assert cfg.do_kbo_dump is True
        assert cfg.do_goudengids is True
        assert cfg.do_kbopub is True
        assert cfg.do_nbb is True
        assert cfg.do_website is True
        assert cfg.do_search is True
        assert cfg.nbb_subscription_key is None
        assert cfg.brave_subscription_key is None
        assert cfg.export_dir is None
        assert cfg.export_chunk_size == 5000
        assert cfg.goudengids_skip_recent_hours == 720
        assert cfg.ddg_brave_skip_recent_hours == 168

    def test_frozen(self) -> None:
        cfg = BatchConfig(city="gent", sectors=["accountants"])
        with pytest.raises((AttributeError, TypeError)):
            cfg.city = "brussel"  # type: ignore[misc]

    def test_skip_flags(self) -> None:
        cfg = BatchConfig(
            city="brussel",
            sectors=[],
            do_goudengids=False,
            do_kbopub=False,
            do_nbb=False,
            do_website=False,
            do_search=False,
        )
        assert cfg.do_goudengids is False
        assert cfg.do_kbopub is False


class TestResolveGoudengidsSlug:
    def test_indexed_sector_nl(self) -> None:
        slug = _resolve_goudengids_slug("elektriciens", "nl")
        assert slug == "elektriciens"

    def test_indexed_sector_fr(self) -> None:
        slug = _resolve_goudengids_slug("elektriciens", "fr")
        assert slug == "electriciens"

    def test_not_indexed_sector_returns_none(self) -> None:
        # energieproducenten has goudengids_sector_not_indexed = true
        slug = _resolve_goudengids_slug("energieproducenten", "nl")
        assert slug is None

    def test_unknown_sector_returns_none(self) -> None:
        slug = _resolve_goudengids_slug("nonexistent-sector-xyz", "nl")
        assert slug is None

    def test_chemiebedrijven_not_indexed(self) -> None:
        slug = _resolve_goudengids_slug("chemiebedrijven", "nl")
        assert slug is None

    def test_accountants_indexed(self) -> None:
        slug = _resolve_goudengids_slug("accountants", "nl")
        assert slug is not None
        assert len(slug) > 0


class TestBatchReport:
    def test_defaults(self) -> None:
        from datetime import UTC, datetime

        now = datetime.now(tz=UTC)
        r = BatchReport(
            city="antwerpen", sectors=["elektriciens"], snapshot_date=None, started_at=now
        )
        assert r.phase_a_kbos == 0
        assert r.placeholders_resolved == 0
        assert r.companies_in_view == 0
        assert r.prospect_scores_computed == 0
        assert r.sources_run == []
        assert r.sources_failed == {}
        assert r.goudengids_per_sector == {}
        assert r.enrichment_observations == {}
        assert r.duration_s == 0.0
        assert r.export_files == []
