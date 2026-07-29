"""Unit tests for pipeline/orchestrator.py — helpers and run_pipeline control flow."""

from __future__ import annotations

import shutil
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scraper.pipeline.orchestrator import (
    PipelineConfig,
    PipelineReport,
    _count_companies_in_view,
    _create_fixture_zip,
    _get_goudengids_slug,
    _get_placeholder_inputs,
    _get_real_kbos,
    _get_real_kbos_for_sector_city,
    _get_website_pairs,
    _run_goudengids,
    _run_kbo_dump,
    _run_kbopub,
    _run_nbb,
    _run_search,
    _run_website,
    resolve_sector_slugs,
    run_pipeline,
)


def _make_pool(**overrides: object) -> AsyncMock:
    pool = AsyncMock()
    pool.execute.return_value = None
    pool.fetch.return_value = []
    pool.fetchrow.return_value = {"n": 0}
    for k, v in overrides.items():
        setattr(pool, k, v)
    return pool


class TestResolveSectorSlugs:
    def test_known_nl_slug_returns_pair(self) -> None:
        nl, fr = resolve_sector_slugs("elektriciens")
        assert nl == "elektriciens"
        assert isinstance(fr, str) and len(fr) > 0

    def test_known_fr_slug_returns_pair(self) -> None:
        nl, _fr = resolve_sector_slugs("electriciens")
        assert nl == "elektriciens"

    def test_unknown_slug_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Unknown sector slug"):
            resolve_sector_slugs("nonexistent-xyz-sector-abc")


class TestGetGoudengidsSlug:
    def test_nl_lang_returns_sector_slug_unchanged(self) -> None:
        config = PipelineConfig(sector="elektriciens", city="antwerpen", sector_slug="elektriciens")
        assert _get_goudengids_slug(config) == "elektriciens"

    def test_fr_lang_returns_fr_slug(self) -> None:
        config = PipelineConfig(
            sector="elektriciens", city="liège", sector_slug="elektriciens", lang="fr"
        )
        slug = _get_goudengids_slug(config)
        assert slug != "elektriciens"  # should be the French slug
        assert isinstance(slug, str) and len(slug) > 0

    def test_fr_lang_unknown_sector_falls_back_to_input(self) -> None:
        config = PipelineConfig(
            sector="unknown-xyz", city="liège", sector_slug="unknown-xyz", lang="fr"
        )
        assert _get_goudengids_slug(config) == "unknown-xyz"


class TestCreateFixtureZip:
    def test_creates_zip_containing_csv_files(self, tmp_path: Path) -> None:
        (tmp_path / "enterprise.csv").write_text("col\nval\n")
        (tmp_path / "address.csv").write_text("col\nval\n")
        zip_path, temp_dir = _create_fixture_zip(tmp_path)
        try:
            assert zip_path.exists()
            assert zip_path.suffix == ".zip"
            with zipfile.ZipFile(zip_path) as zf:
                names = zf.namelist()
            assert "enterprise.csv" in names
            assert "address.csv" in names
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_returns_paths_inside_temp_dir(self, tmp_path: Path) -> None:
        (tmp_path / "data.csv").write_text("x\n")
        zip_path, temp_dir = _create_fixture_zip(tmp_path)
        try:
            assert zip_path.parent == temp_dir
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


class TestCountCompaniesInView:
    async def test_returns_integer_count(self) -> None:
        pool = _make_pool(fetchrow=AsyncMock(return_value={"n": 42}))
        assert await _count_companies_in_view(pool) == 42

    async def test_returns_zero_when_row_is_none(self) -> None:
        pool = _make_pool(fetchrow=AsyncMock(return_value=None))
        assert await _count_companies_in_view(pool) == 0


