"""Stage a KBO Open Data ZIP into kbo_stage_* tables once per snapshot_date.

Key public functions:
  stage_zip(zip_path, pool, *, force=False, progress=None, run_id=None, executor=None)
      -> StagingReport
  cleanup_old_snapshots(pool, keep_n) -> dict[str, int]
  list_staged_snapshots(pool) -> list[dict]

Performance design (see migration 006):
  - The 5 CSVs are parsed + escaped in a ProcessPoolExecutor (true multi-core; the work
    is CPU-bound pure-Python, so threads/async alone do not parallelise it). Each worker
    streams its escaped rows to a temp TSV file and returns (path, row_count) — this bounds
    worker memory to one row and keeps the cross-process payload to a path string.
  - The main process COPYs each temp file into its (UNLOGGED) staging table.
  - Secondary indexes are dropped before the load and recreated afterwards, so COPY does
    not pay index-maintenance cost per row.
  - No per-row JSON is built; raw_row was dropped in migration 006. Schema drift is detected
    by comparing CSV headers against the pinned expected sets (logged warning).
"""

from __future__ import annotations

import asyncio
import csv
import io
import os
import shutil
import tempfile
import time
from concurrent.futures import Executor, ProcessPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

import structlog

from scraper.sources.kbo_dump.parser import (
    _compact_kbo,
    extract_member,
    iter_activities,
    iter_addresses,
    iter_contacts,
    iter_denominations,
    iter_enterprises,
    parse_meta,
    read_csv_header,
)

if TYPE_CHECKING:
    import asyncpg

    from scraper.pipeline.progress import ProgressReporter

_KINDS = ("enterprise", "address", "denomination", "contact", "activity")

_KIND_TABLE = {
    "enterprise": "kbo_stage_enterprise",
    "address": "kbo_stage_address",
    "denomination": "kbo_stage_denomination",
    "contact": "kbo_stage_contact",
    "activity": "kbo_stage_activity",
}

_KIND_COLUMNS: dict[str, list[str]] = {
    "enterprise": [
        "entity_number",
        "snapshot_date",
        "status",
        "juridical_situation",
        "type_of_enterprise",
        "juridical_form",
        "juridical_form_cac",
        "start_date",
    ],
    "address": [
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
    ],
    "denomination": [
        "entity_number",
        "snapshot_date",
        "language",
        "type_of_denomination",
        "denomination",
    ],
    "contact": ["entity_number", "snapshot_date", "contact_type", "value"],
    "activity": [
        "entity_number",
        "snapshot_date",
        "activity_group",
        "nace_version",
        "nace_code",
        "classification",
    ],
}

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

_DRIFT_SPECS: tuple[tuple[str, frozenset[str]], ...] = (
    ("enterprise.csv", _EXPECTED_ENTERPRISE_COLS),
    ("address.csv", _EXPECTED_ADDRESS_COLS),
    ("denomination.csv", _EXPECTED_DENOMINATION_COLS),
    ("contact.csv", _EXPECTED_CONTACT_COLS),
    ("activity.csv", _EXPECTED_ACTIVITY_COLS),
)

