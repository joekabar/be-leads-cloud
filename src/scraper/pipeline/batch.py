"""Epoch-aware batch orchestrator: stage-once KBO + single consolidation/scoring pass.

Phases:
  A  — emit observations from kbo_stage_* tables (SQL filter + Python transformers + COPY)
  B  — per-sector goudengids (sequential; WAF-bound)
  C1 — kbopub/nbb/website enrichment (concurrent with Phase B)
  C2 — ddg_brave search validation (after Phase B)
  D  — single consolidation pass
  E  — single matview refresh
  F  — single prospect scoring pass
"""

from __future__ import annotations

import asyncio
import io
import json
import time
import tomllib
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import structlog

from scraper.db.repositories.runs import RunsRepo
from scraper.pipeline.city_map import get_postal_codes
from scraper.pipeline.consolidate import consolidate
from scraper.pipeline.orchestrator import _SECTOR_NACE_PREFIXES
from scraper.pipeline.progress import ProgressReporter
from scraper.scoring.prospect import refresh_prospect_scores
from scraper.sources.kbo_dump.transformer import (
    activity_to_observation,
    address_to_observation,
    contact_to_observation,
    denomination_to_observation,
    enterprise_to_observations,
)

if TYPE_CHECKING:
    from uuid import UUID

    import asyncpg

    from scraper.lib.http.client import PoliteClient

logger = structlog.get_logger()

_SECTORS_TOML = (
    Path(__file__).parents[3]
    / ".claude"
    / "skills"
    / "goudengids-listing"
    / "references"
    / "sectors.toml"
)


@dataclass(frozen=True, slots=True)
class BatchConfig:
    city: str
    sectors: list[str]
    snapshot_date: date | None = None
    lang: Literal["nl", "fr"] = "nl"
    max_pages: int = 25
    nbb_subscription_key: str | None = None
    brave_subscription_key: str | None = None
    database_url: str | None = None
    do_kbo_dump: bool = True
    do_goudengids: bool = True
    do_kbopub: bool = True
    do_nbb: bool = True
    do_website: bool = True
    do_search: bool = True


@dataclass
class BatchReport:
    city: str
    sectors: list[str]
    snapshot_date: date | None
    started_at: datetime
    ended_at: datetime | None = None
    sources_run: list[str] = field(default_factory=list)
    sources_failed: dict[str, str] = field(default_factory=dict)
    phase_a_kbos: int = 0
    goudengids_per_sector: dict[str, int] = field(default_factory=dict)
    enrichment_observations: dict[str, int] = field(default_factory=dict)
    placeholders_resolved: int = 0
    companies_in_view: int = 0
    prospect_scores_computed: int = 0
    duration_s: float = 0.0


def _load_goudengids_entries() -> dict[str, dict[str, object]]:
    """Return {section_key: {nl_slug, fr_slug, goudengids_sector_not_indexed, ...}}."""
    with _SECTORS_TOML.open("rb") as fh:
        data = tomllib.load(fh)
    return {k: v for k, v in data.items() if isinstance(v, dict)}


def _resolve_goudengids_slug(sector_slug: str, lang: str) -> str | None:
    """Return the goudengids slug for a sector, or None if not indexed."""
    entries = _load_goudengids_entries()

    # Look up by nl_slug or section key.
    entry = entries.get(sector_slug)
    if entry is None:
        for e in entries.values():
            if e.get("nl_slug") == sector_slug or e.get("fr_slug") == sector_slug:
                entry = e
                break

    if entry is None:
        return None
    if entry.get("goudengids_sector_not_indexed"):
        return None

    slug = str(entry.get("fr_slug", "")) if lang == "fr" else str(entry.get("nl_slug", ""))
    return slug if slug else None


async def resolve_snapshot_date(pool: asyncpg.Pool) -> date | None:
    """Return the most-recent snapshot_date in kbo_stage_enterprise, or None if empty."""
    row = await pool.fetchrow("SELECT MAX(snapshot_date) AS d FROM kbo_stage_enterprise")
    return row["d"] if row else None


