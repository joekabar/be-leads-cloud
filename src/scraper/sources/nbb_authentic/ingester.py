from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING

import structlog
from stdnum.be import vat as be_vat

from scraper.db.repositories.observations import ObservationsRepo
from scraper.db.repositories.runs import RunsRepo
from scraper.lib.errors import NbbAuthError, NbbNotFoundError
from scraper.sources.nbb_authentic.parser import parse_accounting_pdf
from scraper.sources.nbb_authentic.transformer import filing_to_observations

if TYPE_CHECKING:
    import asyncpg

    from scraper.db.models import Observation
    from scraper.sources.nbb_authentic.client import NbbClient

logger = structlog.get_logger()


@dataclass
class NbbReport:
    kbos_processed: int = 0
    kbos_not_found: int = 0
    references_total: int = 0
    observations_inserted: int = 0
    duration_s: float = 0.0


async def _is_fresh(pool: asyncpg.Pool, kbo_number: str, skip_recent_hours: int) -> bool:
    if skip_recent_hours <= 0:
        return False
    cutoff = datetime.now(tz=UTC) - timedelta(hours=skip_recent_hours)
    row = await pool.fetchrow(
        """
        SELECT 1 FROM observations
        WHERE kbo_number = $1 AND source = 'nbb_authentic' AND observed_at > $2
        LIMIT 1
        """,
        kbo_number,
        cutoff,
    )
    return row is not None


async def ingest_kbos(
    kbo_numbers: list[str],
    pool: asyncpg.Pool,
    nbb_client: NbbClient,
    *,
    skip_recent_hours: int = 24,
    years_back: int | None = None,
    _today: date | None = None,
) -> NbbReport:
    """Fetch NBB CBSO financial data for each KBO and write financial observations.

    Idempotency: KBOs with an nbb_authentic observation within skip_recent_hours are skipped.
    NbbAuthError aborts the entire batch — the key is broken, stop immediately.
    NbbNotFoundError is counted and skipped; the batch continues.
    """
    t0 = time.monotonic()
    report = NbbReport()
    today = _today if _today is not None else date.today()

    runs_repo = RunsRepo(pool)
    obs_repo = ObservationsRepo(pool)

    run_id = await runs_repo.start_run(source="nbb_authentic")
    snapshot_at = datetime.now(tz=UTC)
    log = logger.bind(run_id=str(run_id), source="nbb_authentic")
    log.info("nbb_ingest_started", total=len(kbo_numbers))

    valid_kbos: list[str] = []
    for raw in kbo_numbers:
        compact = raw.strip()
        if not be_vat.is_valid(compact):
            log.warning("invalid_kbo_skipped", kbo=compact)
            continue
        valid_kbos.append(be_vat.compact(compact))

    buffer: list[Observation] = []

    async def flush() -> None:
        if not buffer:
            return
        ids = await obs_repo.insert_many(buffer)
        report.observations_inserted += len(ids)
        buffer.clear()

    for kbo in valid_kbos:
        if await _is_fresh(pool, kbo, skip_recent_hours):
            log.debug("kbo_skipped_fresh", kbo=kbo)
            continue

        try:
            references = await nbb_client.get_references(kbo)
        except NbbAuthError:
            log.error("nbb_auth_error_aborting", kbo=kbo)
            raise
        except NbbNotFoundError:
            report.kbos_not_found += 1
            log.warning("kbo_not_found_in_nbb", kbo=kbo)
            continue

        if years_back is not None:
            min_year = today.year - years_back
            references = [r for r in references if r.exercise_end.year >= min_year]

        report.references_total += len(references)

        for ref in references:
            if not ref.accounting_data_url:
                log.debug("no_accounting_data_url", kbo=kbo, ref=ref.reference_number)
                continue
            try:
                pdf_bytes = await nbb_client.get_accounting_pdf(ref.accounting_data_url)
            except NbbNotFoundError:
                log.warning("accounting_pdf_not_found", kbo=kbo, ref=ref.reference_number)
                continue
            filing = parse_accounting_pdf(ref, pdf_bytes)
            obs = filing_to_observations(kbo, filing, run_id, snapshot_at)
            buffer.extend(obs)

        report.kbos_processed += 1

        if len(buffer) >= 100:
            await flush()

    await flush()
    await pool.execute("SELECT refresh_companies_current()")
    await runs_repo.finish_run(run_id, jobs_done=report.observations_inserted)

    report.duration_s = time.monotonic() - t0
    log.info(
        "nbb_ingest_finished",
        kbos_processed=report.kbos_processed,
        kbos_not_found=report.kbos_not_found,
        references_total=report.references_total,
        observations_inserted=report.observations_inserted,
        duration_s=round(report.duration_s, 2),
    )
    return report