# Secondary indexes per staging table (mirrors migration 004). Dropped before a load and
# recreated after, so COPY does not maintain them per row. The BIGSERIAL pkey is left intact.
_INDEX_DDL: dict[str, list[tuple[str, str]]] = {
    "kbo_stage_enterprise": [
        (
            "idx_kbo_stage_enterprise_snapshot",
            "CREATE INDEX IF NOT EXISTS idx_kbo_stage_enterprise_snapshot "
            "ON kbo_stage_enterprise (snapshot_date)",
        ),
        (
            "idx_kbo_stage_enterprise_entity",
            "CREATE INDEX IF NOT EXISTS idx_kbo_stage_enterprise_entity "
            "ON kbo_stage_enterprise (entity_number, snapshot_date)",
        ),
    ],
    "kbo_stage_address": [
        (
            "idx_kbo_stage_address_snapshot",
            "CREATE INDEX IF NOT EXISTS idx_kbo_stage_address_snapshot "
            "ON kbo_stage_address (snapshot_date)",
        ),
        (
            "idx_kbo_stage_address_entity",
            "CREATE INDEX IF NOT EXISTS idx_kbo_stage_address_entity "
            "ON kbo_stage_address (entity_number, snapshot_date)",
        ),
        (
            "idx_kbo_stage_address_muni_nl",
            "CREATE INDEX IF NOT EXISTS idx_kbo_stage_address_muni_nl "
            "ON kbo_stage_address (snapshot_date, lower(municipality_nl))",
        ),
        (
            "idx_kbo_stage_address_muni_fr",
            "CREATE INDEX IF NOT EXISTS idx_kbo_stage_address_muni_fr "
            "ON kbo_stage_address (snapshot_date, lower(municipality_fr))",
        ),
    ],
    "kbo_stage_denomination": [
        (
            "idx_kbo_stage_denomination_snapshot",
            "CREATE INDEX IF NOT EXISTS idx_kbo_stage_denomination_snapshot "
            "ON kbo_stage_denomination (snapshot_date)",
        ),
        (
            "idx_kbo_stage_denomination_entity",
            "CREATE INDEX IF NOT EXISTS idx_kbo_stage_denomination_entity "
            "ON kbo_stage_denomination (entity_number, snapshot_date)",
        ),
    ],
    "kbo_stage_contact": [
        (
            "idx_kbo_stage_contact_snapshot",
            "CREATE INDEX IF NOT EXISTS idx_kbo_stage_contact_snapshot "
            "ON kbo_stage_contact (snapshot_date)",
        ),
        (
            "idx_kbo_stage_contact_entity",
            "CREATE INDEX IF NOT EXISTS idx_kbo_stage_contact_entity "
            "ON kbo_stage_contact (entity_number, snapshot_date)",
        ),
    ],
    "kbo_stage_activity": [
        (
            "idx_kbo_stage_activity_snapshot",
            "CREATE INDEX IF NOT EXISTS idx_kbo_stage_activity_snapshot "
            "ON kbo_stage_activity (snapshot_date)",
        ),
        (
            "idx_kbo_stage_activity_entity",
            "CREATE INDEX IF NOT EXISTS idx_kbo_stage_activity_entity "
            "ON kbo_stage_activity (entity_number, snapshot_date)",
        ),
        (
            "idx_kbo_stage_activity_nace",
            "CREATE INDEX IF NOT EXISTS idx_kbo_stage_activity_nace "
            "ON kbo_stage_activity (snapshot_date, nace_code text_pattern_ops)",
        ),
    ],
}

_STAGE_TABLES = tuple(_KIND_TABLE[k] for k in _KINDS)


def _pg_text_escape(val: str | None) -> str:
    if val is None:
        return r"\N"
    return val.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r")


def _detect_drift(zip_path: Path) -> None:
    """Compare each CSV's header against its pinned expected columns; warn on new columns.

    This is the replacement for the old (dead) raw_row safety net: if KBO Open Data ever
    adds a column we don't map, the warning tells you to extend the schema or re-stage.
    """
    for csv_name, expected in _DRIFT_SPECS:
        header = read_csv_header(zip_path, csv_name)
        if header is None:
            continue
        unknown = set(header) - expected
        if unknown:
            logger.warning(
                "kbo_schema_drift_detected",
                csv=csv_name,
                new_columns=sorted(unknown),
            )


def _build_payload_file(
    zip_path: Path,
    kind: str,
    snapshot_date_iso: str,
    tmp_dir: str,
) -> tuple[str, int]:
    """Parse + escape one CSV into a temp TSV file. Returns (path, row_count).

    Runs in a worker process (ProcessPoolExecutor) for real loads, or in a thread for tests.
    Memory is O(1) in rows — each row is written and discarded immediately.
    """
    sd = snapshot_date_iso
    fd, tmp_path = tempfile.mkstemp(suffix=f"_{kind}.tsv", dir=tmp_dir)
    count = 0
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
        if kind == "enterprise":
            for ent in iter_enterprises(zip_path):
                fh.write(
                    "\t".join(
                        [
                            _pg_text_escape(ent.enterprise_number),
                            sd,
                            _pg_text_escape(ent.status),
                            _pg_text_escape(ent.juridical_situation),
                            _pg_text_escape(ent.type_of_enterprise),
                            _pg_text_escape(ent.juridical_form),
                            _pg_text_escape(ent.juridical_form_cac),
                            _pg_text_escape(ent.start_date.isoformat() if ent.start_date else None),
                        ]
                    )
                    + "\n"
                )
                count += 1
        elif kind == "address":
            for addr in iter_addresses(zip_path):
                fh.write(
                    "\t".join(
                        [
                            _pg_text_escape(addr.entity_number),
                            sd,
                            _pg_text_escape(addr.type_of_address),
                            _pg_text_escape(addr.zipcode),
                            _pg_text_escape(addr.municipality_nl),
                            _pg_text_escape(addr.municipality_fr),
                            _pg_text_escape(addr.street_nl),
                            _pg_text_escape(addr.street_fr),
                            _pg_text_escape(addr.house_number),
                            _pg_text_escape(addr.box),
                        ]
                    )
                    + "\n"
                )
                count += 1
        elif kind == "denomination":
            for denom in iter_denominations(zip_path):
                fh.write(
                    "\t".join(
                        [
                            _pg_text_escape(denom.entity_number),
                            sd,
                            _pg_text_escape(denom.language),
                            _pg_text_escape(denom.type_of_denomination),
                            _pg_text_escape(denom.denomination),
                        ]
                    )
                    + "\n"
                )
                count += 1
        elif kind == "contact":
            for contact in iter_contacts(zip_path):
                fh.write(
                    "\t".join(
                        [
                            _pg_text_escape(contact.entity_number),
                            sd,
                            _pg_text_escape(contact.contact_type),
                            _pg_text_escape(contact.value),
                        ]
                    )
                    + "\n"
                )
                count += 1
        elif kind == "activity":
            for act in iter_activities(zip_path):
                fh.write(
                    "\t".join(
                        [
                            _pg_text_escape(act.entity_number),
                            sd,
                            _pg_text_escape(act.activity_group),
                            _pg_text_escape(act.nace_version),
                            _pg_text_escape(act.nace_code),
                            _pg_text_escape(act.classification),
                        ]
                    )
                    + "\n"
                )
                count += 1
        else:  # pragma: no cover - guarded by _KINDS
            raise ValueError(f"unknown kind: {kind}")
    return tmp_path, count


