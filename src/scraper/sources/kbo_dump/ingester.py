from __future__ import annotations

import contextlib
import io
import json as _json
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from pathlib import Path

import structlog

from scraper.db.models import Observation
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


def _pg_text_escape(val: str | None) -> str:
    """Escape a string value for PostgreSQL text-format COPY.

    NULL is represented as \\N; backslash/tab/newline are escaped so Postgres
    unescapes them back to the original characters before type-casting.
    """
    if val is None:
        return r"\N"
    return val.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r")


async def _bulk_insert_observations(
    conn: asyncpg.Connection,
    observations: list[Observation],
) -> int:
    """Bulk insert via COPY text format. Returns count inserted.

    Text-format COPY avoids the binary JSONB encoder requirement while still
    providing ~100x throughput over per-row INSERT (~20k-40k rows/sec on local
    Postgres vs ~500 rows/sec for executemany).
    """
    if not observations:
        return 0

    rows: list[str] = []
    for obs in observations:
        observed_iso = obs.observed_at.isoformat() if obs.observed_at is not None else None
        row = "\t".join(
            [
                _pg_text_escape(obs.kbo_number),
                _pg_text_escape(obs.field),
                _pg_text_escape(_json.dumps(obs.value, ensure_ascii=False)),
                _pg_text_escape(obs.raw_value),
                _pg_text_escape(obs.source),
                _pg_text_escape(obs.source_url),
                _pg_text_escape(observed_iso),
                str(obs.confidence),
                str(obs.run_id),
            ]
        )
        rows.append(row)

    data = ("\n".join(rows) + "\n").encode("utf-8")
    await conn.copy_to_table(
        "observations",
        source=io.BytesIO(data),
        columns=[
            "kbo_number",
            "field",
            "value",
            "raw_value",
            "source",
            "source_url",
            "observed_at",
            "confidence",
            "run_id",
        ],
        format="text",
    )
    return len(rows)


def _build_filter_set(
    zip_path: Path,
    *,
    sector_filter: list[str] | None,
    city_filter: list[str] | None,
) -> set[str] | None:
    """Scan activity.csv + address.csv for matching entity numbers.

    Returns None when no filters are active (caller emits for every entity).
    Sector codes are matched as 2-digit NACE division (e.g. "43" matches 43.xxx).
    City names are matched case-insensitively against NL and FR municipality fields.
    When both filters are active, result is their intersection (AND logic).
    """
    if not sector_filter and not city_filter:
        return None

    keep: set[str] = set()
    if sector_filter:
        normalised = [s.strip() for s in sector_filter]
        for act_row in iter_activities(zip_path):
            # KBO Open Data stores NACE codes without dots (e.g. "62019", not "62.019").
            # Use startswith so a 3-digit prefix "620" matches "62019", "62090", etc.
            if any(act_row.nace_code.startswith(p) for p in normalised):
                keep.add(act_row.entity_number)

    if city_filter:
        normalised_cities = {c.strip().lower() for c in city_filter}
        if sector_filter:
            keep_after_city: set[str] = set()
            for addr_row in iter_addresses(zip_path):
                if addr_row.entity_number not in keep:
                    continue
                muni_nl = (addr_row.municipality_nl or "").lower()
                muni_fr = (addr_row.municipality_fr or "").lower()
                if muni_nl in normalised_cities or muni_fr in normalised_cities:
                    keep_after_city.add(addr_row.entity_number)
            keep = keep_after_city
        else:
            for addr_row in iter_addresses(zip_path):
                muni_nl = (addr_row.municipality_nl or "").lower()
                muni_fr = (addr_row.municipality_fr or "").lower()
                if muni_nl in normalised_cities or muni_fr in normalised_cities:
                    keep.add(addr_row.entity_number)

    return keep