async def get_entity_filter(
    pool: asyncpg.Pool,
    snapshot_date: date,
    city: str,
    nace_prefixes: list[str],
) -> list[str]:
    """Return entity_numbers matching city + NACE filter from staging tables.

    Uses postal-code lookup when the city slug is in city_map.toml; falls back
    to municipality name matching for cities not in the map.
    """
    postal_codes = get_postal_codes(city)
    if postal_codes:
        city_rows = await pool.fetch(
            """
            SELECT DISTINCT entity_number
            FROM kbo_stage_address
            WHERE snapshot_date = $1
              AND zipcode = ANY($2::text[])
            """,
            snapshot_date,
            postal_codes,
        )
    else:
        city_rows = await pool.fetch(
            """
            SELECT DISTINCT entity_number
            FROM kbo_stage_address
            WHERE snapshot_date = $1
              AND (lower(municipality_nl) = lower($2) OR lower(municipality_fr) = lower($2))
            """,
            snapshot_date,
            city,
        )
    city_entities = {r["entity_number"] for r in city_rows}

    if not city_entities:
        return []

    if nace_prefixes:
        like_patterns = [f"{p}%" for p in nace_prefixes]
        nace_rows = await pool.fetch(
            """
            SELECT DISTINCT entity_number
            FROM kbo_stage_activity
            WHERE snapshot_date = $1
              AND nace_code LIKE ANY($2::text[])
            """,
            snapshot_date,
            like_patterns,
        )
        nace_entities = {r["entity_number"] for r in nace_rows}
        return list(city_entities & nace_entities)

    return list(city_entities)


def _pg_text_escape(val: str | None) -> str:
    if val is None:
        return r"\N"
    return val.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r")


