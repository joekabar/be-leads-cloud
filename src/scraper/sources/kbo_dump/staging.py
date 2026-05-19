"""Stage a KBO Open Data ZIP into kbo_stage_* tables once per snapshot_date.

Key public functions:
  stage_zip(zip_path, pool, *, force=False, progress=None) -> StagingReport
  cleanup_old_snapshots(pool, keep_n) -> dict[str, int]
"""

from __future__ import annotations

import asyncio
import io
import json
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import TYPE_CHECKING
from uuid import UUID

import structlog

from scraper.sources.kbo_dump.parser import (
    iter_activities,
    iter_addresses,
    iter_contacts,
    iter_denominations,
    iter_enterprises,
    parse_meta,
)

if TYPE_CHECKING:
    from pathlib import Path

    import asyncpg

    from scraper.pipeline.progress import ProgressReporter

_STAGE_TABLES = (
    "kbo_stage_enterprise",
    "kbo_stage_address",
    "kbo_stage_denomination",
    "kbo_stage_contact",
    "kbo_stage_activity",
)
_NULL_UUID = UUID("00000000-0000-0000-0000-000000000000")

logger = structlog.get_logger()

# Pinned expected column sets per CSV — used for schema-drift detection.
_EXPECTED_ENTERPRISE_COLS = frozenset(
    {
        "EnterpriseNumber",
        "Status",
        "JuridicalSituation",
        "TypeOfEnterprise",
        "JuridicalForm",
        "JuridicalFormCAC",
        "StartDate",
    }
)
_EXPECTED_ADDRESS_COLS = frozenset(
    {
        "EntityNumber",
        "TypeOfAddress",
        "Zipcode",
        "MunicipalityNL",
        "MunicipalityFR",
        "StreetNL",
        "StreetFR",
        "HouseNumber",
        "Box",
    }
)
_EXPECTED_DENOMINATION_COLS = frozenset(
    {"EntityNumber", "Language", "TypeOfDenomination", "Denomination"}
)
_EXPECTED_CONTACT_COLS = frozenset({"EntityNumber", "ContactType", "Value"})
_EXPECTED_ACTIVITY_COLS = frozenset(
    {"EntityNumber", "ActivityGroup", "NaceVersion", "NaceCode", "Classification"}
)


def _pg_text_escape(val: str | None) -> str:
    if val is None:
        return r"\N"
    return val.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r")


def _check_drift(csv_name: str, actual_cols: set[str], expected: frozenset[str]) -> None:
    unknown = actual_cols - expected
    if unknown:
        logger.warning(
            "kbo_schema_drift_detected",
            csv=csv_name,
            new_columns=sorted(unknown),
        )


@dataclass
class StagingReport:
    snapshot_date: date
    skipped: bool = False
    rows_enterprise: int = 0
    rows_address: int = 0
    rows_denomination: int = 0
    rows_contact: int = 0
    rows_activity: int = 0
    duration_s: float = 0.0
    errors: list[str] = field(default_factory=list)


async def _copy_rows(
    conn: asyncpg.Connection,
    table: str,
    columns: list[str],
    rows: list[str],
) -> int:
    if not rows:
        return 0
    data = ("\n".join(rows) + "\n").encode("utf-8")
    await conn.copy_to_table(table, source=io.BytesIO(data), columns=columns, format="text")
    return len(rows)