async def ingest_zip(
    zip_path: Path,
    pool: asyncpg.Pool,
    *,
    batch_size: int = 5000,
    sector_filter: list[str] | None = None,
    city_filter: list[str] | None = None,
    month_label: str | None = None,
    max_enterprises: int | None = None,
    truncate_first: bool = False,
    refresh_view: bool = True,
    skip_if_fresh: bool = False,
) -> IngestReport:
    """Stream the ZIP through transformers and bulk-insert via COPY.

    Idempotency note: this function does NOT dedupe at insert time. Re-running the same
    Full ZIP creates duplicate observation rows (~250MB per re-run on real data). The
    matview `companies_current` resolves duplicates via DISTINCT ON, so data integrity
    is preserved; only storage is wasted. Use truncate_first=True for development cycles
    where storage matters more than history preservation.
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

    if skip_if_fresh:
        month_start = datetime(snapshot_date.year, snapshot_date.month, 1, tzinfo=UTC)
        if snapshot_date.month == 12:
            next_month_start = datetime(snapshot_date.year + 1, 1, 1, tzinfo=UTC)
        else:
            next_month_start = datetime(snapshot_date.year, snapshot_date.month + 1, 1, tzinfo=UTC)
        async with pool.acquire() as conn:
            already = await conn.fetchval(
                """
                SELECT 1 FROM observations
                WHERE source = 'kbo_dump'
                  AND observed_at >= $1 AND observed_at < $2
                LIMIT 1
                """,
                month_start,
                next_month_start,
            )
        if already is not None:
            logger.info(
                "kbo_dump_skip_if_fresh",
                snapshot_date=snapshot_date.isoformat(),
                month_label=month_label,
            )
            return IngestReport(
                extract_type=extract_type,
                snapshot_date=snapshot_date,
                enterprises_processed=0,
                observations_inserted=0,
                phones_invalid_skipped=0,
                duration_s=time.monotonic() - t0,
            )

    runs_repo = RunsRepo(pool)
    run_id = await runs_repo.start_run(source="kbo_dump")
    log = logger.bind(
        run_id=str(run_id),
        zip=str(zip_path),
        extract_type=extract_type,
        month_label=month_label,
    )

    if truncate_first:
        async with pool.acquire() as conn:
            result = await conn.execute("DELETE FROM observations WHERE source = 'kbo_dump'")
        deleted_count = int(result.split()[-1])
        log.info("kbo_dump_truncated_before_ingest", deleted=deleted_count)
    else:
        log.warning(
            "kbo_dump_reingest_without_truncate",
            note=(
                "Re-ingesting without truncate_first creates duplicate observations "
                "(~250MB/run). Use truncate_first=True for development cycles."
            ),
        )

    log.info("kbo_dump_ingest_started")

    entity_filter = _build_filter_set(
        zip_path, sector_filter=sector_filter, city_filter=city_filter
    )
    if entity_filter is not None:
        log.info("entity_filter_computed", count=len(entity_filter))

    total_inserted = 0
    phones_invalid_skipped = 0
    enterprises_processed = 0
    batch: list[Observation] = []

    async def flush() -> None:
        nonlocal total_inserted
        if not batch:
            return
        async with pool.acquire() as conn:
            total_inserted += await _bulk_insert_observations(conn, batch)
        batch.clear()

    # Track which enterprise KBOs were actually emitted (respects max_enterprises)
    processed_kbos: set[str] = set()

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
        if max_enterprises is not None and enterprises_processed >= max_enterprises:
            break
        enterprises_processed += 1
        processed_kbos.add(ent_row.enterprise_number)
        batch.extend(enterprise_to_observations(ent_row, run_id, observed_at))
        if len(batch) >= batch_size:
            await flush()
    await flush()

    # Effective filter for subsequent loops: intersection of entity_filter + max_enterprises
    effective_filter: set[str] | None
    if max_enterprises is not None or entity_filter is not None:
        effective_filter = processed_kbos
    else:
        effective_filter = None

    # Denominations → name
    for denom_row in iter_denominations(zip_path):
        if effective_filter is not None and denom_row.entity_number not in effective_filter:
            continue
        obs = denomination_to_observation(denom_row, run_id, observed_at)
        if obs is not None:
            batch.append(obs)
            if len(batch) >= batch_size:
                await flush()
    await flush()

    # Addresses → address
    for addr_row in iter_addresses(zip_path):
        if effective_filter is not None and addr_row.entity_number not in effective_filter:
            continue
        obs = address_to_observation(addr_row, run_id, observed_at)
        if obs is not None:
            batch.append(obs)
            if len(batch) >= batch_size:
                await flush()
    await flush()

    # Contacts → phone / email / website
    for contact_row in iter_contacts(zip_path):
        if effective_filter is not None and contact_row.entity_number not in effective_filter:
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
        if effective_filter is not None and act_row.entity_number not in effective_filter:
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