async def _copy_file(
    conn: asyncpg.Connection,
    table: str,
    columns: list[str],
    path: str,
) -> None:
    """COPY a temp TSV file into *table* via text-format COPY."""
    await conn.copy_to_table(table, source=Path(path), columns=columns, format="text")


async def _drop_indexes(conn: asyncpg.Connection) -> None:
    for table in _STAGE_TABLES:
        for index_name, _ in _INDEX_DDL[table]:
            await conn.execute(f"DROP INDEX IF EXISTS {index_name}")


async def _create_indexes(conn: asyncpg.Connection) -> None:
    for table in _STAGE_TABLES:
        for _, create_sql in _INDEX_DDL[table]:
            await conn.execute(create_sql)


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


_ACTIVITY_COLS = ("EntityNumber", "ActivityGroup", "NaceVersion", "NaceCode", "Classification")


def _compute_shards(path: str, n: int) -> list[tuple[int, int]]:
    """Split a plain CSV into <= n byte ranges, each starting at a line boundary.

    The header line is excluded (the first shard starts just after it). Used to parse the
    large activity.csv across multiple cores. Returns [(start, end), ...].
    """
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        f.readline()  # consume header
        header_end = f.tell()
        if size <= header_end:
            return []
        if n <= 1:
            return [(header_end, size)]
        span = (size - header_end) // n
        shards: list[tuple[int, int]] = []
        start = header_end
        for i in range(n):
            if start >= size:
                break
            if i == n - 1:
                end = size
            else:
                f.seek(header_end + span * (i + 1))
                f.readline()  # advance to the next line boundary
                end = min(f.tell(), size)
            if end > start:
                shards.append((start, end))
            start = end
    return shards


def _build_activity_shard(
    plain_path: str,
    start: int,
    end: int,
    col_idx: dict[str, int],
    snapshot_date_iso: str,
    tmp_dir: str,
) -> tuple[str, int]:
    """Parse activity rows from byte range [start, end) of a plain CSV → temp TSV file.

    Runs in a worker process. Boundaries are line-aligned by _compute_shards, so the shard
    sees only whole rows. Returns (path, row_count).
    """
    ei = col_idx["EntityNumber"]
    gi = col_idx["ActivityGroup"]
    vi = col_idx["NaceVersion"]
    ci = col_idx["NaceCode"]
    li = col_idx["Classification"]
    max_idx = max(ei, gi, vi, ci, li)
    with open(plain_path, "rb") as f:
        f.seek(start)
        text = f.read(end - start).decode("utf-8")
    fd, tmp_path = tempfile.mkstemp(suffix="_activity.tsv", dir=tmp_dir)
    count = 0
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as out:
        for fields in csv.reader(io.StringIO(text)):
            if len(fields) <= max_idx:
                continue
            out.write(
                "\t".join(
                    [
                        _pg_text_escape(_compact_kbo(fields[ei])),
                        snapshot_date_iso,
                        _pg_text_escape(fields[gi]),
                        _pg_text_escape(fields[vi]),
                        _pg_text_escape(fields[ci]),
                        _pg_text_escape(fields[li]),
                    ]
                )
                + "\n"
            )
            count += 1
    return tmp_path, count