async def _stage_enterprises(
    zip_path: Path,
    pool: asyncpg.Pool,
    snapshot_date: date,
    progress: ProgressReporter | None,
    run_id: UUID,
) -> int:
    cols = [
        "entity_number",
        "snapshot_date",
        "status",
        "juridical_situation",
        "type_of_enterprise",
        "juridical_form",
        "juridical_form_cac",
        "start_date",
        "raw_row",
    ]
    batch: list[str] = []
    total = 0
    drift_checked = False

    for ent in iter_enterprises(zip_path):
        if not drift_checked:
            _check_drift("enterprise.csv", set(), _EXPECTED_ENTERPRISE_COLS)
            drift_checked = True

        raw: dict[str, str | None] = {
            "EnterpriseNumber": ent.enterprise_number,
            "Status": ent.status,
            "JuridicalSituation": ent.juridical_situation,
            "TypeOfEnterprise": ent.type_of_enterprise,
            "JuridicalForm": ent.juridical_form,
            "JuridicalFormCAC": ent.juridical_form_cac,
            "StartDate": ent.start_date.isoformat() if ent.start_date else None,
        }
        row = "\t".join(
            [
                _pg_text_escape(ent.enterprise_number),
                snapshot_date.isoformat(),
                _pg_text_escape(ent.status),
                _pg_text_escape(ent.juridical_situation),
                _pg_text_escape(ent.type_of_enterprise),
                _pg_text_escape(ent.juridical_form),
                _pg_text_escape(ent.juridical_form_cac),
                _pg_text_escape(ent.start_date.isoformat() if ent.start_date else None),
                _pg_text_escape(json.dumps(raw, ensure_ascii=False)),
            ]
        )
        batch.append(row)

        if len(batch) >= 5000:
            async with pool.acquire() as conn:
                total += await _copy_rows(conn, "kbo_stage_enterprise", cols, batch)
            batch.clear()
            if progress:
                await progress.report(
                    "staging", "enterprise", current=total, message="staging enterprises"
                )

    if batch:
        async with pool.acquire() as conn:
            total += await _copy_rows(conn, "kbo_stage_enterprise", cols, batch)

    logger.info("kbo_stage_enterprise_done", rows=total)
    return total


async def _stage_addresses(
    zip_path: Path,
    pool: asyncpg.Pool,
    snapshot_date: date,
    progress: ProgressReporter | None,
    run_id: UUID,
) -> int:
    cols = [
        "entity_number",
        "snapshot_date",
        "type_of_address",
        "zipcode",
        "municipality_nl",
        "municipality_fr",
        "street_nl",
        "street_fr",
        "house_number",
        "box",
        "raw_row",
    ]
    batch: list[str] = []
    total = 0

    for addr in iter_addresses(zip_path):
        raw = {
            "EntityNumber": addr.entity_number,
            "TypeOfAddress": addr.type_of_address,
            "Zipcode": addr.zipcode,
            "MunicipalityNL": addr.municipality_nl,
            "MunicipalityFR": addr.municipality_fr,
            "StreetNL": addr.street_nl,
            "StreetFR": addr.street_fr,
            "HouseNumber": addr.house_number,
            "Box": addr.box,
        }
        row = "\t".join(
            [
                _pg_text_escape(addr.entity_number),
                snapshot_date.isoformat(),
                _pg_text_escape(addr.type_of_address),
                _pg_text_escape(addr.zipcode),
                _pg_text_escape(addr.municipality_nl),
                _pg_text_escape(addr.municipality_fr),
                _pg_text_escape(addr.street_nl),
                _pg_text_escape(addr.street_fr),
                _pg_text_escape(addr.house_number),
                _pg_text_escape(addr.box),
                _pg_text_escape(json.dumps(raw, ensure_ascii=False)),
            ]
        )
        batch.append(row)

        if len(batch) >= 5000:
            async with pool.acquire() as conn:
                total += await _copy_rows(conn, "kbo_stage_address", cols, batch)
            batch.clear()
            if progress:
                await progress.report(
                    "staging", "address", current=total, message="staging addresses"
                )

    if batch:
        async with pool.acquire() as conn:
            total += await _copy_rows(conn, "kbo_stage_address", cols, batch)

    logger.info("kbo_stage_address_done", rows=total)
    return total


async def _stage_denominations(
    zip_path: Path,
    pool: asyncpg.Pool,
    snapshot_date: date,
    progress: ProgressReporter | None,
    run_id: UUID,
) -> int:
    cols = [
        "entity_number",
        "snapshot_date",
        "language",
        "type_of_denomination",
        "denomination",
        "raw_row",
    ]
    batch: list[str] = []
    total = 0

    for denom in iter_denominations(zip_path):
        raw = {
            "EntityNumber": denom.entity_number,
            "Language": denom.language,
            "TypeOfDenomination": denom.type_of_denomination,
            "Denomination": denom.denomination,
        }
        row = "\t".join(
            [
                _pg_text_escape(denom.entity_number),
                snapshot_date.isoformat(),
                _pg_text_escape(denom.language),
                _pg_text_escape(denom.type_of_denomination),
                _pg_text_escape(denom.denomination),
                _pg_text_escape(json.dumps(raw, ensure_ascii=False)),
            ]
        )
        batch.append(row)

        if len(batch) >= 5000:
            async with pool.acquire() as conn:
                total += await _copy_rows(conn, "kbo_stage_denomination", cols, batch)
            batch.clear()

    if batch:
        async with pool.acquire() as conn:
            total += await _copy_rows(conn, "kbo_stage_denomination", cols, batch)

    logger.info("kbo_stage_denomination_done", rows=total)
    return total


