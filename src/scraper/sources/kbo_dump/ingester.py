from __future__ import annotations

import contextlib
import json
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from pathlib import Path

import structlog

from scraper.db.models import Observation
from scraper.db.repositories.observations import ObservationsRepo
from scraper.db.repositories.runs import RunsRepo
from scraper.sources.kbo_dump.parser import (
    detect_extract_type,
    iter_activities,
    iter_addresses,
    iter_contacts,
    iter_deleted_enterprises,
    iter_denominations,
    iter_enterprises,
    parse_meta,
)
from scraper.sources.kbo_dump.transformer import (
    activity_to_observation,
    address_to_observation,
    contact_to_observation,
    denomination_to_observation,
    enterprise_to_observations,
)

if TYPE_CHECKING:
    import asyncpg

logger = structlog.get_logger()


@dataclass
class IngestReport:
    extract_type: Literal["Full", "Update"]
    snapshot_date: date
    enterprises_processed: int
    observations_inserted: int
    phones_invalid_skipped: int
    duration_s: float


async def _filter_duplicates(
    observations: list[Observation],
    pool: asyncpg.Pool,
) -> list[Observation]:
    """Remove observations already present in the DB (same kbo/field/value/source).

    No time restriction: observed_at is the historical snapshot date, so a 24h window
    would not catch re-ingestion of older snapshots.
    """
    if not observations:
        return []

    kbo_numbers = list({obs.kbo_number for obs in observations})
    rows = await pool.fetch(
        """
        SELECT kbo_number, field, value
        FROM observations
        WHERE source = 'kbo_dump'
          AND kbo_number = ANY($1::char(10)[])
        """,
        kbo_numbers,
    )

    existing: set[tuple[str, str, str]] = set()
    for row in rows:
        key = (
            str(row["kbo_number"]).strip(),
            row["field"],
            json.dumps(dict(row["value"]), sort_keys=True),
        )
        existing.add(key)

    result: list[Observation] = []
    for obs in observations:
        key = (obs.kbo_number, obs.field, json.dumps(obs.value, sort_keys=True))
        if key not in existing:
            result.append(obs)
            existing.add(key)  # prevent duplicates within the same batch

    return result


def _compute_entity_filter(
    zip_path: Path,
    sector_filter: list[str] | None,
    city_filter: list[str] | None,
) -> set[str]:
    """Return the set of entity numbers that pass sector and/or city filters (AND logic)."""
    sector_matched: set[str] | None = None
    city_matched: set[str] | None = None

    if sector_filter:
        sector_matched = set()
        for act_row in iter_activities(zip_path):
            if any(act_row.nace_code.startswith(p) for p in sector_filter):
                sector_matched.add(act_row.entity_number)

    if city_filter:
        city_lower = [c.lower() for c in city_filter]
        city_matched = set()
        for addr_row in iter_addresses(zip_path):
            nl = (addr_row.municipality_nl or "").lower()
            fr = (addr_row.municipality_fr or "").lower()
            if nl in city_lower or fr in city_lower:
                city_matched.add(addr_row.entity_number)

    if sector_matched is not None and city_matched is not None:
        return sector_matched & city_matched
    if sector_matched is not None:
        return sector_matched
    if city_matched is not None:
        return city_matched
    return set()