class TestGetRealKbos:
    async def test_uses_run_id_branch_when_provided(self) -> None:
        run_id = uuid.uuid4()
        pool = _make_pool(fetch=AsyncMock(return_value=[{"kbo_number": "0123456789"}]))
        result = await _get_real_kbos(pool, datetime.now(tz=UTC), kbo_dump_run_id=run_id)
        assert result == ["0123456789"]
        sql = pool.fetch.call_args[0][0]
        assert "run_id" in sql

    async def test_uses_since_branch_when_no_run_id(self) -> None:
        since = datetime(2024, 1, 1, tzinfo=UTC)
        pool = _make_pool(fetch=AsyncMock(return_value=[{"kbo_number": "0987654321"}]))
        result = await _get_real_kbos(pool, since, kbo_dump_run_id=None)
        assert result == ["0987654321"]
        sql = pool.fetch.call_args[0][0]
        assert "observed_at" in sql

    async def test_strips_whitespace_from_kbo_number(self) -> None:
        pool = _make_pool(fetch=AsyncMock(return_value=[{"kbo_number": "  0123456789  "}]))
        result = await _get_real_kbos(pool, datetime.now(tz=UTC))
        assert result == ["0123456789"]

    async def test_returns_empty_list_when_no_rows(self) -> None:
        pool = _make_pool(fetch=AsyncMock(return_value=[]))
        result = await _get_real_kbos(pool, datetime.now(tz=UTC))
        assert result == []


class TestGetWebsitePairs:
    async def test_returns_kbo_url_pairs(self) -> None:
        pool = _make_pool(
            fetch=AsyncMock(
                return_value=[
                    {"kbo_number": "0123456789", "url": "https://example.be"},
                    {"kbo_number": "0987654321", "url": "https://other.be"},
                ]
            )
        )
        result = await _get_website_pairs(pool, datetime.now(tz=UTC))
        assert ("0123456789", "https://example.be") in result
        assert ("0987654321", "https://other.be") in result

    async def test_filters_out_null_urls(self) -> None:
        pool = _make_pool(
            fetch=AsyncMock(
                return_value=[
                    {"kbo_number": "0123456789", "url": None},
                    {"kbo_number": "0987654321", "url": "https://example.be"},
                ]
            )
        )
        result = await _get_website_pairs(pool, datetime.now(tz=UTC))
        assert len(result) == 1
        assert result[0][0] == "0987654321"


class TestGetRealKbosForSectorCity:
    async def test_returns_kbos_matching_city_and_nace(self) -> None:
        pool = _make_pool(fetch=AsyncMock(return_value=[{"kbo_number": "0123456789"}]))
        result = await _get_real_kbos_for_sector_city(pool, ["4321"], "antwerpen")
        assert result == ["0123456789"]

    async def test_empty_result(self) -> None:
        pool = _make_pool(fetch=AsyncMock(return_value=[]))
        result = await _get_real_kbos_for_sector_city(pool, ["4321"], "gent")
        assert result == []


class TestGetPlaceholderInputs:
    async def test_combines_name_and_city_for_placeholders(self) -> None:
        pool = _make_pool(
            fetch=AsyncMock(
                side_effect=[
                    [{"kbo_number": "9000000001", "name": "Test BVBA"}],
                    [{"kbo_number": "9000000001", "city": "Gent"}],
                ]
            )
        )
        result = await _get_placeholder_inputs(pool, datetime.now(tz=UTC))
        assert result == [("9000000001", "Test BVBA", "Gent")]

    async def test_skips_entries_with_empty_name(self) -> None:
        pool = _make_pool(
            fetch=AsyncMock(
                side_effect=[
                    [{"kbo_number": "9000000001", "name": None}],
                    [{"kbo_number": "9000000001", "city": "Gent"}],
                ]
            )
        )
        result = await _get_placeholder_inputs(pool, datetime.now(tz=UTC))
        assert result == []

    async def test_missing_city_defaults_to_empty_string(self) -> None:
        pool = _make_pool(
            fetch=AsyncMock(
                side_effect=[
                    [{"kbo_number": "9000000001", "name": "Acme NV"}],
                    [],  # no address rows
                ]
            )
        )
        result = await _get_placeholder_inputs(pool, datetime.now(tz=UTC))
        assert result == [("9000000001", "Acme NV", "")]