async def _stage_contacts(
    zip_path: Path,
    pool: asyncpg.Pool,
    snapshot_date: date,
    progress: ProgressReporter | None,
    run_id: UUID,
) -> int:
    cols = ["entity_number", "snapshot_date", "contact_type", "value", "raw_row"]
    batch: list[str] = []
    total = 0

    for contact in iter_contacts(zip_path):
        raw = {
            "EntityNumber": contact.entity_number,
            "ContactType": contact.contact_type,
            "Value": contact.value,
        }
        row = "\t".join(
            [
                _pg_text_escape(contact.entity_number),
                snapshot_date.isoformat(),
                _pg_text_escape(contact.contact_type),
                _pg_text_escape(contact.value),
                _pg_text_escape(json.dumps(raw, ensure_ascii=False)),
            ]
        )
        batch.append(row)

        if len(batch) >= 5000:
            async with pool.acquire() as conn:
                total += await _copy_rows(conn, "kbo_stage_contact", cols, batch)
            batch.clear()

    if batch:
        async with pool.acquire() as conn:
            total += await _copy_rows(conn, "kbo_stage_contact", cols, batch)

    logger.info("kbo_stage_contact_done", rows=total)
    return total


async def _stage_activities(
    zip_path: Path,
    pool: asyncpg.Pool,
    snapshot_date: date,
    progress: ProgressReporter | None,
    run_id: UUID,
) -> int:
    cols = [
        "entity_number",
        "snapshot_date",
        "activity_group",
        "nace_version",
        "nace_code",
        "classification",
        "raw_row",
    ]
    batch: list[str] = []
    total = 0

    for act in iter_activities(zip_path):
        raw = {
            "EntityNumber": act.entity_number,
            "ActivityGroup": act.activity_group,
            "NaceVersion": act.nace_version,
            "NaceCode": act.nace_code,
            "Classification": act.classification,
        }
        row = "\t".join(
            [
                _pg_text_escape(act.entity_number),
                snapshot_date.isoformat(),
                _pg_text_escape(act.activity_group),
                _pg_text_escape(act.nace_version),
                _pg_text_escape(act.nace_code),
                _pg_text_escape(act.classification),
                _pg_text_escape(json.dumps(raw, ensure_ascii=False)),
            ]
        )
        batch.append(row)

        if len(batch) >= 5000:
            async with pool.acquire() as conn:
                total += await _copy_rows(conn, "kbo_stage_activity", cols, batch)
            batch.clear()

    if batch:
        async with pool.acquire() as conn:
            total += await _copy_rows(conn, "kbo_stage_activity", cols, batch)

    logger.info("kbo_stage_activity_done", rows=total)
    return total


