"""Integration tests for the pipeline orchestrator (mocked source ingesters)."""

from __future__ import annotations

import asyncio
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


class _FakeGoudReport:
    observations_inserted = 2
    placeholders_created = 1


class _FakeKbopubReport:
    observations_inserted = 1
    kbos_processed = 1


class _FakeWebReport:
    observations_inserted = 0
    kbos_processed = 0
    fetch_failures = 0


class _FakeSearchReport:
    observations_inserted = 0
    queries_processed = 0


async def test_sources_run_recorded(clean_pool, pipeline_synthetic_zip) -> None:
    """kbo_dump and goudengids both appear in sources_run when both are enabled."""
    config = _make_config(
        do_goudengids=True,
        do_kbopub=True,
        do_nbb=False,
        do_website=True,
        do_search=True,
    )
    polite = _mock_polite_client()

    with (
        patch.multiple(
            "scraper.pipeline.orchestrator",
            **{
                "_create_fixture_zip": MagicMock(
                    return_value=(pipeline_synthetic_zip, Path("/tmp/fake"))
                ),
            },
        ),
        patch(
            "scraper.sources.kbo_dump.ingester.ingest_zip",
            new=AsyncMock(return_value=_FakeKboDumpReport()),
        ),
        patch(
            "scraper.sources.goudengids.ingester.ingest_sector_city",
            new=AsyncMock(return_value=_FakeGoudReport()),
        ),
        patch(
            "scraper.sources.goudengids.fetcher.BrowserListingFetcher",
            return_value=MagicMock(),
        ),
        patch(
            "scraper.sources.kbopub_html.ingester.ingest_kbos",
            new=AsyncMock(return_value=_FakeKbopubReport()),
        ),
        patch(
            "scraper.sources.website.ingester.ingest_kbos",
            new=AsyncMock(return_value=_FakeWebReport()),
        ),
        patch(
            "scraper.sources.ddg_brave.ingester.validate_companies",
            new=AsyncMock(return_value=_FakeSearchReport()),
        ),
        patch(
            "scraper.pipeline.consolidate.consolidate",
            new=AsyncMock(return_value=[]),
        ),
    ):
        report = await run_pipeline(config, clean_pool, polite)

    assert isinstance(report, PipelineReport)
    assert "kbo_dump" in report.sources_run
    assert "goudengids" in report.sources_run


async def test_wave_b_starts_after_wave_a_completes(clean_pool, pipeline_synthetic_zip) -> None:
    """Wave B sources (kbopub, website, goudengids) start only after kbo_dump (Wave A) finishes."""
    kbo_done = asyncio.Event()
    wave_b_saw_kbo: list[bool] = []

    async def fake_kbo(*_a, **_kw) -> _FakeKboDumpReport:
        await asyncio.sleep(0.02)
        kbo_done.set()
        return _FakeKboDumpReport()

    async def fake_goud(*_a, **_kw) -> _FakeGoudReport:
        wave_b_saw_kbo.append(kbo_done.is_set())
        return _FakeGoudReport()

    async def fake_kbopub(_kbos, _pool, _limiter, **_kw) -> _FakeKbopubReport:
        wave_b_saw_kbo.append(kbo_done.is_set())
        return _FakeKbopubReport()

    async def fake_website(_pairs, _pool, _polite, **_kw) -> _FakeWebReport:
        wave_b_saw_kbo.append(kbo_done.is_set())
        return _FakeWebReport()

    config = _make_config(do_goudengids=True, do_kbopub=True, do_website=True)
    polite = _mock_polite_client()

    # Mock DB helpers so kbopub/website aren't skipped due to empty DB
    with (
        patch.multiple(
            "scraper.pipeline.orchestrator",
            **{
                "_create_fixture_zip": MagicMock(
                    return_value=(pipeline_synthetic_zip, Path("/tmp/fake"))
                ),
                "_get_real_kbos": AsyncMock(return_value=["0123456789"]),
                "_get_website_pairs": AsyncMock(
                    return_value=[("0123456789", "https://example.com")]
                ),
            },
        ),
        patch("scraper.sources.kbo_dump.ingester.ingest_zip", new=AsyncMock(side_effect=fake_kbo)),
        patch(
            "scraper.sources.goudengids.ingester.ingest_sector_city",
            new=AsyncMock(side_effect=fake_goud),
        ),
        patch("scraper.sources.goudengids.fetcher.BrowserListingFetcher", return_value=MagicMock()),
        patch(
            "scraper.sources.kbopub_html.ingester.ingest_kbos",
            new=AsyncMock(side_effect=fake_kbopub),
        ),
        patch(
            "scraper.sources.website.ingester.ingest_kbos", new=AsyncMock(side_effect=fake_website)
        ),
        patch("scraper.pipeline.consolidate.consolidate", new=AsyncMock(return_value=[])),
    ):
        await run_pipeline(config, clean_pool, polite)

    assert wave_b_saw_kbo, "Wave B tasks did not run"
    assert all(wave_b_saw_kbo), "Wave B started before Wave A (kbo_dump) completed"