class TestRunPipeline:
    async def test_all_sources_disabled_returns_complete_report(self) -> None:
        """All sources off still runs consolidate/matview/scoring and returns a report."""
        pool = _make_pool()
        polite_client = MagicMock()

        config = PipelineConfig(
            sector="elektriciens",
            city="antwerpen",
            sector_slug="elektriciens",
            do_kbo_dump=False,
            do_goudengids=False,
            do_kbopub=False,
            do_nbb=False,
            do_website=False,
            do_search=False,
        )

        with (
            patch("scraper.pipeline.orchestrator.consolidate", new=AsyncMock(return_value=[])),
            patch(
                "scraper.scoring.prospect.refresh_prospect_scores",
                new=AsyncMock(return_value=0),
            ),
        ):
            report = await run_pipeline(config, pool, polite_client)

        assert report.city == "antwerpen"
        assert report.sector == "elektriciens"
        assert "kbo_dump" in report.sources_skipped
        assert "goudengids" in report.sources_skipped
        assert "kbopub_html" in report.sources_skipped
        assert report.ended_at is not None
        assert report.duration_s >= 0.0

    async def test_nbb_skipped_when_no_key(self) -> None:
        """nbb is skipped when nbb_subscription_key is None even if do_nbb=True."""
        pool = _make_pool()
        polite_client = MagicMock()

        config = PipelineConfig(
            sector="elektriciens",
            city="antwerpen",
            sector_slug="elektriciens",
            do_kbo_dump=False,
            do_goudengids=False,
            do_kbopub=False,
            do_nbb=True,
            nbb_subscription_key=None,
            do_website=False,
            do_search=False,
        )

        with (
            patch("scraper.pipeline.orchestrator.consolidate", new=AsyncMock(return_value=[])),
            patch(
                "scraper.scoring.prospect.refresh_prospect_scores",
                new=AsyncMock(return_value=0),
            ),
        ):
            report = await run_pipeline(config, pool, polite_client)

        assert "nbb_authentic" in report.sources_skipped

    async def test_all_sources_enabled_tasks_created(self) -> None:
        """run_pipeline with all sources mocked covers the create_task branches."""
        pool = _make_pool()
        polite_client = MagicMock()

        config = PipelineConfig(
            sector="elektriciens",
            city="antwerpen",
            sector_slug="elektriciens",
            do_kbo_dump=True,
            do_goudengids=True,
            do_kbopub=True,
            do_nbb=True,
            nbb_subscription_key="key",
            do_website=True,
            do_search=True,
        )

        noop = AsyncMock(return_value=None)
        with (
            patch("scraper.pipeline.orchestrator._run_kbo_dump", noop),
            patch("scraper.pipeline.orchestrator._run_goudengids", noop),
            patch("scraper.pipeline.orchestrator._run_kbopub", noop),
            patch("scraper.pipeline.orchestrator._run_nbb", noop),
            patch("scraper.pipeline.orchestrator._run_website", noop),
            patch("scraper.pipeline.orchestrator._run_search", noop),
            patch("scraper.pipeline.orchestrator.consolidate", new=AsyncMock(return_value=[])),
            patch(
                "scraper.scoring.prospect.refresh_prospect_scores", new=AsyncMock(return_value=0)
            ),
        ):
            report = await run_pipeline(config, pool, polite_client)

        assert report.ended_at is not None

    async def test_consolidation_error_does_not_raise(self) -> None:
        pool = _make_pool()
        config = PipelineConfig(
            sector="elektriciens",
            city="antwerpen",
            sector_slug="elektriciens",
            do_kbo_dump=False,
            do_goudengids=False,
            do_kbopub=False,
            do_nbb=False,
            do_website=False,
            do_search=False,
        )
        with (
            patch(
                "scraper.pipeline.orchestrator.consolidate",
                new=AsyncMock(side_effect=RuntimeError("consolidation failed")),
            ),
            patch(
                "scraper.scoring.prospect.refresh_prospect_scores", new=AsyncMock(return_value=0)
            ),
        ):
            report = await run_pipeline(config, pool, MagicMock())
        assert report.ended_at is not None

    async def test_prospect_score_error_does_not_raise(self) -> None:
        pool = _make_pool()
        config = PipelineConfig(
            sector="elektriciens",
            city="antwerpen",
            sector_slug="elektriciens",
            do_kbo_dump=False,
            do_goudengids=False,
            do_kbopub=False,
            do_nbb=False,
            do_website=False,
            do_search=False,
        )
        with (
            patch("scraper.pipeline.orchestrator.consolidate", new=AsyncMock(return_value=[])),
            patch(
                "scraper.scoring.prospect.refresh_prospect_scores",
                new=AsyncMock(side_effect=RuntimeError("scoring failed")),
            ),
        ):
            report = await run_pipeline(config, pool, MagicMock())
        assert report.ended_at is not None

    async def test_orphaned_run_cleanup_error_is_swallowed(self) -> None:
        pool = _make_pool()
        pool.execute = AsyncMock(side_effect=[Exception("db offline"), None, None, None, None])
        config = PipelineConfig(
            sector="elektriciens",
            city="antwerpen",
            sector_slug="elektriciens",
            do_kbo_dump=False,
            do_goudengids=False,
            do_kbopub=False,
            do_nbb=False,
            do_website=False,
            do_search=False,
        )
        with (
            patch("scraper.pipeline.orchestrator.consolidate", new=AsyncMock(return_value=[])),
            patch(
                "scraper.scoring.prospect.refresh_prospect_scores", new=AsyncMock(return_value=0)
            ),
        ):
            report = await run_pipeline(config, pool, MagicMock())
        assert report.ended_at is not None

    async def test_matview_refresh_failure_does_not_raise(self) -> None:
        """Lines 733-734: matview refresh exception is caught and logged, not re-raised."""
        pool = _make_pool()
        pool.execute = AsyncMock(side_effect=[None, RuntimeError("matview failed")])
        config = PipelineConfig(
            sector="elektriciens",
            city="antwerpen",
            sector_slug="elektriciens",
            do_kbo_dump=False,
            do_goudengids=False,
            do_kbopub=False,
            do_nbb=False,
            do_website=False,
            do_search=False,
        )
        with (
            patch("scraper.pipeline.orchestrator.consolidate", new=AsyncMock(return_value=[])),
            patch(
                "scraper.scoring.prospect.refresh_prospect_scores", new=AsyncMock(return_value=0)
            ),
        ):
            report = await run_pipeline(config, pool, MagicMock())
        assert report.ended_at is not None