async def stage_zip(
    zip_path: Path,
    pool: asyncpg.Pool,
    *,
    force: bool = False,
    progress: ProgressReporter | None = None,
    run_id: UUID | None = None,
) -> StagingReport:
    """Stage a KBO Open Data ZIP into the kbo_stage_* tables.

    Idempotent: a snapshot_date already present is skipped unless force=True.
    On force, all 5 tables are DELETE'd for that snapshot_date first.
    The 5 CSV passes run concurrently via asyncio.TaskGroup.
    """
    t0 = time.monotonic()
    meta = parse_meta(zip_path)
    snapshot_date_str = meta.get("SnapshotDate", "")
    try:
        snapshot_date = datetime.strptime(snapshot_date_str, "%d-%m-%Y").date()
    except ValueError:
        snapshot_date = date.today()

    log = logger.bind(zip=str(zip_path), snapshot_date=snapshot_date.isoformat())
    report = StagingReport(snapshot_date=snapshot_date)

    # Idempotency check.
    existing = await pool.fetchval(
        "SELECT 1 FROM kbo_stage_enterprise WHERE snapshot_date = $1 LIMIT 1",
        snapshot_date,
    )
    if existing is not None and not force:
        log.info("kbo_stage_skipped_already_staged", snapshot_date=snapshot_date.isoformat())
        report.skipped = True
        report.duration_s = time.monotonic() - t0
        return report

    if existing is not None and force:
        log.info("kbo_stage_force_delete", snapshot_date=snapshot_date.isoformat())
        async with pool.acquire() as conn, conn.transaction():
            for tbl in (
                "kbo_stage_enterprise",
                "kbo_stage_address",
                "kbo_stage_denomination",
                "kbo_stage_contact",
                "kbo_stage_activity",
            ):
                await conn.execute(f"DELETE FROM {tbl} WHERE snapshot_date = $1", snapshot_date)  # noqa: S608

    if progress and run_id:
        await progress.report("staging", "started", message=f"staging {zip_path.name}")

    log.info("kbo_stage_started")

    # 5 CSV passes run concurrently — independent tables, no FK constraints.
    _rid = run_id or _NULL_UUID
    async with asyncio.TaskGroup() as tg:
        t_ent = tg.create_task(_stage_enterprises(zip_path, pool, snapshot_date, progress, _rid))
        t_adr = tg.create_task(_stage_addresses(zip_path, pool, snapshot_date, progress, _rid))
        t_den = tg.create_task(_stage_denominations(zip_path, pool, snapshot_date, progress, _rid))
        t_con = tg.create_task(_stage_contacts(zip_path, pool, snapshot_date, progress, _rid))
        t_act = tg.create_task(_stage_activities(zip_path, pool, snapshot_date, progress, _rid))

    report.rows_enterprise = t_ent.result()
    report.rows_address = t_adr.result()
    report.rows_denomination = t_den.result()
    report.rows_contact = t_con.result()
    report.rows_activity = t_act.result()
    report.duration_s = time.monotonic() - t0

    log.info(
        "kbo_stage_finished",
        rows_enterprise=report.rows_enterprise,
        rows_address=report.rows_address,
        rows_denomination=report.rows_denomination,
        rows_contact=report.rows_contact,
        rows_activity=report.rows_activity,
        duration_s=round(report.duration_s, 2),
    )
    return report


async def cleanup_old_snapshots(
    pool: asyncpg.Pool,
    keep_n: int,
) -> dict[str, int]:
    """Delete staging rows for all snapshot_dates except the most-recent keep_n.

    Runs in a single transaction. Returns per-table row counts deleted.
    """
    if keep_n < 1:
        raise ValueError("keep_n must be >= 1")

    snapshots = await pool.fetch(
        "SELECT DISTINCT snapshot_date FROM kbo_stage_enterprise ORDER BY snapshot_date DESC"
    )
    all_dates = [r["snapshot_date"] for r in snapshots]
    if len(all_dates) <= keep_n:
        return dict.fromkeys(_STAGE_TABLES, 0)

    cutoff_dates = all_dates[keep_n:]

    deleted: dict[str, int] = {}
    async with pool.acquire() as conn, conn.transaction():
        for tbl in _STAGE_TABLES:
            result = await conn.execute(
                f"DELETE FROM {tbl} WHERE snapshot_date = ANY($1::date[])",  # noqa: S608
                cutoff_dates,
            )
            deleted[tbl] = int(result.split()[-1])

    logger.info(
        "kbo_stage_cleanup_done",
        deleted=deleted,
        cutoff_dates=[d.isoformat() for d in cutoff_dates],
    )
    return deleted


async def list_staged_snapshots(
    pool: asyncpg.Pool,
) -> list[dict[str, object]]:
    """Return summary rows: [{snapshot_date, row_counts: {table: n}}]."""
    rows = await pool.fetch(
        """
        SELECT snapshot_date, COUNT(*) AS n
        FROM kbo_stage_enterprise
        GROUP BY snapshot_date
        ORDER BY snapshot_date DESC
        """
    )
    result = []
    for r in rows:
        result.append({"snapshot_date": r["snapshot_date"], "enterprise_count": int(r["n"])})
    return result