async def emit_phase_a(
    pool: asyncpg.Pool,
    snapshot_date: date,
    entity_numbers: list[str],
    run_id: UUID,
    observed_at: datetime,
    progress: ProgressReporter | None = None,
) -> int:
    """Fetch staging rows for entity_numbers, transform, bulk-COPY into observations."""
    from scraper.sources.kbo_dump.parser import (
        ActivityRow,
        AddressRow,
        ContactRow,
        DenominationRow,
        EnterpriseRow,
    )

    obs_cols = [
        "kbo_number",
        "field",
        "value",
        "raw_value",
        "source",
        "source_url",
        "observed_at",
        "confidence",
        "run_id",
    ]

    total_inserted = 0
    batch: list[str] = []

    async def _flush() -> None:
        nonlocal total_inserted
        if not batch:
            return
        data = ("\n".join(batch) + "\n").encode("utf-8")
        async with pool.acquire() as conn:
            await conn.copy_to_table(
                "observations",
                source=io.BytesIO(data),
                columns=obs_cols,
                format="text",
            )
        total_inserted += len(batch)
        batch.clear()

    def _obs_row(kbo: str, fld: str, value: dict[str, object], raw: str | None, conf: float) -> str:
        return "\t".join(
            [
                _pg_text_escape(kbo),
                _pg_text_escape(fld),
                _pg_text_escape(json.dumps(value, ensure_ascii=False)),
                _pg_text_escape(raw),
                "kbo_dump",
                r"\N",
                observed_at.isoformat(),
                str(conf),
                str(run_id),
            ]
        )

    # --- Enterprise rows ---
    if progress:
        await progress.report("phase_a", "enterprise", message="emitting enterprise observations")
    ent_rows = await pool.fetch(
        """
        SELECT entity_number, status, juridical_situation, type_of_enterprise,
               juridical_form, juridical_form_cac, start_date
        FROM kbo_stage_enterprise
        WHERE snapshot_date = $1 AND entity_number = ANY($2::text[])
        """,
        snapshot_date,
        entity_numbers,
    )
    for r in ent_rows:
        ent = EnterpriseRow(
            enterprise_number=r["entity_number"],
            status=r["status"] or "",
            juridical_situation=r["juridical_situation"] or "",
            type_of_enterprise=r["type_of_enterprise"] or "",
            juridical_form=r["juridical_form"],
            juridical_form_cac=r["juridical_form_cac"],
            start_date=r["start_date"],
        )
        for obs in enterprise_to_observations(ent, run_id, observed_at):
            batch.append(
                _obs_row(obs.kbo_number, obs.field, obs.value, obs.raw_value, float(obs.confidence))
            )
            if len(batch) >= 5000:
                await _flush()

    # --- Address rows ---
    if progress:
        await progress.report(
            "phase_a", "address", current=total_inserted, message="emitting address observations"
        )
    addr_rows = await pool.fetch(
        """
        SELECT entity_number, type_of_address, zipcode,
               municipality_nl, municipality_fr, street_nl, street_fr, house_number, box
        FROM kbo_stage_address
        WHERE snapshot_date = $1 AND entity_number = ANY($2::text[])
        """,
        snapshot_date,
        entity_numbers,
    )
    for r in addr_rows:
        addr = AddressRow(
            entity_number=r["entity_number"],
            type_of_address=r["type_of_address"] or "",
            zipcode=r["zipcode"],
            municipality_nl=r["municipality_nl"],
            municipality_fr=r["municipality_fr"],
            street_nl=r["street_nl"],
            street_fr=r["street_fr"],
            house_number=r["house_number"],
            box=r["box"],
        )
        addr_obs = address_to_observation(addr, run_id, observed_at)
        if addr_obs:
            batch.append(
                _obs_row(
                    addr_obs.kbo_number,
                    addr_obs.field,
                    addr_obs.value,
                    addr_obs.raw_value,
                    float(addr_obs.confidence),
                )
            )
            if len(batch) >= 5000:
                await _flush()

    # --- Denomination rows ---
    if progress:
        await progress.report(
            "phase_a", "denomination", current=total_inserted, message="emitting name observations"
        )
    denom_rows = await pool.fetch(
        """
        SELECT entity_number, language, type_of_denomination, denomination
        FROM kbo_stage_denomination
        WHERE snapshot_date = $1 AND entity_number = ANY($2::text[])
        """,
        snapshot_date,
        entity_numbers,
    )
    for r in denom_rows:
        denom = DenominationRow(
            entity_number=r["entity_number"],
            language=r["language"] or "",
            type_of_denomination=r["type_of_denomination"] or "",
            denomination=r["denomination"] or "",
        )
        denom_obs = denomination_to_observation(denom, run_id, observed_at)
        if denom_obs:
            batch.append(
                _obs_row(
                    denom_obs.kbo_number,
                    denom_obs.field,
                    denom_obs.value,
                    denom_obs.raw_value,
                    float(denom_obs.confidence),
                )
            )
            if len(batch) >= 5000:
                await _flush()

    # --- Contact rows ---
    if progress:
        await progress.report(
            "phase_a", "contact", current=total_inserted, message="emitting contact observations"
        )
    contact_rows = await pool.fetch(
        """
        SELECT entity_number, contact_type, value
        FROM kbo_stage_contact
        WHERE snapshot_date = $1 AND entity_number = ANY($2::text[])
        """,
        snapshot_date,
        entity_numbers,
    )
    for r in contact_rows:
        contact = ContactRow(
            entity_number=r["entity_number"],
            contact_type=r["contact_type"] or "",
            value=r["value"] or "",
        )
        contact_obs = contact_to_observation(contact, run_id, observed_at)
        if contact_obs:
            batch.append(
                _obs_row(
                    contact_obs.kbo_number,
                    contact_obs.field,
                    contact_obs.value,
                    contact_obs.raw_value,
                    float(contact_obs.confidence),
                )
            )
            if len(batch) >= 5000:
                await _flush()

    # --- Activity rows ---
    if progress:
        await progress.report(
            "phase_a", "activity", current=total_inserted, message="emitting NACE observations"
        )
    act_rows = await pool.fetch(
        """
        SELECT entity_number, activity_group, nace_version, nace_code, classification
        FROM kbo_stage_activity
        WHERE snapshot_date = $1 AND entity_number = ANY($2::text[])
        """,
        snapshot_date,
        entity_numbers,
    )
    for r in act_rows:
        act = ActivityRow(
            entity_number=r["entity_number"],
            activity_group=r["activity_group"] or "",
            nace_version=r["nace_version"] or "",
            nace_code=r["nace_code"] or "",
            classification=r["classification"] or "",
        )
        act_obs = activity_to_observation(act, run_id, observed_at)
        if act_obs:
            batch.append(
                _obs_row(
                    act_obs.kbo_number,
                    act_obs.field,
                    act_obs.value,
                    act_obs.raw_value,
                    float(act_obs.confidence),
                )
            )
            if len(batch) >= 5000:
                await _flush()

    await _flush()
    return total_inserted