def _make_report() -> PipelineReport:
    return PipelineReport(
        run_id=None,
        sector="elektriciens",
        city="antwerpen",
        started_at=datetime.now(tz=UTC),
        ended_at=None,
    )


class TestRunKboDump:
    async def test_use_fixture_appends_kbo_dump(self) -> None:
        pool = _make_pool()
        config = PipelineConfig(
            sector="elektriciens",
            city="antwerpen",
            sector_slug="elektriciens",
            use_fixture=True,
        )
        report = _make_report()
        fake_result = MagicMock(observations_inserted=5, enterprises_processed=3)
        with (
            patch(
                "scraper.pipeline.orchestrator._create_fixture_zip",
                return_value=(Path("/fake.zip"), Path("/fake/tmp")),
            ),
            patch(
                "scraper.sources.kbo_dump.ingester.ingest_zip",
                new=AsyncMock(return_value=fake_result),
            ),
        ):
            await _run_kbo_dump(config, pool, datetime.now(tz=UTC), report)
        assert "kbo_dump" in report.sources_run
        assert report.observations_inserted_per_source["kbo_dump"] == 5

    async def test_no_fixture_path_error_stored(self) -> None:
        pool = _make_pool()
        config = PipelineConfig(
            sector="elektriciens",
            city="antwerpen",
            sector_slug="elektriciens",
            use_fixture=False,
            fixture_zip_path=None,
        )
        report = _make_report()
        await _run_kbo_dump(config, pool, datetime.now(tz=UTC), report)
        assert "kbo_dump" in report.sources_failed

    async def test_ingest_exception_stored(self) -> None:
        pool = _make_pool()
        config = PipelineConfig(
            sector="elektriciens",
            city="antwerpen",
            sector_slug="elektriciens",
            use_fixture=True,
        )
        report = _make_report()
        with (
            patch(
                "scraper.pipeline.orchestrator._create_fixture_zip",
                return_value=(Path("/fake.zip"), Path("/fake/tmp")),
            ),
            patch(
                "scraper.sources.kbo_dump.ingester.ingest_zip",
                new=AsyncMock(side_effect=RuntimeError("zip failed")),
            ),
        ):
            await _run_kbo_dump(config, pool, datetime.now(tz=UTC), report)
        assert "kbo_dump" in report.sources_failed
        assert "zip failed" in report.sources_failed["kbo_dump"]

    async def test_fixture_zip_path_branch_stages_and_emits(self) -> None:
        """Lines 368-412: fixture_zip_path branch stages the ZIP and emits via staging tables."""
        from datetime import date

        pool = _make_pool()
        config = PipelineConfig(
            sector="elektriciens",
            city="antwerpen",
            sector_slug="elektriciens",
            use_fixture=False,
            fixture_zip_path=Path("/fake/data.zip"),
        )
        report = _make_report()

        mock_staging = MagicMock()
        mock_staging.skipped = False
        mock_staging.duration_s = 0.5

        run_id = uuid.uuid4()

        with (
            patch(
                "scraper.sources.kbo_dump.staging.stage_zip",
                new=AsyncMock(return_value=mock_staging),
            ),
            patch(
                "scraper.pipeline.batch.resolve_snapshot_date",
                new=AsyncMock(return_value=date(2024, 3, 1)),
            ),
            patch("scraper.pipeline.batch.get_entity_filter", new=AsyncMock(return_value=[])),
            patch("scraper.db.repositories.runs.RunsRepo") as mock_runs_cls,
            patch("scraper.pipeline.batch.emit_phase_a", new=AsyncMock(return_value=0)),
        ):
            mock_runs_cls.return_value.start_run = AsyncMock(return_value=run_id)
            mock_runs_cls.return_value.finish_run = AsyncMock()
            await _run_kbo_dump(config, pool, datetime.now(tz=UTC), report)

        assert "kbo_dump" in report.sources_run
        assert report.observations_inserted_per_source["kbo_dump"] == 0

    async def test_fixture_zip_path_none_snapshot_raises(self) -> None:
        """Line 387: resolve_snapshot_date returns None → RuntimeError stored in report."""
        pool = _make_pool()
        config = PipelineConfig(
            sector="elektriciens",
            city="antwerpen",
            sector_slug="elektriciens",
            use_fixture=False,
            fixture_zip_path=Path("/fake/data.zip"),
        )
        report = _make_report()

        mock_staging = MagicMock()
        mock_staging.skipped = True

        with (
            patch(
                "scraper.sources.kbo_dump.staging.stage_zip",
                new=AsyncMock(return_value=mock_staging),
            ),
            patch(
                "scraper.pipeline.batch.resolve_snapshot_date",
                new=AsyncMock(return_value=None),
            ),
        ):
            await _run_kbo_dump(config, pool, datetime.now(tz=UTC), report)

        assert "kbo_dump" in report.sources_failed
        assert "Staging tables empty" in report.sources_failed["kbo_dump"]

    async def test_fixture_zip_path_with_entities_calls_emit(self) -> None:
        """Line 407: entity_numbers non-empty triggers emit_phase_a call."""
        from datetime import date

        pool = _make_pool()
        config = PipelineConfig(
            sector="elektriciens",
            city="antwerpen",
            sector_slug="elektriciens",
            use_fixture=False,
            fixture_zip_path=Path("/fake/data.zip"),
        )
        report = _make_report()

        mock_staging = MagicMock()
        mock_staging.skipped = True
        run_id = uuid.uuid4()

        with (
            patch(
                "scraper.sources.kbo_dump.staging.stage_zip",
                new=AsyncMock(return_value=mock_staging),
            ),
            patch(
                "scraper.pipeline.batch.resolve_snapshot_date",
                new=AsyncMock(return_value=date(2024, 3, 1)),
            ),
            patch(
                "scraper.pipeline.batch.get_entity_filter",
                new=AsyncMock(return_value=["0403019261"]),
            ),
            patch("scraper.db.repositories.runs.RunsRepo") as mock_runs_cls,
            patch("scraper.pipeline.batch.emit_phase_a", new=AsyncMock(return_value=7)),
        ):
            mock_runs_cls.return_value.start_run = AsyncMock(return_value=run_id)
            mock_runs_cls.return_value.finish_run = AsyncMock()
            await _run_kbo_dump(config, pool, datetime.now(tz=UTC), report)

        assert "kbo_dump" in report.sources_run
        assert report.observations_inserted_per_source["kbo_dump"] == 7


