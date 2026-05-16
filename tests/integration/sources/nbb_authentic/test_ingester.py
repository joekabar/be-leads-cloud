from __future__ import annotations

import re
from datetime import date
from typing import TYPE_CHECKING

import httpx
import pytest
import respx

from scraper.sources.nbb_authentic.ingester import NbbReport, ingest_kbos

if TYPE_CHECKING:
    from scraper.sources.nbb_authentic.client import NbbClient

from .conftest import nbb_side_effect

pytestmark = pytest.mark.integration

_NBB_RE = re.compile(r".*ws\.cbso\.nbb\.be.*")

# MICRO PDF (used for all mocked PDF fetches) yields revenue (9900) + profit_loss, no employees.
# Per reference: 2 observations.
_OBS_PER_REF = 2


@pytest.fixture()
async def fresh_pool(clean_pool):  # type: ignore[no-untyped-def]
    await clean_pool.execute("SELECT refresh_companies_current()")
    return clean_pool


# ---------------------------------------------------------------------------
# Three KBOs — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_inserts_observations(fresh_pool, nbb_client: NbbClient) -> None:
    # 0439401387: 3 refs × 2 obs (MICRO PDF, no employees) = 6
    # 0502699332: 1 ref × 2 obs = 2
    # 0345678997: unknown → 404 → 0
    with respx.mock:
        respx.get(_NBB_RE).mock(side_effect=nbb_side_effect)
        report = await ingest_kbos(
            ["0439401387", "0502699332", "0345678997"],
            fresh_pool,
            nbb_client,
            skip_recent_hours=0,
        )

    assert isinstance(report, NbbReport)
    assert report.kbos_processed == 3
    assert report.observations_inserted == 8  # 6 + 2 + 0


@pytest.mark.asyncio
async def test_batch_observation_fields(fresh_pool, nbb_client: NbbClient) -> None:
    with respx.mock:
        respx.get(_NBB_RE).mock(side_effect=nbb_side_effect)
        await ingest_kbos(["0439401387"], fresh_pool, nbb_client, skip_recent_hours=0)

    rows = await fresh_pool.fetch(
        "SELECT field, value, source, confidence FROM observations WHERE kbo_number = $1",
        "0439401387",
    )
    fields = {r["field"] for r in rows}

    # MICRO PDF: revenue (from 9900 Brutomarge proxy) and profit_loss present; employees absent
    assert "revenue_2023" in fields
    assert "profit_2023" in fields
    assert "employees_2023" not in fields  # MICRO model doesn't disclose headcount

    rev = next(r for r in rows if r["field"] == "revenue_2023")
    assert rev["value"]["value"] > 0
    assert rev["value"]["currency"] == "EUR"
    assert rev["source"] == "nbb_authentic"
    assert float(rev["confidence"]) == 1.00

    profit = next(r for r in rows if r["field"] == "profit_2023")
    assert profit["value"]["value"] == -25390


# ---------------------------------------------------------------------------
# Idempotency: second run within 24 h → 0 new observations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_idempotent_within_24h(fresh_pool, nbb_client: NbbClient) -> None:
    with respx.mock:
        respx.get(_NBB_RE).mock(side_effect=nbb_side_effect)
        report1 = await ingest_kbos(["0439401387"], fresh_pool, nbb_client)

    with respx.mock:
        respx.get(_NBB_RE).mock(side_effect=nbb_side_effect)
        report2 = await ingest_kbos(["0439401387"], fresh_pool, nbb_client)

    assert report1.observations_inserted == 3 * _OBS_PER_REF
    assert report2.observations_inserted == 0


@pytest.mark.asyncio
async def test_force_refetch_inserts_again(fresh_pool, nbb_client: NbbClient) -> None:
    with respx.mock:
        respx.get(_NBB_RE).mock(side_effect=nbb_side_effect)
        await ingest_kbos(["0439401387"], fresh_pool, nbb_client)

    with respx.mock:
        respx.get(_NBB_RE).mock(side_effect=nbb_side_effect)
        report2 = await ingest_kbos(["0439401387"], fresh_pool, nbb_client, skip_recent_hours=0)

    assert report2.observations_inserted == 3 * _OBS_PER_REF


