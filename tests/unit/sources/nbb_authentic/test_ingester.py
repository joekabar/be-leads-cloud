"""Unit tests for nbb_authentic ingester — transient error resilience."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from scraper.lib.errors import NbbAuthError, NbbNotFoundError, RetriesExhaustedError
from scraper.sources.nbb_authentic.ingester import ingest_kbos
from scraper.sources.nbb_authentic.parser import ReferenceRow

_KBO = "0439401387"

_REF = ReferenceRow(
    reference_number="2024-00000148",
    deposit_date=date(2024, 9, 12),
    exercise_start=date(2023, 1, 1),
    exercise_end=date(2023, 12, 31),
    model_type="ABBREVIATED",
    language="NL",
    deposit_type="DEPOSIT",
    filing_method="STRUCTURED",
    accounting_data_url="https://ws.cbso.nbb.be/authentic/deposit/2024-00000148/accountingData",
)


def _make_pool() -> MagicMock:
    pool = MagicMock()
    pool.fetchrow = AsyncMock(return_value=None)
    pool.fetch = AsyncMock(return_value=[])
    pool.execute = AsyncMock()
    # runs repo start/finish
    pool.fetchrow = AsyncMock(return_value=None)
    return pool


def _make_runs_repo(pool: MagicMock) -> None:
    """Patch RunsRepo and ObservationsRepo on the pool mock."""
    import uuid

    _run_id = uuid.uuid4()

    async def _fetchrow(sql: str, *args: object) -> object:
        if "run_log" in sql or "INSERT" in sql:
            return {"id": _run_id}
        return None

    pool.fetchrow = AsyncMock(side_effect=_fetchrow)


@pytest.fixture()
def pool() -> MagicMock:
    import uuid

    p = MagicMock()
    run_id = uuid.uuid4()
    p.fetchrow = AsyncMock(return_value={"id": run_id})
    p.fetch = AsyncMock(return_value=[])
    p.execute = AsyncMock()
    return p


@pytest.fixture()
def nbb_client() -> MagicMock:
    return MagicMock()


@pytest.mark.asyncio
async def test_transient_error_on_references_is_skipped_not_raised(
    pool: MagicMock, nbb_client: MagicMock
) -> None:
    """RetriesExhaustedError on get_references must not crash the source."""
    from unittest.mock import patch

    nbb_client.get_references = AsyncMock(
        side_effect=RetriesExhaustedError("Exhausted 5 attempts for url")
    )

    with (
        patch("scraper.sources.nbb_authentic.ingester.RunsRepo") as mock_runs,
        patch("scraper.sources.nbb_authentic.ingester.ObservationsRepo") as mock_obs,
    ):
        import uuid

        mock_runs.return_value.start_run = AsyncMock(return_value=uuid.uuid4())
        mock_runs.return_value.finish_run = AsyncMock()
        mock_obs.return_value.insert_many = AsyncMock(return_value=[])
        pool.execute = AsyncMock()

        report = await ingest_kbos([_KBO], pool, nbb_client, skip_recent_hours=0)

    assert report.kbos_transient_error == 1
    assert report.kbos_processed == 0
    assert report.observations_inserted == 0


@pytest.mark.asyncio
async def test_auth_error_on_references_is_reraised(pool: MagicMock, nbb_client: MagicMock) -> None:
    """NbbAuthError must propagate — key is broken, stop immediately."""
    nbb_client.get_references = AsyncMock(side_effect=NbbAuthError(401, "url", "invalid key"))

    with (
        pytest.raises(NbbAuthError),
        pytest.MonkeyPatch().context() as mp,
    ):
        import uuid

        mp.setattr(
            "scraper.sources.nbb_authentic.ingester.RunsRepo",
            lambda _: MagicMock(
                start_run=AsyncMock(return_value=uuid.uuid4()),
                finish_run=AsyncMock(),
            ),
        )
        mp.setattr(
            "scraper.sources.nbb_authentic.ingester.ObservationsRepo",
            lambda _: MagicMock(insert_many=AsyncMock(return_value=[])),
        )
        pool.execute = AsyncMock()
        await ingest_kbos([_KBO], pool, nbb_client, skip_recent_hours=0)


@pytest.mark.asyncio
async def test_not_found_increments_counter(pool: MagicMock, nbb_client: MagicMock) -> None:
    """NbbNotFoundError must be counted and not crash the source."""
    nbb_client.get_references = AsyncMock(side_effect=NbbNotFoundError(_KBO, "url"))

    with (
        pytest.MonkeyPatch().context() as mp,
    ):
        import uuid

        mp.setattr(
            "scraper.sources.nbb_authentic.ingester.RunsRepo",
            lambda _: MagicMock(
                start_run=AsyncMock(return_value=uuid.uuid4()),
                finish_run=AsyncMock(),
            ),
        )
        mp.setattr(
            "scraper.sources.nbb_authentic.ingester.ObservationsRepo",
            lambda _: MagicMock(insert_many=AsyncMock(return_value=[])),
        )
        pool.execute = AsyncMock()
        report = await ingest_kbos([_KBO], pool, nbb_client, skip_recent_hours=0)

    assert report.kbos_not_found == 1
    assert report.kbos_processed == 0


@pytest.mark.asyncio
async def test_transient_error_on_pdf_is_skipped(pool: MagicMock, nbb_client: MagicMock) -> None:
    """RetriesExhaustedError on get_accounting_pdf must skip that filing, not crash."""
    nbb_client.get_references = AsyncMock(return_value=[_REF])
    nbb_client.get_accounting_pdf = AsyncMock(
        side_effect=RetriesExhaustedError("Exhausted 5 attempts for pdf url")
    )

    with pytest.MonkeyPatch().context() as mp:
        import uuid

        mp.setattr(
            "scraper.sources.nbb_authentic.ingester.RunsRepo",
            lambda _: MagicMock(
                start_run=AsyncMock(return_value=uuid.uuid4()),
                finish_run=AsyncMock(),
            ),
        )
        mp.setattr(
            "scraper.sources.nbb_authentic.ingester.ObservationsRepo",
            lambda _: MagicMock(insert_many=AsyncMock(return_value=[])),
        )
        pool.execute = AsyncMock()
        report = await ingest_kbos([_KBO], pool, nbb_client, skip_recent_hours=0)

    assert report.kbos_processed == 1
    assert report.observations_inserted == 0