class TestRunGoudengids:
    async def test_happy_path_appends_goudengids(self) -> None:
        pool = _make_pool()
        config = PipelineConfig(
            sector="elektriciens",
            city="antwerpen",
            sector_slug="elektriciens",
        )
        report = _make_report()
        fake_goud = MagicMock(observations_inserted=10, placeholders_created=3)
        with (
            patch("scraper.sources.goudengids.fetcher.BrowserListingFetcher"),
            patch(
                "scraper.sources.goudengids.ingester.ingest_sector_city",
                new=AsyncMock(return_value=fake_goud),
            ),
        ):
            await _run_goudengids(config, pool, MagicMock(), report)
        assert "goudengids" in report.sources_run
        assert report.observations_inserted_per_source["goudengids"] == 10

    async def test_kbo_only_sector_is_skipped(self) -> None:
        pool = _make_pool()
        config = PipelineConfig(
            sector="nonexistent",
            city="antwerpen",
            sector_slug="nonexistent-xyz-sector",
        )
        report = _make_report()
        await _run_goudengids(config, pool, MagicMock(), report)
        assert "goudengids" in report.sources_skipped

    async def test_ingest_exception_stored(self) -> None:
        pool = _make_pool()
        config = PipelineConfig(
            sector="elektriciens",
            city="antwerpen",
            sector_slug="elektriciens",
        )
        report = _make_report()
        with (
            patch("scraper.sources.goudengids.fetcher.BrowserListingFetcher"),
            patch(
                "scraper.sources.goudengids.ingester.ingest_sector_city",
                new=AsyncMock(side_effect=RuntimeError("goud failed")),
            ),
        ):
            await _run_goudengids(config, pool, MagicMock(), report)
        assert "goudengids" in report.sources_failed