async def stage_zip(
    zip_path: Path,
    pool: asyncpg.Pool,
    *,
    force: bool = False,
    progress: ProgressReporter | None = None,
    run_id: UUID | None = None,
    executor: Executor | None = None,
) -> StagingReport:
    """Stage a KBO Open Data ZIP into the kbo_stage_* tables.

    Idempotent: a snapshot_date already present is skipped unless force=True.
    On force, all 5 tables are DELETE'd for that snapshot_date first.

    The 5 CSVs are parsed in parallel processes (CPU-bound) and COPY'd into UNLOGGED tables
    whose secondary indexes are dropped for the duration of the load. Pass *executor* to run
    parsing in-process (used by tests); production creates its own ProcessPoolExecutor.
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
            for tbl in _STAGE_TABLES:
                await conn.execute(f"DELETE FROM {tbl} WHERE snapshot_date = $1", snapshot_date)  # noqa: S608

    _detect_drift(zip_path)

    if progress and run_id is not None:
        await progress.report("staging", "started", message=f"staging {zip_path.name}")

    log.info("kbo_stage_started")

    loop = asyncio.get_running_loop()
    own_executor = executor is None
    ex: Executor = executor or ProcessPoolExecutor(max_workers=min(os.cpu_count() or 2, 8))
    tmp_dir = tempfile.mkdtemp(prefix="kbo_stage_")
    sd_iso = snapshot_date.isoformat()
    counts: dict[str, int] = {}

    async def _parse_and_copy(kind: str) -> tuple[str, int]:
        path, n = await loop.run_in_executor(
            ex, _build_payload_file, zip_path, kind, sd_iso, tmp_dir
        )
        try:
            if n:
                async with pool.acquire() as conn:
                    await _copy_file(conn, _KIND_TABLE[kind], _KIND_COLUMNS[kind], path)
        finally:
            Path(path).unlink(missing_ok=True)  # noqa: ASYNC240
        if progress and run_id is not None:
            await progress.report("staging", kind, current=n, message=f"staged {kind}")
        logger.info(f"kbo_stage_{kind}_done", rows=n)
        return kind, n

    n_shards = max(1, (os.cpu_count() or 2) - 1)

    async def _stage_activity() -> tuple[str, int]:
        # activity.csv dominates (tens of millions of rows). Decompress it once to a plain
        # seekable file, then parse disjoint byte ranges across the cores left idle once the
        # four smaller tables finish. Falls back to the single-worker path (also the route
        # mock-based unit tests take) when the member can't be extracted.
        plain_path = os.path.join(tmp_dir, "activity_plain.csv")
        ok = await loop.run_in_executor(ex, extract_member, zip_path, "activity.csv", plain_path)
        header = read_csv_header(zip_path, "activity.csv") if ok else None
        if not ok or header is None or not all(c in header for c in _ACTIVITY_COLS):
            return await _parse_and_copy("activity")
        col_idx = {name: i for i, name in enumerate(header)}
        shards = _compute_shards(plain_path, n_shards)

        async def _one_shard(rng: tuple[int, int]) -> int:
            s, e = rng
            shard_path, c = await loop.run_in_executor(
                ex, _build_activity_shard, plain_path, s, e, col_idx, sd_iso, tmp_dir
            )
            try:
                if c:
                    async with pool.acquire() as conn:
                        await _copy_file(
                            conn, "kbo_stage_activity", _KIND_COLUMNS["activity"], shard_path
                        )
            finally:
                Path(shard_path).unlink(missing_ok=True)  # noqa: ASYNC240
            return c

        async with asyncio.TaskGroup() as stg:
            shard_tasks = [stg.create_task(_one_shard(r)) for r in shards]
        total = sum(t.result() for t in shard_tasks)
        Path(plain_path).unlink(missing_ok=True)  # noqa: ASYNC240
        if progress and run_id is not None:
            await progress.report("staging", "activity", current=total, message="staged activity")
        logger.info("kbo_stage_activity_done", rows=total)
        return "activity", total

    try:
        async with pool.acquire() as conn:
            await _drop_indexes(conn)
        try:
            async with asyncio.TaskGroup() as tg:
                tasks = [
                    tg.create_task(_parse_and_copy(kind))
                    for kind in ("enterprise", "address", "denomination", "contact")
                ]
                act_task = tg.create_task(_stage_activity())
            for task in tasks:
                kind, n = task.result()
                counts[kind] = n
            _, counts["activity"] = act_task.result()
        finally:
            async with pool.acquire() as conn:
                await _create_indexes(conn)
    finally:
        if own_executor:
            ex.shutdown(wait=True)
        shutil.rmtree(tmp_dir, ignore_errors=True)

    report.rows_enterprise = counts.get("enterprise", 0)
    report.rows_address = counts.get("address", 0)
    report.rows_denomination = counts.get("denomination", 0)
    report.rows_contact = counts.get("contact", 0)
    report.rows_activity = counts.get("activity", 0)
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
    """Return summary rows: [{snapshot_date, enterprise_count}]."""
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
