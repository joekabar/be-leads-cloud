from __future__ import annotations

import re
import sys
import time

import httpx
import pytest
import respx

from scraper.lib.errors import BlockedError
from scraper.lib.http.limiter import HostConfig, HostLimiter
from scraper.sources.kbopub_html.ingester import ingest_kbos

from .conftest import kbopub_side_effect

pytestmark = pytest.mark.integration

_KBOPUB_URL_RE = re.compile(r".*kbopub\.economie\.fgov\.be.*")


@pytest.fixture()
async def fresh_pool(clean_pool):  # type: ignore[no-untyped-def]
    await clean_pool.execute("SELECT refresh_companies_current()")
    return clean_pool


# ---------------------------------------------------------------------------
# First run: inserts expected observations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_first_run_inserts_observations(fresh_pool, fast_limiter: HostLimiter) -> None:
    with respx.mock:
        respx.get(_KBOPUB_URL_RE).mock(side_effect=kbopub_side_effect)
        report = await ingest_kbos(["0439401387"], fresh_pool, fast_limiter)

    assert report.kbos_processed == 1
    assert report.function_holders_total == 1
    assert report.observations_inserted == 1


@pytest.mark.asyncio
async def test_first_run_observation_field_and_value(fresh_pool, fast_limiter: HostLimiter) -> None:
    with respx.mock:
        respx.get(_KBOPUB_URL_RE).mock(side_effect=kbopub_side_effect)
        await ingest_kbos(["0439401387"], fresh_pool, fast_limiter)

    rows = await fresh_pool.fetch(
        "SELECT field, value, source, confidence FROM observations WHERE kbo_number = $1",
        "0439401387",
    )
    fh_rows = [r for r in rows if r["field"] == "function_holder"]
    assert len(fh_rows) == 1
    v = fh_rows[0]["value"]
    assert v["name"] == "Boonen, Jan"
    assert v["role"] == "bestuurder"
    assert v["role_canonical"] == "director"
    assert v["since"] == "2024-03-27"
    assert fh_rows[0]["source"] == "kbopub"
    assert float(fh_rows[0]["confidence"]) == 0.95


# ---------------------------------------------------------------------------
# Idempotency: second run within 24h produces 0 new observations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_idempotent_within_24h(fresh_pool, fast_limiter: HostLimiter) -> None:
    with respx.mock:
        respx.get(_KBOPUB_URL_RE).mock(side_effect=kbopub_side_effect)
        report1 = await ingest_kbos(["0439401387"], fresh_pool, fast_limiter)

    with respx.mock:
        respx.get(_KBOPUB_URL_RE).mock(side_effect=kbopub_side_effect)
        report2 = await ingest_kbos(["0439401387"], fresh_pool, fast_limiter)

    assert report1.observations_inserted == 1
    assert report2.observations_inserted == 0


# ---------------------------------------------------------------------------
# Force skip_recent_hours=0: always re-fetches and re-inserts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_force_refetch_inserts_again(fresh_pool, fast_limiter: HostLimiter) -> None:
    with respx.mock:
        respx.get(_KBOPUB_URL_RE).mock(side_effect=kbopub_side_effect)
        await ingest_kbos(["0439401387"], fresh_pool, fast_limiter)

    with respx.mock:
        respx.get(_KBOPUB_URL_RE).mock(side_effect=kbopub_side_effect)
        report2 = await ingest_kbos(["0439401387"], fresh_pool, fast_limiter, skip_recent_hours=0)

    assert report2.observations_inserted == 1


# ---------------------------------------------------------------------------
# Multiple KBOs in one batch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multiple_kbos_batch(fresh_pool, fast_limiter: HostLimiter) -> None:
    # Bellock (1 holder) + no_holders (0 holders) + multiple_roles (3 holders).
    # 0234567873 is the valid-checksum KBO that maps to the multiple_roles fixture.
    kbos = ["0439401387", "0123456749", "0234567873"]
    with respx.mock:
        respx.get(_KBOPUB_URL_RE).mock(side_effect=kbopub_side_effect)
        report = await ingest_kbos(kbos, fresh_pool, fast_limiter)

    assert report.kbos_processed == 3
    assert report.function_holders_total == 4  # 1 + 0 + 3
    assert report.observations_inserted == 4


# ---------------------------------------------------------------------------
# HTTP 403 raises BlockedError and aborts the batch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_blocked_error_aborts_batch(fresh_pool, fast_limiter: HostLimiter) -> None:
    with respx.mock:
        respx.get(_KBOPUB_URL_RE).mock(return_value=httpx.Response(403))
        with pytest.raises(BlockedError):
            await ingest_kbos(["0439401387"], fresh_pool, fast_limiter)


# ---------------------------------------------------------------------------
# HTTP 404 counted as kbos_not_found; batch continues
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_not_found_counted_and_skipped(fresh_pool, fast_limiter: HostLimiter) -> None:
    def side_effect_404_then_ok(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "0439401387" in url:
            return httpx.Response(
                200,
                text=(
                    "<html><body>"
                    "<h1>Gegevens van de geregistreerde entiteit</h1>"
                    "<table></table></body></html>"
                ),
            )
        return httpx.Response(404)

    with respx.mock:
        respx.get(_KBOPUB_URL_RE).mock(side_effect=side_effect_404_then_ok)
        # ghost_kbo uses the invalid fixture mapping → 404; bellock → 200 (no functies)
        ghost_kbo = "0502699332"
        report = await ingest_kbos([ghost_kbo, "0439401387"], fresh_pool, fast_limiter)

    assert report.kbos_not_found == 1
    assert report.kbos_processed == 1


# ---------------------------------------------------------------------------
# Invalid KBO checksum is skipped with a warning (not a fatal error)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_kbo_skipped(fresh_pool, fast_limiter: HostLimiter) -> None:
    with respx.mock:
        respx.get(_KBOPUB_URL_RE).mock(side_effect=kbopub_side_effect)
        report = await ingest_kbos(["0000000000", "0439401387"], fresh_pool, fast_limiter)

    assert report.kbos_invalid == 1
    assert report.kbos_processed == 1


# ---------------------------------------------------------------------------
# Rate-limiter timing assertion (slow; skipped on Windows due to asyncio granularity)
# ---------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.skipif(sys.platform == "win32", reason="asyncio sleep granularity on Windows")
@pytest.mark.asyncio
async def test_rate_limiter_timing(fresh_pool) -> None:
    """5 fetches at 0.25 rps should take >= 14 s (4 inter-request gaps x 4 s each).

    Expected: (5 - 1) * 4 s = 16 s; we allow 14 s as a lower bound for CI variance.
    """
    slow_cfg = HostConfig(rps=0.25, concurrency=1, timeout_s=30.0, user_agent_pool_id="api-client")
    slow_limiter = HostLimiter(configs={}, default=slow_cfg)

    # Use valid-checksum KBOs that map to the five golden fixtures via conftest.
    kbos = ["0439401387", "0123456749", "0234567873", "0345678997", "0456789034"]

    with respx.mock:
        respx.get(_KBOPUB_URL_RE).mock(side_effect=kbopub_side_effect)
        t0 = time.monotonic()
        await ingest_kbos(kbos, fresh_pool, slow_limiter)
        elapsed = time.monotonic() - t0

    assert elapsed >= 14.0, f"Rate limiter too fast: {elapsed:.1f}s (expected ≥ 14s)"
