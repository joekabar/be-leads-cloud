from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

import structlog
from stdnum.be import vat as be_vat

from scraper.db.repositories.observations import ObservationsRepo
from scraper.db.repositories.runs import RunsRepo
from scraper.lib.errors import BlockedError, KboNotFoundError
from scraper.lib.http.client import get_polite_client
from scraper.sources.kbopub_html.fetcher import build_detail_url, fetch_detail_page
from scraper.sources.kbopub_html.parser import parse_function_holders
from scraper.sources.kbopub_html.transformer import function_holder_to_observation

if TYPE_CHECKING:
    import asyncpg

    from scraper.db.models import Observation
    from scraper.lib.http.limiter import HostLimiter

logger = structlog.get_logger()


@dataclass
class KbopubReport:
    kbos_processed: int = 0
    kbos_not_found: int = 0
    kbos_invalid: int = 0
    function_holders_total: int = 0
    observations_inserted: int = 0
    duration_s: float = 0.0
    errors: list[str] = field(default_factory=list)


async def _is_fresh(pool: asyncpg.Pool, kbo_number: str, skip_recent_hours: int) -> bool:
    """Return True if a kbopub observation for this KBO exists within skip_recent_hours."""
    if skip_recent_hours <= 0:
        return False
    cutoff = datetime.now(tz=UTC) - timedelta(hours=skip_recent_hours)
    row = await pool.fetchrow(
        """
        SELECT 1 FROM observations
        WHERE kbo_number = $1 AND source = 'kbopub' AND observed_at > $2
        LIMIT 1
        """,
        kbo_number,
        cutoff,
    )
    return row is not None


async def ingest_kbos(
    kbo_numbers: list[str],
    pool: asyncpg.Pool,
    limiter: HostLimiter,
    *,
    batch_size: int = 50,
    lang: Literal["nl", "fr"] = "nl",
    skip_recent_hours: int = 24,
) -> KbopubReport:
    """Fetch kbopub detail pages for each KBO and write function-holder observations.

    Idempotency: KBOs with a kbopub observation within skip_recent_hours are skipped.
    BlockedError aborts the entire batch (WAF block — do not retry).
    KboNotFoundError is counted and skipped; the batch continues.
    """
    t0 = time.monotonic()
    report = KbopubReport()

    runs_repo = RunsRepo(pool)
    obs_repo = ObservationsRepo(pool)

    run_id = await runs_repo.start_run(source="kbopub")
    snapshot_at = datetime.now(tz=UTC)
    log = logger.bind(run_id=str(run_id), source="kbopub")
    log.info("kbopub_ingest_started", total=len(kbo_numbers))

    # Validate KBOs upfront; skip invalids with a warning.
    valid_kbos: list[str] = []
    for raw in kbo_numbers:
        compact = raw.strip()
        if not be_vat.is_valid(compact):
            report.kbos_invalid += 1
            log.warning("invalid_kbo_skipped", kbo=compact)
            continue
        valid_kbos.append(be_vat.compact(compact))

    pending: list[tuple[str, bool]] = []
    for kbo in valid_kbos:
        fresh = await _is_fresh(pool, kbo, skip_recent_hours)
        pending.append((kbo, fresh))

    buffer: list[Observation] = []

    async def flush() -> None:
        if not buffer:
            return
        ids = await obs_repo.insert_many(buffer)
        report.observations_inserted += len(ids)
        buffer.clear()

    async with get_polite_client(limiter) as client:
        for idx, (kbo, is_fresh) in enumerate(pending):
            if is_fresh:
                log.debug("kbo_skipped_fresh", kbo=kbo)
                continue

            try:
                html = await fetch_detail_page(client, kbo, lang=lang)
            except KboNotFoundError:
                report.kbos_not_found += 1
                log.warning("kbo_not_found", kbo=kbo)
                continue
            except BlockedError:
                log.error("kbopub_blocked_aborting_batch", kbo=kbo)
                raise  # caller must abort; do not retry

            rows = parse_function_holders(html)
            report.kbos_processed += 1
            report.function_holders_total += len(rows)

            source_url = build_detail_url(kbo, lang)
            for row in rows:
                buffer.append(
                    function_holder_to_observation(
                        kbo, row, run_id, snapshot_at, source_url=source_url
                    )
                )

            if (idx + 1) % batch_size == 0:
                await flush()

    await flush()
    await pool.execute("SELECT refresh_companies_current()")
    await runs_repo.finish_run(run_id, jobs_done=report.observations_inserted)

    report.duration_s = time.monotonic() - t0
    log.info(
        "kbopub_ingest_finished",
        kbos_processed=report.kbos_processed,
        kbos_not_found=report.kbos_not_found,
        kbos_invalid=report.kbos_invalid,
        observations_inserted=report.observations_inserted,
        duration_s=round(report.duration_s, 2),
    )
    return report
