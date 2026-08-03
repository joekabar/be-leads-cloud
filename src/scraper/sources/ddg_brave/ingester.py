"""Orchestrate per-(name, city) search cross-validation."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import structlog

from scraper.db.repositories.observations import ObservationsRepo
from scraper.db.repositories.runs import RunsRepo
from scraper.sources.ddg_brave.brave_client import BraveAuthError, BraveQuotaExhaustedError
from scraper.sources.ddg_brave.classifier import classify
from scraper.sources.ddg_brave.ddg_client import DdgRateLimitedError
from scraper.sources.ddg_brave.parser import parse_brave, parse_ddg
from scraper.sources.ddg_brave.transformer import query_to_observations

if TYPE_CHECKING:
    import asyncpg

    from scraper.db.models import Observation
    from scraper.lib.http.client import PoliteClient
    from scraper.sources.ddg_brave.brave_client import BraveClient
    from scraper.sources.ddg_brave.ddg_client import DdgClient

logger = structlog.get_logger()

_BATCH_SIZE = 50


@dataclass
class SearchValidationReport:
    queries_processed: int = 0
    brave_queries: int = 0
    ddg_queries: int = 0
    brave_quota_exhausted: bool = False
    observations_inserted: int = 0
    websites_confirmed: int = 0
    duration_s: float = 0.0
    errors: list[str] = field(default_factory=list)


async def _recent_kbos(pool: asyncpg.Pool, cutoff: datetime) -> set[str]:
    rows = await pool.fetch(
        "SELECT DISTINCT kbo_number FROM observations "
        "WHERE source IN ('brave', 'ddg') AND observed_at > $1",
        cutoff,
    )
    return {r["kbo_number"] for r in rows}


async def validate_companies(
    company_inputs: list[tuple[str, str, str]],  # (kbo_number, company_name, city)
    pool: asyncpg.Pool,
    polite_client: PoliteClient,
    *,
    brave_client: BraveClient | None,
    ddg_client: DdgClient | None,
    skip_recent_hours: int = 168,
    use_ddg_fallback: bool = True,
) -> SearchValidationReport:
    """Cross-validate a batch of companies via search engines.

    For each (kbo, name, city):
    1. Skip if any brave/ddg observation exists within skip_recent_hours.
    2. Try Brave first (if available and quota not exhausted).
    3. Fall back to DDG if Brave is unavailable or returns 0 results.
    4. Emit website + cross_validation observations.
    """
    t0 = time.monotonic()
    report = SearchValidationReport()

    runs_repo = RunsRepo(pool)
    obs_repo = ObservationsRepo(pool)

    run_id = await runs_repo.start_run(source="brave")
    snapshot_at = datetime.now(tz=UTC)
    log = logger.bind(run_id=str(run_id), source="ddg_brave")

    recent: set[str] = set()
    if skip_recent_hours > 0:
        cutoff = snapshot_at - timedelta(hours=skip_recent_hours)
        recent = await _recent_kbos(pool, cutoff)

    log.info(
        "search_validate_started",
        total=len(company_inputs),
        skipped_recent=sum(1 for kbo, _, _ in company_inputs if kbo in recent),
    )

    brave_quota_exhausted = False
    buffer: list[Observation] = []

    try:
        for kbo, name, city in company_inputs:
            if kbo in recent:
                continue

            query = f'"{name}" {city}'
            engine_used: str | None = None

            if brave_client is not None and not brave_quota_exhausted:
                try:
                    raw = await brave_client.search(query)
                    results_sr = parse_brave(raw)
                    classified = [classify(r, name) for r in results_sr]
                    engine_used = "brave"
                    report.brave_queries += 1
                except BraveQuotaExhaustedError:
                    brave_quota_exhausted = True
                    report.brave_quota_exhausted = True
                    log.warning("brave_quota_exhausted_switching_to_ddg")
                except BraveAuthError as exc:
                    brave_quota_exhausted = True
                    report.brave_quota_exhausted = True
                    log.error("brave_auth_error_stopping", error=str(exc))
                    report.errors.append(str(exc))

            if engine_used is None and use_ddg_fallback and ddg_client is not None:
                try:
                    raw_list = await ddg_client.search(query)
                    results_sr = parse_ddg(raw_list)
                    classified = [classify(r, name) for r in results_sr]
                    engine_used = "ddg"
                    report.ddg_queries += 1
                except DdgRateLimitedError as exc:
                    log.warning("ddg_rate_limited_skipping", kbo=kbo, name=name)
                    report.errors.append(str(exc))
                except Exception as exc:
                    # One company's search must never cost the batch its whole
                    # cross-validation pass. Anything unexpected here is recorded and
                    # skipped, matching the rate-limit branch above.
                    log.warning(
                        "ddg_search_failed_skipping",
                        kbo=kbo,
                        name=name,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                    report.errors.append(f"{kbo}: {type(exc).__name__}: {exc}")

            if engine_used is None:
                log.debug("no_engine_available_skipping", kbo=kbo)
                continue

            obs = query_to_observations(
                kbo,
                name,
                query,
                engine_used,  # type: ignore[arg-type]
                classified,
                run_id,
                snapshot_at,
            )
            buffer.extend(obs)
            report.websites_confirmed += sum(1 for o in obs if o.field == "website")
            report.queries_processed += 1

            if len(buffer) >= _BATCH_SIZE:
                ids = await obs_repo.insert_many(buffer)
                report.observations_inserted += len(ids)
                buffer.clear()

        if buffer:
            ids = await obs_repo.insert_many(buffer)
            report.observations_inserted += len(ids)
            buffer.clear()

    finally:
        await pool.execute("SELECT refresh_companies_current()")
        await runs_repo.finish_run(
            run_id,
            jobs_done=report.observations_inserted,
            jobs_failed=len(report.errors),
        )

    report.duration_s = time.monotonic() - t0
    log.info(
        "search_validate_finished",
        queries_processed=report.queries_processed,
        brave_queries=report.brave_queries,
        ddg_queries=report.ddg_queries,
        observations_inserted=report.observations_inserted,
        websites_confirmed=report.websites_confirmed,
        duration_s=round(report.duration_s, 2),
    )
    return report
