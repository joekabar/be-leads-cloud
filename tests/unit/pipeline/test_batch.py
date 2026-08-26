"""Unit tests for batch.py (no DB required)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import structlog

from scraper.pipeline.batch import (
    BatchConfig,
    BatchReport,
    _pg_text_escape,
    _resolve_goudengids_slug,
    emit_phase_a,
    get_entity_filter,
    resolve_nace_prefixes,
    resolve_snapshot_date,
    run_batch,
)


def _fake_pool() -> AsyncMock:
    return AsyncMock()


def _fake_polite_client() -> MagicMock:
    return MagicMock()


class TestResolveNacePrefixes:
    """Manually-entered NACE codes widen a search beyond the predefined sectors."""

    def test_sector_only(self) -> None:
        assert resolve_nace_prefixes(["elektriciens"], []) == ["4321"]

    def test_extra_nace_only_without_sectors(self) -> None:
        """A NACE-only search must work with no sector selected at all."""
        assert resolve_nace_prefixes([], ["3511", "3512"]) == ["3511", "3512"]

    def test_union_of_sector_and_extra(self) -> None:
        assert set(resolve_nace_prefixes(["elektriciens"], ["3511"])) == {"4321", "3511"}

    def test_deduplicates_overlap(self) -> None:
        """Entering a code the sector already covers must not duplicate the filter."""
        assert resolve_nace_prefixes(["elektriciens"], ["4321"]) == ["4321"]

    def test_unknown_sector_contributes_nothing(self) -> None:
        assert resolve_nace_prefixes(["no_such_sector"], ["3511"]) == ["3511"]

    def test_empty_inputs(self) -> None:
        assert resolve_nace_prefixes([], []) == []


class TestBatchConfig:
    def test_extra_nace_defaults_empty(self) -> None:
        cfg = BatchConfig(city="antwerpen", sectors=["elektriciens"])
        assert cfg.extra_nace == []

    def test_extra_nace_accepted(self) -> None:
        cfg = BatchConfig(city="antwerpen", sectors=[], extra_nace=["3511"])
        assert cfg.extra_nace == ["3511"]

    def test_defaults(self) -> None:
        cfg = BatchConfig(city="antwerpen", sectors=["elektriciens"])
        assert cfg.lang == "nl"
        # A ceiling only; the in-city bail-out is what stops thin sectors early.
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

    def test_fr_slug_lookup_via_loop(self) -> None:
        """Lines 112-113: fr_slug lookup falls through direct-key lookup to loop."""
        # "electriciens" is the fr_slug of "elektriciens" but is NOT a top-level dict key
        slug = _resolve_goudengids_slug("electriciens", "nl")
        assert slug is not None  # returns nl_slug for that entry


class TestBatchReport:
    def test_defaults(self) -> None:

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


class TestPgTextEscape:
    def test_none_becomes_null_marker(self) -> None:
        assert _pg_text_escape(None) == r"\N"

    def test_plain_string_unchanged(self) -> None:
        assert _pg_text_escape("hello") == "hello"

    def test_tab_escaped(self) -> None:
        assert _pg_text_escape("a\tb") == r"a\tb"

    def test_newline_escaped(self) -> None:
        assert _pg_text_escape("a\nb") == r"a\nb"

    def test_backslash_escaped(self) -> None:
        assert _pg_text_escape("a\\b") == r"a\\b"

    def test_carriage_return_escaped(self) -> None:
        assert _pg_text_escape("a\rb") == r"a\rb"


class TestResolveSnapshotDate:
    async def test_returns_date_from_row(self) -> None:
        d = date(2024, 3, 15)
        pool = AsyncMock()
        pool.fetchrow.return_value = {"d": d}
        result = await resolve_snapshot_date(pool)
        assert result == d

    async def test_returns_none_when_table_empty(self) -> None:
        pool = AsyncMock()
        pool.fetchrow.return_value = None
        result = await resolve_snapshot_date(pool)
        assert result is None

    async def test_returns_none_when_max_is_null(self) -> None:
        pool = AsyncMock()
        pool.fetchrow.return_value = {"d": None}
        result = await resolve_snapshot_date(pool)
        assert result is None


class TestGetEntityFilter:
    async def test_empty_city_result_returns_empty_list(self) -> None:
        pool = AsyncMock()
        pool.fetch.return_value = []
        result = await get_entity_filter(pool, date(2024, 1, 1), "antwerpen", ["4321"])
        assert result == []

    async def test_city_match_no_nace_returns_all_city_entities(self) -> None:
        pool = AsyncMock()
        pool.fetch.return_value = [{"entity_number": "0123456789"}]
        result = await get_entity_filter(pool, date(2024, 1, 1), "gent", [])
        assert result == ["0123456789"]

    async def test_city_and_nace_intersection(self) -> None:
        pool = AsyncMock()
        pool.fetch.side_effect = [
            [{"entity_number": "0111111111"}, {"entity_number": "0222222222"}],
            [{"entity_number": "0222222222"}, {"entity_number": "0333333333"}],
        ]
        result = await get_entity_filter(pool, date(2024, 1, 1), "brussel", ["4321"])
        assert result == ["0222222222"]


class TestRunBatch:
    def _make_pool(self) -> AsyncMock:
        pool = AsyncMock()
        pool.execute.return_value = None
        pool.fetch.return_value = []
        pool.fetchrow.return_value = {"n": 0}
        return pool

    async def test_all_sources_disabled_returns_report(self) -> None:
        """run_batch with all sources off and snapshot_date provided runs D/E/F phases."""
        pool = self._make_pool()
        polite_client = MagicMock()

        config = BatchConfig(
            city="antwerpen",
            sectors=["elektriciens"],
            snapshot_date=date(2024, 3, 1),
            do_kbo_dump=False,
            do_goudengids=False,
            do_kbopub=False,
            do_nbb=False,
            do_website=False,
            do_search=False,
        )

        with (
            patch("scraper.pipeline.batch.consolidate", new=AsyncMock(return_value=[])),
            patch("scraper.pipeline.batch.refresh_prospect_scores", new=AsyncMock(return_value=0)),
        ):
            report = await run_batch(config, pool, polite_client)

        assert report.city == "antwerpen"
        assert report.snapshot_date == date(2024, 3, 1)
        assert report.ended_at is not None
        assert report.duration_s >= 0.0

    async def test_no_snapshot_date_raises_when_pool_empty(self) -> None:
        """run_batch raises RuntimeError when no snapshot_date and staging tables are empty."""
        pool = self._make_pool()
        pool.fetchrow.return_value = {"d": None}
        polite_client = MagicMock()

        config = BatchConfig(
            city="antwerpen",
            sectors=["elektriciens"],
            snapshot_date=None,
        )

        with pytest.raises(RuntimeError, match="No staged KBO data"):
            await run_batch(config, pool, polite_client)

    async def test_phase_a_skipped_when_no_entities(self) -> None:
        """Phase A skipped when entity_numbers is empty."""
        pool = self._make_pool()
        polite_client = MagicMock()

        config = BatchConfig(
            city="antwerpen",
            sectors=["elektriciens"],
            snapshot_date=date(2024, 3, 1),
            do_kbo_dump=True,
            do_goudengids=False,
            do_kbopub=False,
            do_nbb=False,
            do_website=False,
            do_search=False,
        )

        with (
            patch("scraper.pipeline.batch.consolidate", new=AsyncMock(return_value=[])),
            patch("scraper.pipeline.batch.refresh_prospect_scores", new=AsyncMock(return_value=0)),
        ):
            report = await run_batch(config, pool, polite_client)

        # entity_numbers=[] so kbo_dump not in sources_run
        assert "kbo_dump" not in report.sources_run
        assert report.phase_a_kbos == 0

    async def test_december_snapshot_date_branch(self) -> None:
        """Line 511: December snapshot_date triggers year+1 end boundary."""
        pool = self._make_pool()
        polite_client = MagicMock()

        config = BatchConfig(
            city="antwerpen",
            sectors=["elektriciens"],
            snapshot_date=date(2023, 12, 1),
            do_kbo_dump=False,
            do_goudengids=False,
            do_kbopub=False,
            do_nbb=False,
            do_website=False,
            do_search=False,
        )

        with (
            patch("scraper.pipeline.batch.consolidate", new=AsyncMock(return_value=[])),
            patch("scraper.pipeline.batch.refresh_prospect_scores", new=AsyncMock(return_value=0)),
        ):
            report = await run_batch(config, pool, polite_client)

        assert report.snapshot_date == date(2023, 12, 1)

    async def test_phase_a_runs_when_entities_found(self) -> None:
        """Lines 533-553: phase A emits + collects real KBOs when entities exist."""

        pool = self._make_pool()
        pool.fetch.side_effect = [
            [{"entity_number": "0403019261"}],  # city filter query
            [{"entity_number": "0403019261"}],  # nace filter query
            [],  # real_kbos query after phase A
        ]
        polite_client = MagicMock()

        config = BatchConfig(
            city="antwerpen",
            sectors=["elektriciens"],
            snapshot_date=date(2024, 3, 1),
            do_kbo_dump=True,
            do_goudengids=False,
            do_kbopub=False,
            do_nbb=False,
            do_website=False,
            do_search=False,
        )

        with (
            patch("scraper.pipeline.batch.emit_phase_a", new=AsyncMock(return_value=5)),
            patch("scraper.pipeline.batch.consolidate", new=AsyncMock(return_value=[])),
            patch("scraper.pipeline.batch.refresh_prospect_scores", new=AsyncMock(return_value=0)),
        ):
            report = await run_batch(config, pool, polite_client)

        assert report.phase_a_kbos > 0
        assert "kbo_dump" in report.sources_run

    async def test_kbopub_skip_path_logged(self) -> None:
        """Lines 597-601: kbopub skipped when do_kbopub=False."""
        pool = self._make_pool()
        polite_client = MagicMock()

        config = BatchConfig(
            city="antwerpen",
            sectors=["elektriciens"],
            snapshot_date=date(2024, 3, 1),
            do_kbo_dump=False,
            do_goudengids=False,
            do_kbopub=False,
            do_nbb=False,
            do_website=False,
            do_search=False,
        )

        with (
            patch("scraper.pipeline.batch.consolidate", new=AsyncMock(return_value=[])),
            patch("scraper.pipeline.batch.refresh_prospect_scores", new=AsyncMock(return_value=0)),
        ):
            report = await run_batch(config, pool, polite_client)

        assert "kbopub_html" not in report.sources_run

    async def test_goudengids_not_indexed_sector_skipped(self) -> None:
        """Lines 428-431: _run_goudengids_sector skips not-indexed sectors."""
        from scraper.pipeline.batch import _run_goudengids_sector

        pool = AsyncMock()
        polite_client = MagicMock()
        log = MagicMock()

        result, error = await _run_goudengids_sector(
            "energieproducenten", "antwerpen", "nl", 5, pool, polite_client, log
        )

        assert result == 0
        assert error is None

    async def test_goudengids_unknown_sector_returns_zero(self) -> None:
        """_run_goudengids_sector returns 0 for unknown sector slug."""
        from scraper.pipeline.batch import _run_goudengids_sector

        pool = AsyncMock()
        polite_client = MagicMock()
        log = MagicMock()

        result, error = await _run_goudengids_sector(
            "totally-unknown-sector-xyz", "antwerpen", "nl", 5, pool, polite_client, log
        )

        assert result == 0
        assert error is None

    async def test_goudengids_phase_b_runs_indexed_sector(self) -> None:
        """Lines 566-594: _phase_b loops sectors and collects run_ids when do_goudengids=True."""
        pool = self._make_pool()
        pool.fetch = AsyncMock(
            side_effect=[
                [],  # city_rows (entity_numbers=[])
                [],  # run_ids_now inside _phase_b for "elektriciens"
            ]
        )
        polite_client = MagicMock()

        config = BatchConfig(
            city="antwerpen",
            sectors=["elektriciens"],
            snapshot_date=date(2024, 3, 1),
            do_kbo_dump=False,
            do_goudengids=True,
            do_kbopub=False,
            do_nbb=False,
            do_website=False,
            do_search=False,
        )

        with (
            patch(
                "scraper.pipeline.batch._run_goudengids_sector",
                new=AsyncMock(return_value=(5, None)),
            ),
            patch("scraper.pipeline.batch.consolidate", new=AsyncMock(return_value=[])),
            patch("scraper.pipeline.batch.refresh_prospect_scores", new=AsyncMock(return_value=0)),
        ):
            report = await run_batch(config, pool, polite_client)

        assert report.goudengids_per_sector.get("elektriciens") == 5

    async def test_kbopub_ingest_runs_when_real_kbos_available(self) -> None:
        """Lines 547-553, 602-618: real_kbos query + kbopub try body."""
        pool = self._make_pool()
        pool.fetch = AsyncMock(
            side_effect=[
                [],  # city_rows (entity_numbers=[])
                [{"kbo_number": "0403019261"}],  # real_kbos query (do_kbopub=True)
            ]
        )
        polite_client = MagicMock()

        config = BatchConfig(
            city="antwerpen",
            sectors=["elektriciens"],
            snapshot_date=date(2024, 3, 1),
            do_kbo_dump=False,
            do_goudengids=False,
            do_kbopub=True,
            do_nbb=False,
            do_website=False,
            do_search=False,
        )

        mock_r = MagicMock()
        mock_r.observations_inserted = 3
        mock_r.kbos_processed = 1

        with (
            patch(
                "scraper.sources.kbopub_html.ingester.ingest_kbos",
                new=AsyncMock(return_value=mock_r),
            ),
            patch("scraper.pipeline.batch.consolidate", new=AsyncMock(return_value=[])),
            patch("scraper.pipeline.batch.refresh_prospect_scores", new=AsyncMock(return_value=0)),
        ):
            report = await run_batch(config, pool, polite_client)

        assert "kbopub_html" in report.sources_run
        assert report.enrichment_observations["kbopub_html"] == 3

    async def test_nbb_ingest_runs_when_key_and_real_kbos(self) -> None:
        """Lines 627-639: _phase_c1_nbb try body covered when key + real KBOs present."""
        pool = self._make_pool()
        pool.fetch = AsyncMock(
            side_effect=[
                [],  # city_rows
                [{"kbo_number": "0403019261"}],  # real_kbos (do_nbb=True)
            ]
        )
        polite_client = MagicMock()

        config = BatchConfig(
            city="antwerpen",
            sectors=["elektriciens"],
            snapshot_date=date(2024, 3, 1),
            do_kbo_dump=False,
            do_goudengids=False,
            do_kbopub=False,
            do_nbb=True,
            nbb_subscription_key="testkey",
            do_website=False,
            do_search=False,
        )

        mock_r = MagicMock()
        mock_r.observations_inserted = 2

        with (
            patch("scraper.sources.nbb_authentic.client.NbbClient"),
            patch(
                "scraper.sources.nbb_authentic.ingester.ingest_kbos",
                new=AsyncMock(return_value=mock_r),
            ),
            patch("scraper.pipeline.batch.consolidate", new=AsyncMock(return_value=[])),
            patch("scraper.pipeline.batch.refresh_prospect_scores", new=AsyncMock(return_value=0)),
        ):
            report = await run_batch(config, pool, polite_client)

        assert "nbb_authentic" in report.sources_run
        assert report.enrichment_observations["nbb_authentic"] == 2

    async def test_website_ingest_runs_when_pairs_available(self) -> None:
        """Lines 644-663: _phase_c1_website try body covered when pairs present."""
        pool = self._make_pool()
        pool.fetch = AsyncMock(
            side_effect=[
                [],  # city_rows
                [],  # real_kbos (do_website=True triggers the query)
                [{"kbo_number": "0403019261", "url": "https://test.be"}],  # pairs_rows
            ]
        )
        polite_client = MagicMock()

        config = BatchConfig(
            city="antwerpen",
            sectors=["elektriciens"],
            snapshot_date=date(2024, 3, 1),
            do_kbo_dump=False,
            do_goudengids=False,
            do_kbopub=False,
            do_nbb=False,
            do_website=True,
            do_search=False,
        )

        mock_r = MagicMock()
        mock_r.observations_inserted = 4

        with (
            patch(
                "scraper.sources.website.ingester.ingest_kbos",
                new=AsyncMock(return_value=mock_r),
            ),
            patch("scraper.pipeline.batch.consolidate", new=AsyncMock(return_value=[])),
            patch("scraper.pipeline.batch.refresh_prospect_scores", new=AsyncMock(return_value=0)),
        ):
            report = await run_batch(config, pool, polite_client)

        assert "website" in report.sources_run
        assert report.enrichment_observations["website"] == 4

    async def test_goudengids_run_ids_loop_body(self) -> None:
        """Lines 593-594: run_ids_now loop body covered when pool.fetch returns a run_id row."""
        import uuid as _uuid

        pool = self._make_pool()
        pool.fetch = AsyncMock(
            side_effect=[
                [],  # city_rows
                [{"run_id": _uuid.uuid4()}],  # run_ids_now inside _phase_b (non-empty)
            ]
        )
        polite_client = MagicMock()

        config = BatchConfig(
            city="antwerpen",
            sectors=["elektriciens"],
            snapshot_date=date(2024, 3, 1),
            do_kbo_dump=False,
            do_goudengids=True,
            do_kbopub=False,
            do_nbb=False,
            do_website=False,
            do_search=False,
        )

        with (
            patch(
                "scraper.pipeline.batch._run_goudengids_sector",
                new=AsyncMock(return_value=(3, None)),
            ),
            patch("scraper.pipeline.batch.consolidate", new=AsyncMock(return_value=[])),
            patch("scraper.pipeline.batch.refresh_prospect_scores", new=AsyncMock(return_value=0)),
        ):
            report = await run_batch(config, pool, polite_client)

        assert report.goudengids_per_sector.get("elektriciens") == 3

    async def test_kbopub_exception_stored_in_report(self) -> None:
        """Lines 616-618: kbopub exception handler stores error in sources_failed."""
        pool = self._make_pool()
        pool.fetch = AsyncMock(
            side_effect=[
                [],  # city_rows
                [{"kbo_number": "0403019261"}],  # real_kbos
            ]
        )
        polite_client = MagicMock()

        config = BatchConfig(
            city="antwerpen",
            sectors=["elektriciens"],
            snapshot_date=date(2024, 3, 1),
            do_kbo_dump=False,
            do_goudengids=False,
            do_kbopub=True,
            do_nbb=False,
            do_website=False,
            do_search=False,
        )

        with (
            patch(
                "scraper.sources.kbopub_html.ingester.ingest_kbos",
                new=AsyncMock(side_effect=RuntimeError("kbopub crashed")),
            ),
            patch("scraper.pipeline.batch.consolidate", new=AsyncMock(return_value=[])),
            patch("scraper.pipeline.batch.refresh_prospect_scores", new=AsyncMock(return_value=0)),
        ):
            report = await run_batch(config, pool, polite_client)

        assert "kbopub_html" in report.sources_failed
        assert "kbopub crashed" in report.sources_failed["kbopub_html"]

    async def test_nbb_exception_stored_in_report(self) -> None:
        """Lines 637-639: nbb exception handler stores error in sources_failed."""
        pool = self._make_pool()
        pool.fetch = AsyncMock(
            side_effect=[
                [],  # city_rows
                [{"kbo_number": "0403019261"}],  # real_kbos
            ]
        )
        polite_client = MagicMock()

        config = BatchConfig(
            city="antwerpen",
            sectors=["elektriciens"],
            snapshot_date=date(2024, 3, 1),
            do_kbo_dump=False,
            do_goudengids=False,
            do_kbopub=False,
            do_nbb=True,
            nbb_subscription_key="testkey",
            do_website=False,
            do_search=False,
        )

        with (
            patch("scraper.sources.nbb_authentic.client.NbbClient"),
            patch(
                "scraper.sources.nbb_authentic.ingester.ingest_kbos",
                new=AsyncMock(side_effect=RuntimeError("nbb crashed")),
            ),
            patch("scraper.pipeline.batch.consolidate", new=AsyncMock(return_value=[])),
            patch("scraper.pipeline.batch.refresh_prospect_scores", new=AsyncMock(return_value=0)),
        ):
            report = await run_batch(config, pool, polite_client)

        assert "nbb_authentic" in report.sources_failed

    async def test_website_no_pairs_skipped(self) -> None:
        """Lines 654-655: website skip when pairs_rows is empty."""
        pool = self._make_pool()
        pool.fetch = AsyncMock(
            side_effect=[
                [],  # city_rows
                [],  # real_kbos
                [],  # pairs_rows (empty → no pairs → skip)
            ]
        )
        polite_client = MagicMock()

        config = BatchConfig(
            city="antwerpen",
            sectors=["elektriciens"],
            snapshot_date=date(2024, 3, 1),
            do_kbo_dump=False,
            do_goudengids=False,
            do_kbopub=False,
            do_nbb=False,
            do_website=True,
            do_search=False,
        )

        with (
            patch("scraper.pipeline.batch.consolidate", new=AsyncMock(return_value=[])),
            patch("scraper.pipeline.batch.refresh_prospect_scores", new=AsyncMock(return_value=0)),
        ):
            report = await run_batch(config, pool, polite_client)

        assert "website" not in report.sources_run

    async def test_website_exception_stored_in_report(self) -> None:
        """Lines 661-663: website exception handler stores error in sources_failed."""
        pool = self._make_pool()
        pool.fetch = AsyncMock(
            side_effect=[
                [],  # city_rows
                [],  # real_kbos
                [{"kbo_number": "0403019261", "url": "https://test.be"}],  # pairs_rows
            ]
        )
        polite_client = MagicMock()

        config = BatchConfig(
            city="antwerpen",
            sectors=["elektriciens"],
            snapshot_date=date(2024, 3, 1),
            do_kbo_dump=False,
            do_goudengids=False,
            do_kbopub=False,
            do_nbb=False,
            do_website=True,
            do_search=False,
        )

        with (
            patch(
                "scraper.sources.website.ingester.ingest_kbos",
                new=AsyncMock(side_effect=RuntimeError("website crashed")),
            ),
            patch("scraper.pipeline.batch.consolidate", new=AsyncMock(return_value=[])),
            patch("scraper.pipeline.batch.refresh_prospect_scores", new=AsyncMock(return_value=0)),
        ):
            report = await run_batch(config, pool, polite_client)

        assert "website" in report.sources_failed

    async def test_search_skipped_when_no_placeholder_inputs(self) -> None:
        """Lines 675-725: do_search=True but placeholder_rows is empty → skip branch."""
        pool = self._make_pool()
        pool.fetch = AsyncMock(
            side_effect=[
                [],  # city_rows (get_entity_filter → empty → early return)
                [],  # placeholder_rows (empty → no inputs → skip)
            ]
        )
        polite_client = MagicMock()

        config = BatchConfig(
            city="antwerpen",
            sectors=["elektriciens"],
            snapshot_date=date(2024, 3, 1),
            do_kbo_dump=False,
            do_goudengids=False,
            do_kbopub=False,
            do_nbb=False,
            do_website=False,
            do_search=True,
        )

        with (
            patch("scraper.pipeline.batch.consolidate", new=AsyncMock(return_value=[])),
            patch("scraper.pipeline.batch.refresh_prospect_scores", new=AsyncMock(return_value=0)),
        ):
            report = await run_batch(config, pool, polite_client)

        assert "ddg_brave" not in report.sources_run

    async def test_search_runs_when_placeholders_with_names(self) -> None:
        """Lines 705-723: do_search=True with named placeholder → validate_companies called."""
        pool = self._make_pool()
        pool.fetch = AsyncMock(
            side_effect=[
                [],  # city_rows (get_entity_filter → empty → early return)
                [{"kbo_number": "9123456789", "name": "Test Co", "city": "Antwerpen"}],
            ]
        )
        polite_client = MagicMock()

        config = BatchConfig(
            city="antwerpen",
            sectors=["elektriciens"],
            snapshot_date=date(2024, 3, 1),
            do_kbo_dump=False,
            do_goudengids=False,
            do_kbopub=False,
            do_nbb=False,
            do_website=False,
            do_search=True,
        )

        mock_search_r = MagicMock()
        mock_search_r.observations_inserted = 3

        with (
            patch("scraper.sources.ddg_brave.ddg_client.DdgClient"),
            patch(
                "scraper.sources.ddg_brave.ingester.validate_companies",
                new=AsyncMock(return_value=mock_search_r),
            ),
            patch("scraper.pipeline.batch.consolidate", new=AsyncMock(return_value=[])),
            patch("scraper.pipeline.batch.refresh_prospect_scores", new=AsyncMock(return_value=0)),
        ):
            report = await run_batch(config, pool, polite_client)

        assert "ddg_brave" in report.sources_run
        assert report.enrichment_observations["ddg_brave"] == 3

    async def test_search_exception_stored_in_report(self) -> None:
        """Lines 726-728: exception in Phase C2 stored in sources_failed."""
        pool = self._make_pool()
        pool.fetch = AsyncMock(
            side_effect=[
                [],  # city_rows (get_entity_filter → empty → early return)
                [{"kbo_number": "9123456789", "name": "Test Co", "city": "Antwerpen"}],
            ]
        )
        polite_client = MagicMock()

        config = BatchConfig(
            city="antwerpen",
            sectors=["elektriciens"],
            snapshot_date=date(2024, 3, 1),
            do_kbo_dump=False,
            do_goudengids=False,
            do_kbopub=False,
            do_nbb=False,
            do_website=False,
            do_search=True,
        )

        with (
            patch("scraper.sources.ddg_brave.ddg_client.DdgClient"),
            patch(
                "scraper.sources.ddg_brave.ingester.validate_companies",
                new=AsyncMock(side_effect=RuntimeError("search crashed")),
            ),
            patch("scraper.pipeline.batch.consolidate", new=AsyncMock(return_value=[])),
            patch("scraper.pipeline.batch.refresh_prospect_scores", new=AsyncMock(return_value=0)),
        ):
            report = await run_batch(config, pool, polite_client)

        assert "ddg_brave" in report.sources_failed


class TestPhaseDEFReportFailures:
    """Phases D/E/F must report failure the way phases A/C/G already do.

    The 2026-07-30 nightly run logged `phase_f_started`, no `phase_f_finished`, and
    `prospect_scores=0` in an otherwise clean `batch_finished` — because the phase was
    wrapped in `with suppress(Exception)`. `prospect_scores.computed_at` had been stuck at
    2026-07-27 for three nights and nothing said so. Failure here stays non-fatal (a broken
    scrape must not cost the night's consolidation), but it must never again be silent.
    """

    def _make_pool(self) -> AsyncMock:
        pool = AsyncMock()
        pool.execute.return_value = None
        pool.fetch.return_value = []
        pool.fetchrow.return_value = {"n": 0}
        return pool

    def _config(self) -> BatchConfig:
        return BatchConfig(
            city="antwerpen",
            sectors=["elektriciens"],
            snapshot_date=date(2024, 3, 1),
            do_kbo_dump=False,
            do_goudengids=False,
            do_kbopub=False,
            do_nbb=False,
            do_website=False,
            do_search=False,
        )

    async def test_prospect_scoring_failure_recorded(self) -> None:
        pool = self._make_pool()

        with (
            patch("scraper.pipeline.batch.consolidate", new=AsyncMock(return_value=[])),
            patch(
                "scraper.pipeline.batch.refresh_prospect_scores",
                new=AsyncMock(side_effect=RuntimeError("scoring exploded")),
            ),
        ):
            report = await run_batch(self._config(), pool, MagicMock())

        assert "prospect_scores" in report.sources_failed
        assert "scoring exploded" in report.sources_failed["prospect_scores"]

    async def test_batch_still_finishes_when_scoring_fails(self) -> None:
        """Non-fatal: the report is still completed and returned."""
        pool = self._make_pool()

        with (
            patch("scraper.pipeline.batch.consolidate", new=AsyncMock(return_value=[])),
            patch(
                "scraper.pipeline.batch.refresh_prospect_scores",
                new=AsyncMock(side_effect=RuntimeError("scoring exploded")),
            ),
        ):
            report = await run_batch(self._config(), pool, MagicMock())

        assert report.ended_at is not None
        assert report.prospect_scores_computed == 0

    async def test_memory_error_records_its_type(self) -> None:
        """`str(MemoryError())` is empty — the type must be recorded or the entry says nothing.

        MemoryError is the leading hypothesis for the production failure: Phase F holds
        8.7M fetched rows plus ~2M dicts alongside Chromium.
        """
        pool = self._make_pool()

        with (
            patch("scraper.pipeline.batch.consolidate", new=AsyncMock(return_value=[])),
            patch(
                "scraper.pipeline.batch.refresh_prospect_scores",
                new=AsyncMock(side_effect=MemoryError()),
            ),
        ):
            report = await run_batch(self._config(), pool, MagicMock())

        assert "MemoryError" in report.sources_failed["prospect_scores"]

    async def test_consolidation_failure_recorded(self) -> None:
        pool = self._make_pool()

        with (
            patch(
                "scraper.pipeline.batch.consolidate",
                new=AsyncMock(side_effect=RuntimeError("consolidation exploded")),
            ),
            patch("scraper.pipeline.batch.refresh_prospect_scores", new=AsyncMock(return_value=0)),
        ):
            report = await run_batch(self._config(), pool, MagicMock())

        assert "consolidation exploded" in report.sources_failed["consolidation"]

    async def test_matview_refresh_failures_recorded(self) -> None:
        """Both refreshes report — the pre-consolidation one and Phase E's."""
        pool = self._make_pool()

        async def _execute(sql: str, *args: object, **kwargs: object) -> None:
            # Fail only the matview refresh; other statements in the run are unrelated.
            if "refresh_companies_current" in sql:
                raise RuntimeError("matview exploded")

        pool.execute = AsyncMock(side_effect=_execute)

        with (
            patch("scraper.pipeline.batch.consolidate", new=AsyncMock(return_value=[])),
            patch("scraper.pipeline.batch.refresh_prospect_scores", new=AsyncMock(return_value=0)),
        ):
            report = await run_batch(self._config(), pool, MagicMock())

        assert "matview exploded" in report.sources_failed["matview_refresh"]
        assert "matview exploded" in report.sources_failed["matview_refresh_pre_consolidation"]

    async def test_failed_steps_are_logged_as_errors(self) -> None:
        pool = self._make_pool()
        mock_log = MagicMock()

        with (
            patch("scraper.pipeline.batch.logger") as mock_logger,
            patch("scraper.pipeline.batch.consolidate", new=AsyncMock(return_value=[])),
            patch(
                "scraper.pipeline.batch.refresh_prospect_scores",
                new=AsyncMock(side_effect=RuntimeError("scoring exploded")),
            ),
        ):
            mock_logger.bind.return_value = mock_log
            await run_batch(self._config(), pool, MagicMock())

        events = [c.args[0] for c in mock_log.error.call_args_list if c.args]
        assert "phase_f_failed" in events

    async def test_batch_finished_names_the_failed_steps(self) -> None:
        """The summary line is what an operator reads; a partial run must not look clean."""
        pool = self._make_pool()
        mock_log = MagicMock()

        with (
            patch("scraper.pipeline.batch.logger") as mock_logger,
            patch("scraper.pipeline.batch.consolidate", new=AsyncMock(return_value=[])),
            patch(
                "scraper.pipeline.batch.refresh_prospect_scores",
                new=AsyncMock(side_effect=RuntimeError("scoring exploded")),
            ),
        ):
            mock_logger.bind.return_value = mock_log
            await run_batch(self._config(), pool, MagicMock())

        finished = [
            c for c in mock_log.info.call_args_list if c.args and c.args[0] == "batch_finished"
        ]
        assert len(finished) == 1
        assert finished[0].kwargs["failed"] == ["prospect_scores"]


class TestEmitPhaseA:
    def _make_pool(self) -> tuple[MagicMock, MagicMock]:
        conn = MagicMock()
        conn.copy_to_table = AsyncMock()

        acquire_cm = MagicMock()
        acquire_cm.__aenter__ = AsyncMock(return_value=conn)
        acquire_cm.__aexit__ = AsyncMock(return_value=False)

        pool = MagicMock()
        pool.acquire = MagicMock(return_value=acquire_cm)
        pool.fetch = AsyncMock(return_value=[])

        return pool, conn

    async def test_empty_entity_numbers_returns_zero(self) -> None:
        import uuid
        from datetime import UTC, date, datetime

        pool, _conn = self._make_pool()
        result = await emit_phase_a(
            pool,
            date(2024, 1, 1),
            [],
            uuid.uuid4(),
            datetime.now(tz=UTC),
        )
        assert result == 0

    async def test_empty_staging_rows_returns_zero(self) -> None:
        import uuid
        from datetime import UTC, date, datetime

        pool, _conn = self._make_pool()
        result = await emit_phase_a(
            pool,
            date(2024, 1, 1),
            ["0403019261"],
            uuid.uuid4(),
            datetime.now(tz=UTC),
        )
        assert result == 0
        assert pool.fetch.call_count == 5

    async def test_one_enterprise_row_emitted(self) -> None:
        import uuid
        from datetime import UTC, date, datetime

        pool, _conn = self._make_pool()

        ent_row = {
            "entity_number": "0403019261",
            "status": "Active",
            "juridical_situation": "AC",
            "type_of_enterprise": "2",
            "juridical_form": None,
            "juridical_form_cac": None,
            "start_date": None,
        }

        pool.fetch = AsyncMock(
            side_effect=[
                [ent_row],
                [],
                [],
                [],
                [],
            ]
        )

        mock_obs = MagicMock()
        mock_obs.kbo_number = "0403019261"
        mock_obs.field = "name"
        mock_obs.value = {"text": "Test NV"}
        mock_obs.raw_value = None
        mock_obs.confidence = 0.95

        with patch(
            "scraper.pipeline.batch.enterprise_to_observations",
            return_value=[mock_obs],
        ):
            result = await emit_phase_a(
                pool,
                date(2024, 1, 1),
                ["0403019261"],
                uuid.uuid4(),
                datetime.now(tz=UTC),
            )

        assert result == 1
        _conn.copy_to_table.assert_called_once()

    async def test_address_row_emitted(self) -> None:
        import uuid
        from datetime import UTC, date, datetime

        pool, _conn = self._make_pool()

        addr_row = {
            "entity_number": "0403019261",
            "type_of_address": "REGO",
            "zipcode": "1000",
            "municipality_nl": "Brussel",
            "municipality_fr": "Bruxelles",
            "street_nl": "Teststraat",
            "street_fr": "Rue Test",
            "house_number": "1",
            "box": None,
        }

        pool.fetch = AsyncMock(
            side_effect=[
                [],
                [addr_row],
                [],
                [],
                [],
            ]
        )

        mock_obs = MagicMock()
        mock_obs.kbo_number = "0403019261"
        mock_obs.field = "address"
        mock_obs.value = {"postal_code": "1000"}
        mock_obs.raw_value = None
        mock_obs.confidence = 0.9

        with patch(
            "scraper.pipeline.batch.address_to_observation",
            return_value=mock_obs,
        ):
            result = await emit_phase_a(
                pool,
                date(2024, 1, 1),
                ["0403019261"],
                uuid.uuid4(),
                datetime.now(tz=UTC),
            )

        assert result == 1

    async def test_denomination_row_emitted(self) -> None:
        import uuid
        from datetime import UTC, date, datetime

        pool, _conn = self._make_pool()

        denom_row = {
            "entity_number": "0403019261",
            "language": "NL",
            "type_of_denomination": "001",
            "denomination": "Test NV",
        }

        pool.fetch = AsyncMock(
            side_effect=[
                [],
                [],
                [denom_row],
                [],
                [],
            ]
        )

        mock_obs = MagicMock()
        mock_obs.kbo_number = "0403019261"
        mock_obs.field = "name"
        mock_obs.value = {"text": "Test NV"}
        mock_obs.raw_value = None
        mock_obs.confidence = 1.0

        with patch(
            "scraper.pipeline.batch.denomination_to_observation",
            return_value=mock_obs,
        ):
            result = await emit_phase_a(
                pool,
                date(2024, 1, 1),
                ["0403019261"],
                uuid.uuid4(),
                datetime.now(tz=UTC),
            )

        assert result == 1

    async def test_contact_row_emitted(self) -> None:
        import uuid
        from datetime import UTC, date, datetime

        pool, _conn = self._make_pool()

        contact_row = {
            "entity_number": "0403019261",
            "contact_type": "WEB",
            "value": "https://test.be",
        }

        pool.fetch = AsyncMock(
            side_effect=[
                [],
                [],
                [],
                [contact_row],
                [],
            ]
        )

        mock_obs = MagicMock()
        mock_obs.kbo_number = "0403019261"
        mock_obs.field = "website"
        mock_obs.value = {"url": "https://test.be"}
        mock_obs.raw_value = None
        mock_obs.confidence = 0.9

        with patch(
            "scraper.pipeline.batch.contact_to_observation",
            return_value=mock_obs,
        ):
            result = await emit_phase_a(
                pool,
                date(2024, 1, 1),
                ["0403019261"],
                uuid.uuid4(),
                datetime.now(tz=UTC),
            )

        assert result == 1

    async def test_activity_row_emitted(self) -> None:
        import uuid
        from datetime import UTC, date, datetime

        pool, _conn = self._make_pool()

        act_row = {
            "entity_number": "0403019261",
            "activity_group": "MAIN",
            "nace_version": "2008",
            "nace_code": "43211",
            "classification": "NACE2008",
        }

        pool.fetch = AsyncMock(
            side_effect=[
                [],
                [],
                [],
                [],
                [act_row],
            ]
        )

        mock_obs = MagicMock()
        mock_obs.kbo_number = "0403019261"
        mock_obs.field = "nace_code"
        mock_obs.value = {"code": "43211"}
        mock_obs.raw_value = None
        mock_obs.confidence = 0.95

        with patch(
            "scraper.pipeline.batch.activity_to_observation",
            return_value=mock_obs,
        ):
            result = await emit_phase_a(
                pool,
                date(2024, 1, 1),
                ["0403019261"],
                uuid.uuid4(),
                datetime.now(tz=UTC),
            )

        assert result == 1

    async def test_emit_with_progress_reporter(self) -> None:
        """Lines 240,270,307,342,376: progress.report called once per section."""
        import uuid
        from datetime import UTC, date, datetime

        pool, _conn = self._make_pool()
        mock_progress = MagicMock()
        mock_progress.report = AsyncMock()

        result = await emit_phase_a(
            pool,
            date(2024, 1, 1),
            ["0403019261"],
            uuid.uuid4(),
            datetime.now(tz=UTC),
            progress=mock_progress,
        )

        assert result == 0
        assert mock_progress.report.call_count >= 5


class TestRunGoudengidsSector:
    async def test_success_nl_returns_observations_count(self) -> None:
        """Lines 433-455: success path returns observations_inserted."""
        from scraper.pipeline.batch import _run_goudengids_sector

        pool = AsyncMock()
        polite_client = MagicMock()
        polite_client.limiter = MagicMock()
        log = MagicMock()

        mock_report = MagicMock()
        mock_report.pages_scanned = 2
        mock_report.cards_found = 10
        mock_report.observations_inserted = 5

        with (
            patch("scraper.sources.goudengids.fetcher.BrowserListingFetcher"),
            patch(
                "scraper.sources.goudengids.ingester.ingest_sector_city",
                new=AsyncMock(return_value=mock_report),
            ),
        ):
            result, error = await _run_goudengids_sector(
                "elektriciens", "antwerpen", "nl", 5, pool, polite_client, log
            )

        assert result == 5
        assert error is None

    async def test_success_fr_uses_pagesdor_domain(self) -> None:
        """Line 436: lang=='fr' selects pagesdor.be domain."""
        from scraper.pipeline.batch import _run_goudengids_sector

        pool = AsyncMock()
        polite_client = MagicMock()
        log = MagicMock()

        mock_report = MagicMock()
        mock_report.pages_scanned = 1
        mock_report.cards_found = 3
        mock_report.observations_inserted = 2

        with (
            patch("scraper.sources.goudengids.fetcher.BrowserListingFetcher"),
            patch(
                "scraper.sources.goudengids.ingester.ingest_sector_city",
                new=AsyncMock(return_value=mock_report),
            ),
        ):
            result, error = await _run_goudengids_sector(
                "elektriciens", "liège", "fr", 5, pool, polite_client, log
            )

        assert result == 2
        assert error is None

    async def test_value_error_returns_zero(self) -> None:
        """Lines 456-458: ValueError from ingest_sector_city is swallowed."""
        from scraper.pipeline.batch import _run_goudengids_sector

        pool = AsyncMock()
        polite_client = MagicMock()
        log = MagicMock()

        with (
            patch("scraper.sources.goudengids.fetcher.BrowserListingFetcher"),
            patch(
                "scraper.sources.goudengids.ingester.ingest_sector_city",
                new=AsyncMock(side_effect=ValueError("no results")),
            ),
        ):
            result, error = await _run_goudengids_sector(
                "elektriciens", "antwerpen", "nl", 5, pool, polite_client, log
            )

        assert result == 0
        assert error is None

    async def test_generic_exception_returns_zero(self) -> None:
        """Lines 459-461: generic Exception from ingest_sector_city is swallowed."""
        from scraper.pipeline.batch import _run_goudengids_sector

        pool = AsyncMock()
        polite_client = MagicMock()
        log = MagicMock()

        with (
            patch("scraper.sources.goudengids.fetcher.BrowserListingFetcher"),
            patch(
                "scraper.sources.goudengids.ingester.ingest_sector_city",
                new=AsyncMock(side_effect=RuntimeError("browser crashed")),
            ),
        ):
            result, error = await _run_goudengids_sector(
                "elektriciens", "antwerpen", "nl", 5, pool, polite_client, log
            )

        assert result == 0
        assert error == "RuntimeError: browser crashed"


class TestSectorErrorsReachTheReport:
    """A sector that FAILED must be distinguishable from one that found nothing.

    On 2026-08-22/23, DNS failures made all ten sectors of four consecutive runs raise
    inside _run_goudengids_sector, whose `except Exception` returned 0 — the same value
    an empty sector returns. Four runs reported exit=0; two days produced zero
    observations with no alarm.
    """

    async def test_ingest_exception_is_recorded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def _boom(*args: object, **kwargs: object) -> object:
            raise RuntimeError("net::ERR_NAME_NOT_RESOLVED at https://www.goudengids.be/")

        import scraper.sources.goudengids.ingester as ingester_mod

        monkeypatch.setattr(ingester_mod, "ingest_sector_city", _boom)

        from scraper.pipeline.batch import _run_goudengids_sector

        obs, err = await _run_goudengids_sector(
            "hotels",
            "brugge",
            "nl",
            25,
            _fake_pool(),
            _fake_polite_client(),
            structlog.get_logger(),
        )
        assert obs == 0
        assert err is not None and "ERR_NAME_NOT_RESOLVED" in err

    async def test_no_results_is_not_an_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """ValueError = sector not indexed / empty: expected, must stay err=None."""

        async def _empty(*args: object, **kwargs: object) -> object:
            raise ValueError("no results")

        import scraper.sources.goudengids.ingester as ingester_mod

        monkeypatch.setattr(ingester_mod, "ingest_sector_city", _empty)

        from scraper.pipeline.batch import _run_goudengids_sector

        obs, err = await _run_goudengids_sector(
            "hotels",
            "brugge",
            "nl",
            25,
            _fake_pool(),
            _fake_polite_client(),
            structlog.get_logger(),
        )
        assert (obs, err) == (0, None)