async def test_wave_b_failure_does_not_cancel_siblings(clean_pool, pipeline_synthetic_zip) -> None:
    """A failure in one Wave B source (kbopub) does not prevent website from running."""
    config = _make_config(
        do_goudengids=False,
        do_kbopub=True,
        do_nbb=False,
        do_website=True,
        do_search=False,
    )
    polite = _mock_polite_client()

    async def kbopub_boom(*_a, **_kw) -> None:
        raise RuntimeError("kbopub exploded")

    with (
        patch.multiple(
            "scraper.pipeline.orchestrator",
            **{
                "_create_fixture_zip": MagicMock(
                    return_value=(pipeline_synthetic_zip, Path("/tmp/fake"))
                ),
                "_get_real_kbos": AsyncMock(return_value=["0123456789"]),
                "_get_website_pairs": AsyncMock(
                    return_value=[("0123456789", "https://example.com")]
                ),
            },
        ),
        patch(
            "scraper.sources.kbo_dump.ingester.ingest_zip",
            new=AsyncMock(return_value=_FakeKboDumpReport()),
        ),
        patch(
            "scraper.sources.kbopub_html.ingester.ingest_kbos",
            new=AsyncMock(side_effect=kbopub_boom),
        ),
        patch(
            "scraper.sources.website.ingester.ingest_kbos",
            new=AsyncMock(return_value=_FakeWebReport()),
        ),
        patch("scraper.pipeline.consolidate.consolidate", new=AsyncMock(return_value=[])),
    ):
        report = await run_pipeline(config, clean_pool, polite)

    assert "kbopub_html" in report.sources_failed
    assert "kbopub exploded" in report.sources_failed["kbopub_html"]
    assert "website" in report.sources_run


async def test_one_source_failure_does_not_abort_pipeline(
    clean_pool, pipeline_synthetic_zip
) -> None:
    """If goudengids fails (Wave A), kbo_dump still completes."""
    config = _make_config(
        do_goudengids=True,
        do_kbopub=False,
        do_nbb=False,
        do_website=False,
        do_search=False,
    )

    polite = _mock_polite_client()

    with (
        patch.multiple(
            "scraper.pipeline.orchestrator",
            **{
                "_create_fixture_zip": MagicMock(
                    return_value=(pipeline_synthetic_zip, Path("/tmp/x"))
                )
            },
        ),
        patch(
            "scraper.sources.kbo_dump.ingester.ingest_zip",
            new=AsyncMock(return_value=_FakeKboDumpReport()),
        ),
        patch(
            "scraper.sources.goudengids.fetcher.BrowserListingFetcher",
            side_effect=RuntimeError("goudengids boom"),
        ),
        patch("scraper.pipeline.consolidate.consolidate", new=AsyncMock(return_value=[])),
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
