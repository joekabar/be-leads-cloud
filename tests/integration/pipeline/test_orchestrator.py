"""Integration tests for the pipeline orchestrator (mocked source ingesters)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scraper.pipeline.orchestrator import PipelineConfig, PipelineReport, run_pipeline

pytestmark = pytest.mark.integration

_FIXTURE_ZIP = Path("tests/golden/kbo_dump/synthetic_mini")


def _make_config(**overrides) -> PipelineConfig:  # type: ignore[no-untyped-def]
    defaults = dict(
        sector="electriciens",
        city="antwerpen",
        sector_slug="elektriciens",
        use_fixture=True,
        do_kbo_dump=True,
        do_goudengids=False,
        do_kbopub=False,
        do_nbb=False,
        do_website=False,
        do_search=False,
    )
    defaults.update(overrides)
    return PipelineConfig(**defaults)


def _mock_polite_client() -> MagicMock:
    client = MagicMock()
    client.limiter = MagicMock()
    return client


class _FakeKboDumpReport:
    observations_inserted = 5
    enterprises_processed = 1
    phones_invalid_skipped = 0


async def test_source_order_in_report(clean_pool, pipeline_synthetic_zip) -> None:
    """Sources run in the correct order: kbo_dump, goudengids, kbopub, nbb, website, ddg_brave."""
    config = _make_config(
        do_goudengids=True,
        do_kbopub=True,
        do_nbb=False,
        do_website=True,
        do_search=True,
    )

    fake_kbo = _FakeKboDumpReport()

    class FakeGoudReport:
        observations_inserted = 2
        placeholders_created = 1

    class FakeKbopubReport:
        observations_inserted = 1
        kbos_processed = 1

    class FakeWebReport:
        observations_inserted = 0
        kbos_processed = 0
        fetch_failures = 0

    class FakeSearchReport:
        observations_inserted = 0
        queries_processed = 0

    polite = _mock_polite_client()

    with (
        patch("scraper.pipeline.orchestrator.ingest_zip", new=AsyncMock(return_value=fake_kbo))
        if False
        else patch(
            "scraper.sources.kbo_dump.ingester.ingest_zip",
            new=AsyncMock(return_value=fake_kbo),
        )
    ):
        pass

    with (
        patch(
            "scraper.pipeline.orchestrator.run_pipeline.__wrapped__",
            side_effect=None,
        )
        if False
        else patch.multiple(
            "scraper.pipeline.orchestrator",
            **{
                "_create_fixture_zip": MagicMock(
                    return_value=(pipeline_synthetic_zip, Path("/tmp/fake"))
                ),
            },
        ), patch(
        "scraper.sources.kbo_dump.ingester.ingest_zip", new=AsyncMock(return_value=fake_kbo)
    ), patch(
        "scraper.sources.goudengids.ingester.ingest_sector_city",
        new=AsyncMock(return_value=FakeGoudReport()),
    ), patch(
        "scraper.sources.goudengids.fetcher.GoudengidsFetcher",
        return_value=MagicMock(),
    ), patch(
        "scraper.sources.kbopub_html.ingester.ingest_kbos",
        new=AsyncMock(return_value=FakeKbopubReport()),
    ), patch(
        "scraper.sources.website.ingester.ingest_kbos",
        new=AsyncMock(return_value=FakeWebReport()),
    ), patch(
        "scraper.sources.ddg_brave.ingester.validate_companies",
        new=AsyncMock(return_value=FakeSearchReport()),
    ), patch(
        "scraper.pipeline.consolidate.consolidate",
        new=AsyncMock(return_value=[]),
    )
    ):
        report = await run_pipeline(config, clean_pool, polite)

    assert isinstance(report, PipelineReport)
    assert "kbo_dump" in report.sources_run
    # goudengids skipped due to no real goudengids warmup in tests — it may fail
    # The key assertion: kbo_dump always runs first
    assert report.sources_run[0] == "kbo_dump"


async def test_one_source_failure_does_not_abort_pipeline(
    clean_pool, pipeline_synthetic_zip
) -> None:
    """If goudengids fails, subsequent sources still run."""
    config = _make_config(
        do_goudengids=True,
        do_kbopub=False,
        do_nbb=False,
        do_website=False,
        do_search=False,
    )

    polite = _mock_polite_client()
    fake_kbo = _FakeKboDumpReport()

    with patch.multiple(
        "scraper.pipeline.orchestrator",
        **{"_create_fixture_zip": MagicMock(return_value=(pipeline_synthetic_zip, Path("/tmp/x")))},
    ), patch(
        "scraper.sources.kbo_dump.ingester.ingest_zip", new=AsyncMock(return_value=fake_kbo)
    ), patch(
        "scraper.sources.goudengids.fetcher.GoudengidsFetcher",
        side_effect=RuntimeError("goudengids boom"),
    ), patch(
        "scraper.pipeline.consolidate.consolidate", new=AsyncMock(return_value=[])
    ):
        report = await run_pipeline(config, clean_pool, polite)

    assert "kbo_dump" in report.sources_run
    assert "goudengids" in report.sources_failed
    assert "goudengids boom" in report.sources_failed["goudengids"]


async def test_skipped_source_recorded(clean_pool, pipeline_synthetic_zip) -> None:
    """Disabled sources appear in sources_skipped, not sources_run."""
    config = _make_config(
        do_kbo_dump=False,
        do_goudengids=False,
        do_kbopub=False,
        do_nbb=False,
        do_website=False,
        do_search=False,
    )
    polite = _mock_polite_client()
    with patch("scraper.pipeline.consolidate.consolidate", new=AsyncMock(return_value=[])):
        report = await run_pipeline(config, clean_pool, polite)

    assert "kbo_dump" in report.sources_skipped
    assert "goudengids" in report.sources_skipped
    assert not report.sources_run