# ---------------------------------------------------------------------------
# 404 → counted as kbos_not_found, batch continues
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_not_found_counted_and_batch_continues(fresh_pool, nbb_client: NbbClient) -> None:
    def side_effect_404_first(request: httpx.Request) -> httpx.Response:
        if "0502699332" in str(request.url):
            return httpx.Response(404)
        return nbb_side_effect(request)

    with respx.mock:
        respx.get(_NBB_RE).mock(side_effect=side_effect_404_first)
        report = await ingest_kbos(
            ["0502699332", "0439401387"],
            fresh_pool,
            nbb_client,
            skip_recent_hours=0,
        )

    assert report.kbos_not_found == 1
    assert report.kbos_processed == 1
    assert report.observations_inserted == 3 * _OBS_PER_REF


# ---------------------------------------------------------------------------
# years_back filter — fixed today so test is deterministic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_years_back_filters_old_filings(fresh_pool, nbb_client: NbbClient) -> None:
    # Bellock: exercise years 2021, 2022, 2023
    # With today=2024-05-11 and years_back=2: min_year=2022 → keep 2022 + 2023 only
    with respx.mock:
        respx.get(_NBB_RE).mock(side_effect=nbb_side_effect)
        report = await ingest_kbos(
            ["0439401387"],
            fresh_pool,
            nbb_client,
            skip_recent_hours=0,
            years_back=2,
            _today=date(2024, 5, 11),
        )

    # 2022 and 2023 filings × 2 obs each (MICRO PDF); 2021 filtered out
    assert report.observations_inserted == 2 * _OBS_PER_REF
    assert report.references_total == 2


@pytest.mark.asyncio
async def test_years_back_none_includes_all_filings(fresh_pool, nbb_client: NbbClient) -> None:
    with respx.mock:
        respx.get(_NBB_RE).mock(side_effect=nbb_side_effect)
        report = await ingest_kbos(
            ["0439401387"],
            fresh_pool,
            nbb_client,
            skip_recent_hours=0,
            years_back=None,
        )

    assert report.observations_inserted == 3 * _OBS_PER_REF
    assert report.references_total == 3


# ---------------------------------------------------------------------------
# Invalid KBO checksum skipped
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_kbo_skipped(fresh_pool, nbb_client: NbbClient) -> None:
    with respx.mock:
        respx.get(_NBB_RE).mock(side_effect=nbb_side_effect)
        report = await ingest_kbos(
            ["0000000000", "0439401387"],
            fresh_pool,
            nbb_client,
            skip_recent_hours=0,
        )

    assert report.kbos_processed == 1
    assert report.observations_inserted == 3 * _OBS_PER_REF


# ---------------------------------------------------------------------------
# NbbAuthError on get_references → abort entire batch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_error_aborts_batch(fresh_pool, nbb_client: NbbClient) -> None:
    from scraper.lib.errors import NbbAuthError as _NbbAuthError

    with respx.mock:
        respx.get(_NBB_RE).mock(return_value=httpx.Response(401))
        with pytest.raises(_NbbAuthError):
            await ingest_kbos(["0439401387"], fresh_pool, nbb_client, skip_recent_hours=0)


# ---------------------------------------------------------------------------
# NbbNotFoundError on accounting PDF endpoint → skip reference, continue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_accounting_data_not_found_skips_reference(fresh_pool, nbb_client: NbbClient) -> None:
    def accounting_not_found(request: httpx.Request) -> httpx.Response:
        if "accountingData" in str(request.url):
            return httpx.Response(404)
        return nbb_side_effect(request)

    with respx.mock:
        respx.get(_NBB_RE).mock(side_effect=accounting_not_found)
        report = await ingest_kbos(["0439401387"], fresh_pool, nbb_client, skip_recent_hours=0)

    assert report.kbos_processed == 1
    assert report.references_total == 3
    assert report.observations_inserted == 0  # all PDF fetches 404'd