async def _run_goudengids_sector(
    sector_slug: str,
    city: str,
    lang: Literal["nl", "fr"],
    max_pages: int,
    pool: asyncpg.Pool,
    polite_client: PoliteClient,
    log: structlog.BoundLogger,
) -> int:
    """Run goudengids for one sector. Returns observations inserted (0 on skip/failure)."""
    goud_slug = _resolve_goudengids_slug(sector_slug, lang)
    if goud_slug is None:
        log.info("goudengids_sector_not_indexed", sector_slug=sector_slug)
        return 0

    from scraper.sources.goudengids.fetcher import BrowserListingFetcher
    from scraper.sources.goudengids.ingester import ingest_sector_city

    domain = "pagesdor.be" if lang == "fr" else "goudengids.be"
    fetcher = BrowserListingFetcher(polite_client.limiter, domain=domain)
    try:
        report = await ingest_sector_city(
            goud_slug,
            city,
            pool,
            fetcher,
            max_pages=max_pages,
            lang=lang,
            skip_recent_hours=0,
        )
        log.info(
            "goudengids_sector_done",
            sector=sector_slug,
            pages=report.pages_scanned,
            cards=report.cards_found,
            obs=report.observations_inserted,
        )
        return report.observations_inserted
    except ValueError as exc:
        log.info("goudengids_no_results_for_sector", sector_slug=sector_slug, reason=str(exc))
        return 0
    except Exception as exc:
        log.error("goudengids_sector_failed", sector_slug=sector_slug, error=str(exc))
        return 0