async def ingest_zip(
    zip_path: Path,
    pool: asyncpg.Pool,
    *,
    batch_size: int = 5000,
    sector_filter: list[str] | None = None,
    city_filter: list[str] | None = None,
    refresh_view: bool = True,
) -> IngestReport:
    """Stream the ZIP through transformers and bulk-insert via ObservationsRepo.

    Idempotent: running the same ZIP twice within 24 hours produces no duplicate observations.
    """
    t0 = time.monotonic()
    meta = parse_meta(zip_path)
    extract_type = detect_extract_type(zip_path)

    snapshot_date_str = meta.get("SnapshotDate", "")
    try:
        snapshot_date = datetime.strptime(snapshot_date_str, "%d-%m-%Y").date()
    except ValueError:
        snapshot_date = date.today()

    observed_at = datetime(snapshot_date.year, snapshot_date.month, snapshot_date.day, tzinfo=UTC)

    runs_repo = RunsRepo(pool)
    obs_repo = ObservationsRepo(pool)

    run_id = await runs_repo.start_run(source="kbo_dump")
    log = logger.bind(run_id=str(run_id), zip=str(zip_path), extract_type=extract_type)
    log.info("kbo_dump_ingest_started")

    entity_filter: set[str] | None = None
    if sector_filter or city_filter:
        entity_filter = _compute_entity_filter(zip_path, sector_filter, city_filter)
        log.info("entity_filter_computed", count=len(entity_filter))

    total_inserted = 0
    phones_invalid_skipped = 0
    enterprises_processed = 0
    batch: list[Observation] = []

    async def flush() -> None:
        nonlocal total_inserted
        if not batch:
            return
        new_obs = await _filter_duplicates(batch, pool)
        if new_obs:
            ids = await obs_repo.insert_many(new_obs)
            total_inserted += len(ids)
        batch.clear()

    # For Update ZIPs: write a status=deleted observation for each deleted enterprise.
    if extract_type == "Update":
        for kbo_number in iter_deleted_enterprises(zip_path):
            if entity_filter is not None and kbo_number not in entity_filter:
                continue
            with contextlib.suppress(ValueError):
                batch.append(
                    Observation(
                        kbo_number=kbo_number,
                        field="status",
                        value={"value": "deleted", "reason": "open_data_update"},
                        raw_value="enterprise_delete",
                        source="kbo_dump",
                        observed_at=observed_at,
                        confidence=1.00,
                        run_id=run_id,
                    )
                )
            if len(batch) >= batch_size:
                await flush()
        await flush()

    # Enterprises → founding_date + status
    for ent_row in iter_enterprises(zip_path):
        if entity_filter is not None and ent_row.enterprise_number not in entity_filter:
            continue
        enterprises_processed += 1
        batch.extend(enterprise_to_observations(ent_row, run_id, observed_at))
        if len(batch) >= batch_size:
            await flush()
    await flush()

    # Denominations → name
    for denom_row in iter_denominations(zip_path):
        if entity_filter is not None and denom_row.entity_number not in entity_filter:
            continue
        obs = denomination_to_observation(denom_row, run_id, observed_at)
        if obs is not None:
            batch.append(obs)
            if len(batch) >= batch_size:
                await flush()
    await flush()

    # Addresses → address
    for addr_row in iter_addresses(zip_path):
        if entity_filter is not None and addr_row.entity_number not in entity_filter:
            continue
        obs = address_to_observation(addr_row, run_id, observed_at)
        if obs is not None:
            batch.append(obs)
            if len(batch) >= batch_size:
                await flush()
    await flush()

    # Contacts → phone / email / website
    for contact_row in iter_contacts(zip_path):
        if entity_filter is not None and contact_row.entity_number not in entity_filter:
            continue
        obs = contact_to_observation(contact_row, run_id, observed_at)
        if obs is None and contact_row.contact_type == "TEL":
            phones_invalid_skipped += 1
        elif obs is not None:
            batch.append(obs)
            if len(batch) >= batch_size:
                await flush()
    await flush()

    # Activities → nace_code
    for act_row in iter_activities(zip_path):
        if entity_filter is not None and act_row.entity_number not in entity_filter:
            continue
        obs = activity_to_observation(act_row, run_id, observed_at)
        if obs is not None:
            batch.append(obs)
            if len(batch) >= batch_size:
                await flush()
    await flush()

    await runs_repo.finish_run(run_id, jobs_done=total_inserted)

    if refresh_view:
        await pool.execute("SELECT refresh_companies_current()")

    duration = time.monotonic() - t0
    log.info(
        "kbo_dump_ingest_finished",
        total_inserted=total_inserted,
        phones_invalid_skipped=phones_invalid_skipped,
        duration_s=round(duration, 2),
    )

    return IngestReport(
        extract_type=extract_type,
        snapshot_date=snapshot_date,
        enterprises_processed=enterprises_processed,
        observations_inserted=total_inserted,
        phones_invalid_skipped=phones_invalid_skipped,
        duration_s=duration,
    )