class TestRunKbopub:
    async def test_with_real_kbos_appends_kbopub_html(self) -> None:
        pool = _make_pool(fetch=AsyncMock(return_value=[{"kbo_number": "0403019261"}]))
        config = PipelineConfig(
            sector="elektriciens",
            city="antwerpen",
            sector_slug="elektriciens",
        )
        report = _make_report()
        fake_result = MagicMock(observations_inserted=3, kbos_processed=1)
        with patch(
            "scraper.sources.kbopub_html.ingester.ingest_kbos",
            new=AsyncMock(return_value=fake_result),
        ):
            await _run_kbopub(config, pool, MagicMock(), datetime.now(tz=UTC), report)
        assert "kbopub_html" in report.sources_run

    async def test_no_real_kbos_skips_source(self) -> None:
        pool = _make_pool(fetch=AsyncMock(return_value=[]))
        config = PipelineConfig(
            sector="elektriciens",
            city="antwerpen",
            sector_slug="elektriciens",
        )
        report = _make_report()
        await _run_kbopub(config, pool, MagicMock(), datetime.now(tz=UTC), report)
        assert "kbopub_html" in report.sources_skipped

    async def test_ingest_exception_stored(self) -> None:
        pool = _make_pool(fetch=AsyncMock(return_value=[{"kbo_number": "0403019261"}]))
        config = PipelineConfig(
            sector="elektriciens",
            city="antwerpen",
            sector_slug="elektriciens",
        )
        report = _make_report()
        with patch(
            "scraper.sources.kbopub_html.ingester.ingest_kbos",
            new=AsyncMock(side_effect=RuntimeError("kbopub err")),
        ):
            await _run_kbopub(config, pool, MagicMock(), datetime.now(tz=UTC), report)
        assert "kbopub_html" in report.sources_failed