async def run_batch(
    config: BatchConfig,
    pool: asyncpg.Pool,
    polite_client: PoliteClient,
) -> BatchReport:
    """Run an epoch-aware batch for city x sectors.

    Phase A  reads from kbo_stage_* (no ZIP parsing).
    Phase B/C1 overlap: goudengids loop runs concurrently with kbopub/nbb/website.
    Phase C2 runs ddg_brave after Phase B completes (needs all placeholders).
    Phase D/E/F: consolidate → matview → scoring, each once for the whole batch.
    """
    t0 = time.monotonic()
    started_at = datetime.now(tz=UTC)
    report = BatchReport(
        city=config.city,
        sectors=list(config.sectors),
        snapshot_date=config.snapshot_date,
        started_at=started_at,
    )
    runs_repo = RunsRepo(pool)
    log = logger.bind(city=config.city, sectors=len(config.sectors))
    log.info("batch_started", sectors=config.sectors)

    # ── Resolve snapshot_date ───────────────────────────────────────────────────
    snapshot_date = config.snapshot_date
    if snapshot_date is None:
        snapshot_date = await resolve_snapshot_date(pool)
        if snapshot_date is None:
            raise RuntimeError("No staged KBO data found. Run: be-leads-kbo-stage <zip_path>")
    report.snapshot_date = snapshot_date
    observed_at = datetime(snapshot_date.year, snapshot_date.month, snapshot_date.day, tzinfo=UTC)

    # ── Phase A — emit from staging tables ─────────────────────────────────────
    log.info("phase_a_started", snapshot_date=snapshot_date.isoformat())
    phase_a_run_id = await runs_repo.start_run(
        source="kbo_dump",
        city_slug=config.city,
        notes=f"batch phase_a snapshot={snapshot_date}",
    )
    progress = ProgressReporter(pool=pool, run_id=phase_a_run_id)

    # Delete previous kbo_dump observations for this snapshot to prevent duplicates.
    snapshot_start = datetime(
        snapshot_date.year, snapshot_date.month, snapshot_date.day, tzinfo=UTC
    )
    if snapshot_date.month == 12:
        snapshot_end = datetime(snapshot_date.year + 1, 1, 1, tzinfo=UTC)
    else:
        snapshot_end = datetime(snapshot_date.year, snapshot_date.month + 1, 1, tzinfo=UTC)

    deleted = await pool.execute(
        "DELETE FROM observations"
        " WHERE source = 'kbo_dump' AND observed_at >= $1 AND observed_at < $2",
        snapshot_start,
        snapshot_end,
    )
    log.info("phase_a_old_obs_deleted", result=deleted)

    # Build NACE union across all requested sectors.
    nace_union: list[str] = []
    for slug in config.sectors:
        nace_union.extend(_SECTOR_NACE_PREFIXES.get(slug, []))

    await progress.report("phase_a", "filter", message=f"computing entity filter for {config.city}")
    entity_numbers = await get_entity_filter(pool, snapshot_date, config.city, nace_union)
    log.info("phase_a_entity_filter", entities=len(entity_numbers), nace_prefixes=len(nace_union))

    if entity_numbers and config.do_kbo_dump:
        phase_a_obs = await emit_phase_a(
            pool, snapshot_date, entity_numbers, phase_a_run_id, observed_at, progress
        )
        report.phase_a_kbos = len(entity_numbers)
        report.sources_run.append("kbo_dump")
        await runs_repo.finish_run(phase_a_run_id, jobs_done=phase_a_obs)
        log.info("phase_a_finished", entities=len(entity_numbers), observations=phase_a_obs)
    else:
        await runs_repo.finish_run(phase_a_run_id, jobs_done=0)
        log.info("phase_a_skipped", reason="no_entities" if not entity_numbers else "disabled")

    # Build real KBOs from Phase A for enrichment (C1).
    phase_a_real_kbos: list[str] = []
    if config.do_kbopub or config.do_nbb or config.do_website:
        rows = await pool.fetch(
            "SELECT DISTINCT kbo_number FROM observations"
            " WHERE run_id = $1 AND kbo_number NOT LIKE '9%%'",
            phase_a_run_id,
        )
        phase_a_real_kbos = [str(r["kbo_number"]).strip() for r in rows]
        log.info("phase_a_real_kbos", count=len(phase_a_real_kbos))

    # ── Phase B/C1 overlap ─────────────────────────────────────────────────────
    # Phase B: goudengids loop (sequential per sector, WAF-bound)
    # Phase C1: kbopub + nbb + website (concurrent, starts immediately after A)
    # Both run in one outer TaskGroup so they overlap.
    log.info("phase_bc1_started")
    phase_b_run_ids: list[UUID] = []
    phase_b_lock = asyncio.Lock()

    async def _phase_b() -> None:
        if not config.do_goudengids:
            return
        for i, sector_slug in enumerate(config.sectors):
            await progress.report(
                "phase_b",
                "goudengids",
                current=i,
                total=len(config.sectors),
                message=f"goudengids: {sector_slug}",
            )
            obs_count = await _run_goudengids_sector(
                sector_slug,
                config.city,
                config.lang,
                config.max_pages,
                pool,
                polite_client,
                log,
            )
            report.goudengids_per_sector[sector_slug] = obs_count
            # Collect run_ids for Phase C2 scope.
            run_ids_now = await pool.fetch(
                "SELECT run_id FROM run_log WHERE source = 'goudengids' AND city_slug = $1 "
                "AND started_at >= $2",
                config.city,
                started_at,
            )
            async with phase_b_lock:
                for r in run_ids_now:
                    if r["run_id"] not in phase_b_run_ids:
                        phase_b_run_ids.append(r["run_id"])

    async def _phase_c1_kbopub() -> None:
        if not config.do_kbopub or not phase_a_real_kbos:
            log.info(
                "kbopub_skipped", reason="no_real_kbos" if not phase_a_real_kbos else "disabled"
            )
            return
        try:
            from scraper.sources.kbopub_html.ingester import ingest_kbos as kbopub_ingest

            await progress.report("phase_c1", "kbopub", message="enriching with kbopub")
            r = await kbopub_ingest(
                phase_a_real_kbos,
                pool,
                polite_client.limiter,
                lang=config.lang,
                skip_recent_hours=24,
            )
            report.enrichment_observations["kbopub_html"] = r.observations_inserted
            report.sources_run.append("kbopub_html")
            log.info("kbopub_done", obs=r.observations_inserted, kbos=r.kbos_processed)
        except Exception as exc:
            report.sources_failed["kbopub_html"] = str(exc)
            log.error("kbopub_failed", error=str(exc))

    async def _phase_c1_nbb() -> None:
        if not config.do_nbb or not config.nbb_subscription_key or not phase_a_real_kbos:
            log.info(
                "nbb_skipped",
                reason="no_key" if not config.nbb_subscription_key else "no_real_kbos",
            )
            return
        try:
            from scraper.sources.nbb_authentic.client import NbbClient
            from scraper.sources.nbb_authentic.ingester import ingest_kbos as nbb_ingest

            await progress.report("phase_c1", "nbb", message="enriching with NBB financials")
            nbb_client = NbbClient(polite_client, config.nbb_subscription_key)
            r = await nbb_ingest(phase_a_real_kbos, pool, nbb_client, skip_recent_hours=24)
            report.enrichment_observations["nbb_authentic"] = r.observations_inserted
            report.sources_run.append("nbb_authentic")
            log.info("nbb_done", obs=r.observations_inserted)
        except Exception as exc:
            report.sources_failed["nbb_authentic"] = str(exc)
            log.error("nbb_failed", error=str(exc))

    async def _phase_c1_website() -> None:
        if not config.do_website:
            return
        try:
            from scraper.sources.website.ingester import ingest_kbos as website_ingest

            pairs_rows = await pool.fetch(
                "SELECT DISTINCT kbo_number, value->>'url' AS url FROM observations "
                "WHERE field = 'website' AND run_id = $1",
                phase_a_run_id,
            )
            pairs = [(str(r["kbo_number"]).strip(), r["url"]) for r in pairs_rows if r["url"]]
            if not pairs:
                log.info("website_skipped", reason="no_pairs")
                return
            await progress.report("phase_c1", "website", message="enriching company websites")
            r = await website_ingest(pairs, pool, polite_client, skip_recent_hours=24)
            report.enrichment_observations["website"] = r.observations_inserted
            report.sources_run.append("website")
            log.info("website_done", obs=r.observations_inserted)
        except Exception as exc:
            report.sources_failed["website"] = str(exc)
            log.error("website_failed", error=str(exc))

    # Run Phase B (goudengids) and Phase C1 (kbopub/nbb/website) concurrently.
    async with asyncio.TaskGroup() as tg:
        tg.create_task(_phase_b())
        tg.create_task(_phase_c1_kbopub())
        tg.create_task(_phase_c1_nbb())
        tg.create_task(_phase_c1_website())

    log.info("phase_bc1_finished")

    # ── Phase C2 — ddg_brave (after Phase B, needs all placeholders) ───────────
    if config.do_search:
        try:
            from scraper.sources.ddg_brave.brave_client import BraveClient
            from scraper.sources.ddg_brave.ddg_client import DdgClient
            from scraper.sources.ddg_brave.ingester import validate_companies

            placeholder_rows = await pool.fetch(
                """
                SELECT DISTINCT o.kbo_number, n.name, a.city
                FROM observations o
                LEFT JOIN LATERAL (
                    SELECT value->>'text' AS name FROM observations
                    WHERE kbo_number = o.kbo_number AND field = 'name'
                    ORDER BY confidence DESC, observed_at DESC LIMIT 1
                ) n ON TRUE
                LEFT JOIN LATERAL (
                    SELECT value->>'city' AS city FROM observations
                    WHERE kbo_number = o.kbo_number AND field = 'address'
                    ORDER BY confidence DESC, observed_at DESC LIMIT 1
                ) a ON TRUE
                WHERE o.kbo_number LIKE '9%%'
                  AND o.observed_at >= $1
                """,
                started_at,
            )
            inputs = [
                (str(r["kbo_number"]), r["name"] or "", r["city"] or "")
                for r in placeholder_rows
                if r["name"]
            ]
            if inputs:
                await progress.report(
                    "phase_c2", "ddg_brave", total=len(inputs), message="search cross-validation"
                )
                brave_client: BraveClient | None = None
                if config.brave_subscription_key:
                    brave_client = BraveClient(polite_client, config.brave_subscription_key)
                ddg_client = DdgClient()
                search_report = await validate_companies(
                    inputs,
                    pool,
                    polite_client,
                    brave_client=brave_client,
                    ddg_client=ddg_client,
                    skip_recent_hours=0,
                )
                report.enrichment_observations["ddg_brave"] = search_report.observations_inserted
                report.sources_run.append("ddg_brave")
                log.info("phase_c2_done", obs=search_report.observations_inserted)
            else:
                log.info("phase_c2_skipped", reason="no_placeholders")
        except Exception as exc:
            report.sources_failed["ddg_brave"] = str(exc)
            log.error("phase_c2_failed", error=str(exc))

    # ── Phase D — single consolidation pass ────────────────────────────────────
    await progress.report("phase_d", "consolidation", message="consolidating placeholder KBOs")
    log.info("phase_d_started")
    with suppress(Exception):
        matches = await consolidate(pool)
        report.placeholders_resolved = len(matches)
        log.info("phase_d_finished", matches=len(matches))

    # ── Phase E — single matview refresh ───────────────────────────────────────
    await progress.report("phase_e", "matview", message="refreshing companies_current")
    log.info("phase_e_started")
    with suppress(Exception):
        await pool.execute("SELECT refresh_companies_current()")
        log.info("phase_e_finished")

    # ── Phase F — single prospect scoring pass ─────────────────────────────────
    await progress.report("phase_f", "scoring", message="computing prospect scores")
    log.info("phase_f_started")
    with suppress(Exception):
        n = await refresh_prospect_scores(pool)
        report.prospect_scores_computed = n
        log.info("phase_f_finished", kbos=n)

    # ── Finish ─────────────────────────────────────────────────────────────────
    row = await pool.fetchrow("SELECT COUNT(DISTINCT kbo_number) AS n FROM companies_current")
    report.companies_in_view = int(row["n"]) if row else 0
    report.ended_at = datetime.now(tz=UTC)
    report.duration_s = time.monotonic() - t0

    await progress.report("done", "finished", message="batch complete")
    log.info(
        "batch_finished",
        city=config.city,
        sectors=len(config.sectors),
        phase_a_kbos=report.phase_a_kbos,
        placeholders_resolved=report.placeholders_resolved,
        companies_in_view=report.companies_in_view,
        prospect_scores=report.prospect_scores_computed,
        duration_s=round(report.duration_s, 2),
    )
    return report
