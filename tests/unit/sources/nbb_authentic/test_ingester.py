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


# ── additional coverage ───────────────────────────────────────────────────────


def _patch_repos(mp: pytest.MonkeyPatch) -> None:
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


async def test_is_fresh_returns_true_when_row_found(pool: MagicMock) -> None:
    from scraper.sources.nbb_authentic.ingester import _is_fresh

    pool.fetchrow = AsyncMock(return_value={"1": 1})
    result = await _is_fresh(pool, _KBO, skip_recent_hours=24)
    assert result is True


async def test_is_fresh_returns_false_when_no_row(pool: MagicMock) -> None:
    from scraper.sources.nbb_authentic.ingester import _is_fresh

    pool.fetchrow = AsyncMock(return_value=None)
    result = await _is_fresh(pool, _KBO, skip_recent_hours=24)
    assert result is False


async def test_invalid_kbo_is_skipped(pool: MagicMock, nbb_client: MagicMock) -> None:
    with pytest.MonkeyPatch().context() as mp:
        _patch_repos(mp)
        pool.execute = AsyncMock()
        report = await ingest_kbos(["0000000000"], pool, nbb_client, skip_recent_hours=0)

    assert report.kbos_processed == 0


async def test_fresh_kbo_is_skipped(pool: MagicMock, nbb_client: MagicMock) -> None:
    pool.fetchrow = AsyncMock(return_value={"1": 1})

    with pytest.MonkeyPatch().context() as mp:
        _patch_repos(mp)
        pool.execute = AsyncMock()
        report = await ingest_kbos([_KBO], pool, nbb_client, skip_recent_hours=24)

    assert report.kbos_processed == 0


async def test_years_back_filters_old_references(pool: MagicMock, nbb_client: MagicMock) -> None:
    from datetime import date

    old_ref = _REF.__class__(
        reference_number="2010-00000001",
        deposit_date=date(2010, 1, 1),
        exercise_start=date(2009, 1, 1),
        exercise_end=date(2009, 12, 31),
        model_type="ABBREVIATED",
        language="NL",
        deposit_type="DEPOSIT",
        filing_method="STRUCTURED",
        accounting_data_url=None,
    )
    nbb_client.get_references = AsyncMock(return_value=[old_ref])

    with pytest.MonkeyPatch().context() as mp:
        _patch_repos(mp)
        pool.execute = AsyncMock()
        report = await ingest_kbos(
            [_KBO],
            pool,
            nbb_client,
            skip_recent_hours=0,
            years_back=3,
            _today=date(2024, 1, 1),
        )

    assert report.references_total == 0
    assert report.kbos_processed == 1


async def test_no_accounting_data_url_skips_ref(pool: MagicMock, nbb_client: MagicMock) -> None:
    from datetime import date

    ref_no_url = _REF.__class__(
        reference_number="2024-00000999",
        deposit_date=date(2024, 1, 1),
        exercise_start=date(2023, 1, 1),
        exercise_end=date(2023, 12, 31),
        model_type="ABBREVIATED",
        language="NL",
        deposit_type="DEPOSIT",
        filing_method="STRUCTURED",
        accounting_data_url=None,
    )
    nbb_client.get_references = AsyncMock(return_value=[ref_no_url])
    nbb_client.get_accounting_pdf = AsyncMock()

    with pytest.MonkeyPatch().context() as mp:
        _patch_repos(mp)
        pool.execute = AsyncMock()
        report = await ingest_kbos([_KBO], pool, nbb_client, skip_recent_hours=0)

    nbb_client.get_accounting_pdf.assert_not_called()
    assert report.kbos_processed == 1


async def test_not_found_error_on_pdf_is_skipped(pool: MagicMock, nbb_client: MagicMock) -> None:
    from scraper.lib.errors import NbbNotFoundError

    nbb_client.get_references = AsyncMock(return_value=[_REF])
    nbb_client.get_accounting_pdf = AsyncMock(
        side_effect=NbbNotFoundError(_KBO, "https://ws.cbso.nbb.be/ref/pdf")
    )

    with pytest.MonkeyPatch().context() as mp:
        _patch_repos(mp)
        pool.execute = AsyncMock()
        report = await ingest_kbos([_KBO], pool, nbb_client, skip_recent_hours=0)

    assert report.kbos_processed == 1
    assert report.observations_inserted == 0


async def test_successful_pdf_parse_produces_observations(
    pool: MagicMock, nbb_client: MagicMock
) -> None:
    from unittest.mock import patch

    nbb_client.get_references = AsyncMock(return_value=[_REF])
    nbb_client.get_accounting_pdf = AsyncMock(return_value=b"fake_pdf_bytes")
    fake_obs = MagicMock()

    with pytest.MonkeyPatch().context() as mp:
        _patch_repos(mp)
        mp.setattr(
            "scraper.sources.nbb_authentic.ingester.ObservationsRepo",
            lambda _: MagicMock(insert_many=AsyncMock(return_value=[1])),
        )
        pool.execute = AsyncMock()

        with (
            patch(
                "scraper.sources.nbb_authentic.ingester.parse_accounting_pdf",
                return_value=MagicMock(),
            ),
            patch(
                "scraper.sources.nbb_authentic.ingester.filing_to_observations",
                return_value=[fake_obs],
            ),
        ):
            report = await ingest_kbos([_KBO], pool, nbb_client, skip_recent_hours=0)

    assert report.kbos_processed == 1
    assert report.observations_inserted == 1


async def test_buffer_flush_at_100_observations(pool: MagicMock, nbb_client: MagicMock) -> None:
    from unittest.mock import patch

    nbb_client.get_references = AsyncMock(return_value=[_REF])
    nbb_client.get_accounting_pdf = AsyncMock(return_value=b"fake_pdf_bytes")
    fake_obs_list = [MagicMock() for _ in range(100)]

    inserted: list[int] = []

    async def _insert_many(obs: list[object]) -> list[object]:
        inserted.append(len(obs))
        return list(range(len(obs)))

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
            lambda _: MagicMock(insert_many=AsyncMock(side_effect=_insert_many)),
        )
        pool.execute = AsyncMock()

        with (
            patch(
                "scraper.sources.nbb_authentic.ingester.parse_accounting_pdf",
                return_value=MagicMock(),
            ),
            patch(
                "scraper.sources.nbb_authentic.ingester.filing_to_observations",
                return_value=fake_obs_list,
            ),
        ):
            report = await ingest_kbos([_KBO], pool, nbb_client, skip_recent_hours=0)

    assert report.observations_inserted == 100
    assert len(inserted) >= 1