class TestRunNbb:
    async def test_with_real_kbos_appends_nbb(self) -> None:
        pool = _make_pool(fetch=AsyncMock(return_value=[{"kbo_number": "0403019261"}]))
        config = PipelineConfig(
            sector="elektriciens",
            city="antwerpen",
            sector_slug="elektriciens",
            nbb_subscription_key="test-key",
        )
        report = _make_report()
        fake_result = MagicMock(observations_inserted=2, kbos_processed=1)
        with (
            patch("scraper.sources.nbb_authentic.client.NbbClient"),
            patch(
                "scraper.sources.nbb_authentic.ingester.ingest_kbos",
                new=AsyncMock(return_value=fake_result),
            ),
        ):
            await _run_nbb(config, pool, MagicMock(), datetime.now(tz=UTC), report)
        assert "nbb_authentic" in report.sources_run

    async def test_no_real_kbos_skips_source(self) -> None:
        pool = _make_pool(fetch=AsyncMock(return_value=[]))
        config = PipelineConfig(
            sector="elektriciens",
            city="antwerpen",
            sector_slug="elektriciens",
            nbb_subscription_key="test-key",
        )
        report = _make_report()
        await _run_nbb(config, pool, MagicMock(), datetime.now(tz=UTC), report)
        assert "nbb_authentic" in report.sources_skipped

    async def test_ingest_exception_stored(self) -> None:
        pool = _make_pool(fetch=AsyncMock(return_value=[{"kbo_number": "0403019261"}]))
        config = PipelineConfig(
            sector="elektriciens",
            city="antwerpen",
            sector_slug="elektriciens",
            nbb_subscription_key="test-key",
        )
        report = _make_report()
        with (
            patch("scraper.sources.nbb_authentic.client.NbbClient"),
            patch(
                "scraper.sources.nbb_authentic.ingester.ingest_kbos",
                new=AsyncMock(side_effect=RuntimeError("nbb err")),
            ),
        ):
            await _run_nbb(config, pool, MagicMock(), datetime.now(tz=UTC), report)
        assert "nbb_authentic" in report.sources_failed


class TestRunWebsite:
    async def test_with_pairs_appends_website(self) -> None:
        pool = _make_pool(
            fetch=AsyncMock(
                return_value=[{"kbo_number": "0403019261", "url": "https://example.be"}]
            )
        )
        config = PipelineConfig(
            sector="elektriciens",
            city="antwerpen",
            sector_slug="elektriciens",
        )
        report = _make_report()
        fake_result = MagicMock(observations_inserted=4, kbos_processed=1)
        with patch(
            "scraper.sources.website.ingester.ingest_kbos",
            new=AsyncMock(return_value=fake_result),
        ):
            await _run_website(config, pool, MagicMock(), datetime.now(tz=UTC), report)
        assert "website" in report.sources_run

    async def test_no_pairs_skips_source(self) -> None:
        pool = _make_pool(fetch=AsyncMock(return_value=[]))
        config = PipelineConfig(
            sector="elektriciens",
            city="antwerpen",
            sector_slug="elektriciens",
        )
        report = _make_report()
        await _run_website(config, pool, MagicMock(), datetime.now(tz=UTC), report)
        assert "website" in report.sources_skipped

    async def test_ingest_exception_stored(self) -> None:
        pool = _make_pool(
            fetch=AsyncMock(
                return_value=[{"kbo_number": "0403019261", "url": "https://example.be"}]
            )
        )
        config = PipelineConfig(
            sector="elektriciens",
            city="antwerpen",
            sector_slug="elektriciens",
        )
        report = _make_report()
        with patch(
            "scraper.sources.website.ingester.ingest_kbos",
            new=AsyncMock(side_effect=RuntimeError("website err")),
        ):
            await _run_website(config, pool, MagicMock(), datetime.now(tz=UTC), report)
        assert "website" in report.sources_failed


class TestRunSearch:
    async def test_with_placeholders_appends_ddg_brave(self) -> None:
        pool = _make_pool(
            fetch=AsyncMock(
                side_effect=[
                    [{"kbo_number": "9000000001", "name": "Test NV"}],
                    [{"kbo_number": "9000000001", "city": "Antwerpen"}],
                ]
            )
        )
        config = PipelineConfig(
            sector="elektriciens",
            city="antwerpen",
            sector_slug="elektriciens",
        )
        report = _make_report()
        fake_result = MagicMock(observations_inserted=1, queries_processed=1)
        with (
            patch("scraper.sources.ddg_brave.ddg_client.DdgClient"),
            patch(
                "scraper.sources.ddg_brave.ingester.validate_companies",
                new=AsyncMock(return_value=fake_result),
            ),
        ):
            await _run_search(config, pool, MagicMock(), datetime.now(tz=UTC), report)
        assert "ddg_brave" in report.sources_run

    async def test_no_placeholders_skips_source(self) -> None:
        pool = _make_pool(fetch=AsyncMock(side_effect=[[], []]))
        config = PipelineConfig(
            sector="elektriciens",
            city="antwerpen",
            sector_slug="elektriciens",
        )
        report = _make_report()
        await _run_search(config, pool, MagicMock(), datetime.now(tz=UTC), report)
        assert "ddg_brave" in report.sources_skipped

    async def test_search_exception_stored(self) -> None:
        pool = _make_pool(
            fetch=AsyncMock(
                side_effect=[
                    [{"kbo_number": "9000000001", "name": "Test NV"}],
                    [{"kbo_number": "9000000001", "city": "Antwerpen"}],
                ]
            )
        )
        config = PipelineConfig(
            sector="elektriciens",
            city="antwerpen",
            sector_slug="elektriciens",
        )
        report = _make_report()
        with (
            patch("scraper.sources.ddg_brave.ddg_client.DdgClient"),
            patch(
                "scraper.sources.ddg_brave.ingester.validate_companies",
                new=AsyncMock(side_effect=RuntimeError("search err")),
            ),
        ):
            await _run_search(config, pool, MagicMock(), datetime.now(tz=UTC), report)
        assert "ddg_brave" in report.sources_failed

    async def test_brave_client_used_when_key_set(self) -> None:
        """Line 610: brave_subscription_key set → BraveClient instantiated."""
        pool = _make_pool(
            fetch=AsyncMock(
                side_effect=[
                    [{"kbo_number": "9000000001", "name": "Test NV"}],
                    [{"kbo_number": "9000000001", "city": "Antwerpen"}],
                ]
            )
        )
        config = PipelineConfig(
            sector="elektriciens",
            city="antwerpen",
            sector_slug="elektriciens",
            brave_subscription_key="brave-key-123",
        )
        report = _make_report()
        fake_result = MagicMock(observations_inserted=1, queries_processed=1)
        with (
            patch("scraper.sources.ddg_brave.brave_client.BraveClient"),
            patch("scraper.sources.ddg_brave.ddg_client.DdgClient"),
            patch(
                "scraper.sources.ddg_brave.ingester.validate_companies",
                new=AsyncMock(return_value=fake_result),
            ),
        ):
            await _run_search(config, pool, MagicMock(), datetime.now(tz=UTC), report)
        assert "ddg_brave" in report.sources_run
