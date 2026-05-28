"""Pipeline orchestrator: run all six sources in dependency order."""

from __future__ import annotations

import asyncio
import shutil
import tempfile
import time
import tomllib
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import structlog

from scraper.lib.data_paths import SECTORS_TOML as _SECTORS_TOML
from scraper.pipeline.consolidate import consolidate

if TYPE_CHECKING:
    from uuid import UUID

    import asyncpg

    from scraper.lib.http.client import PoliteClient

logger = structlog.get_logger()


# Mapping from NL sector slug → NACE prefix(es) for kbo_dump filtering.
# KBO Open Data stores NACE codes without dots (e.g. "43211", not "43.21").
_SECTOR_NACE_PREFIXES: dict[str, list[str]] = {
    # Construction & installation
    "dakdekkers": ["4391"],
    "elektriciens": ["4321"],  # 43211=electrical systems, 43212=alarm/signalling
    "glaszetters": ["4334"],  # 43340=painting and glazing (includes glazing)
    "isolatiebedrijven": ["4329", "4399"],
    "loodgieters": ["4322"],  # 43220=plumbing, heating, air-conditioning
    "metselaars": [
        "4120",
        "4399",
    ],  # 4120=general building construction (incl. masonry); 4399=other specialised
    "schilders": ["4334"],  # 43340=painting and glazing
    "schrijnwerkers": ["4332"],  # 43320=joinery installation
    "tegelzetters": ["4333"],  # 43330=floor and wall covering
    "timmerlieden": ["4332"],  # 43320=joinery installation (on-site carpentry)
    "vloerleggers": ["4333"],  # 43330=floor and wall covering
    "zonnepaneleninstallateurs": ["4321"],
    "airco-installateurs": ["4322"],
    "sanitair": ["4322"],
    "verwarmingsinstallateurs": ["4322"],
    # Automotive
    "autogarages": ["4520"],  # 45201/45202=maintenance and repair of motor vehicles
    "autohandelaars": ["4511", "4519"],
    "carrosserieherstellers": ["4520"],
    "garagisten": ["4520"],  # 45201/45202 — same as autogarages
    # Food & hospitality
    "bakkers": ["1071"],
    "cateringbedrijven": ["5621", "5629"],
    "hotels": ["5510"],
    "restaurants": ["5610"],
    "slagers": ["1013"],
    "supermarkten": ["4711"],
    "traiteurs": ["5621", "5629"],
    # Retail & market
    "bloemisten": ["4776"],
    "boekhandels": ["4761"],
    "kledingwinkels": ["4771"],
    "marktzaken": ["478"],
    "opticiens": ["4778"],
    "schoenenwinkels": ["4772"],
    "tuincentra": ["4776"],
    # Professional services
    "accountants": ["6920"],
    "advocaten": ["6910"],
    "architecten": ["7111"],
    "belastingconsulenten": ["6920"],
    "ingenieurs": ["7112"],
    "managementconsulenten": ["7022"],
    "notarissen": ["6910"],
    "reclamebureaus": ["7311"],
    "uitzendbureaus": ["7820"],
    "vastgoedmakelaars": ["6831", "6832"],
    "vertalingsbureaus": ["7430"],
    "verzekeringsmaatschappijen": ["651", "652"],
    # Healthcare & personal care
    "apothekers": ["4773"],
    "dierenartsen": ["7500"],
    "huisartsen": ["8621"],
    "kappers": ["9602"],
    "kinderdagverblijven": ["8891"],
    "kinesitherapeuten": ["8690"],
    "schoonheidsspecialisten": ["9602"],
    "tandartsen": ["8623"],
    # ICT & media
    "fotografen": ["7420"],
    "informaticabedrijven": [
        "620",
        "631",
        "582",
    ],  # 620x=programming/consultancy, 631x=hosting/portals, 582x=software publishing
    "telecomdiensten": ["61"],
    # Other services
    "banken": ["641", "642"],
    "begrafenisondernemingen": ["9603"],
    "bewakingsdiensten": ["8010"],
    "campings": ["5530"],
    "drukkerijen": ["1811", "1812"],
    "recyclagebedrijven": ["381", "382", "383"],
    "recyclagebedrijven-industrieel": ["381", "382", "383"],
    "scholen": ["85"],
    "schoonmaakbedrijven": ["8121", "8122", "8129"],
    "taxidiensten": ["4932"],
    "transportbedrijven": ["4941", "4939", "4942"],
    "transportbedrijven-zwaar": ["4941", "4942"],
    "tuinaanleggers": ["8130"],
    "verhuisbedrijven": ["4942"],
    # Tier 1: Guaranteed / very high HV — KBO Open Data only (not on goudengids)
    "energieproducenten": ["3511", "3512", "3513", "3514"],
    "gasdistributie": ["3521", "3522"],
    "stoomlevering": ["3530"],
    "chemiebedrijven": ["201", "202", "203", "204", "205", "206"],
    "farmaceutische-bedrijven": ["211", "212"],
    "staalindustrie": ["241", "242", "243", "244", "245"],
    "petroleumraffinaderijen": ["191", "192"],
    "datacenters": ["6190"],
    "spoortransport": ["4910", "4920"],
    # Tier 2: High HV — KBO Open Data only
    "waterzuivering": ["3600", "3700"],
    "afvalverwerkingsindustrie": ["382", "383", "390"],
    "automobielfabrieken": ["291", "292", "293"],
    "scheepsbouw": ["301", "302", "303"],
    "papierfabrieken": ["171", "172"],
    "rubberindustrie": ["221", "222"],
    "glasindustrie": ["231", "235"],
    "elektronica-fabrieken": ["261", "262", "263", "271", "272", "273", "274"],
    "machinebouwers": ["281", "282", "283", "284", "289"],
    "metaalverwerkingsbedrijven": ["251", "252", "253", "255", "256", "257", "259"],
    "voedingsindustrie": [
        "101",
        "102",
        "103",
        "104",
        "105",
        "106",
        "107",
        "108",
        "109",
        "110",
    ],
    "diervoederfabricage": ["1091", "1092"],
    "textielfabricage": ["131", "132"],
    # Tier 3: Moderate HV — KBO Open Data only
    "ziekenhuizen": ["8610"],
    "logistiekverleners": ["5210", "5220", "5221", "5224"],
    "havenactiviteiten": ["5222", "5223"],
    "bouwbedrijven": ["4110", "4120", "4211", "4212", "4213", "4221", "4222", "4223"],
    "universiteiten": ["8542"],
    "ingenieurs-adviesbureaus": ["7112"],
    "grote-bedrijfsgebouwen": ["6820"],
    "steengroeven": ["0812"],
    "tuinbouwbedrijven-industrieel": ["0113", "0119", "013"],
    "intensieve-veehouderij": ["0147"],
    "snellaadstations": ["4799"],
}


@dataclass(frozen=True, slots=True)
class PipelineConfig:
    sector: str
    city: str
    sector_slug: str
    max_pages: int = 5
    lang: Literal["nl", "fr"] = "nl"
    use_fixture: bool = False
    fixture_zip_path: Path | None = None
    postcodes: tuple[str, ...] = ()
    do_kbo_dump: bool = True
    do_goudengids: bool = True
    do_kbopub: bool = True
    do_nbb: bool = True
    do_website: bool = True
    do_search: bool = True
    nbb_subscription_key: str | None = None
    brave_subscription_key: str | None = None
    database_url: str | None = None


@dataclass
class PipelineReport:
    run_id: UUID | None
    sector: str
    city: str
    started_at: datetime
    ended_at: datetime | None
    sources_run: list[str] = field(default_factory=list)
    sources_skipped: list[str] = field(default_factory=list)
    sources_failed: dict[str, str] = field(default_factory=dict)
    observations_inserted_per_source: dict[str, int] = field(default_factory=dict)
    duration_per_source: dict[str, float] = field(default_factory=dict)
    placeholders_created: int = 0
    placeholders_resolved: int = 0
    companies_in_view: int = 0
    duration_s: float = 0.0
    kbo_dump_run_id: UUID | None = None  # set by staging path; used by kbopub/nbb to find KBOs


def resolve_sector_slugs(input_slug: str) -> tuple[str, str]:
    """Return (nl_slug, fr_slug) for an input slug (NL or FR). Raises ValueError if unknown."""
    with _SECTORS_TOML.open("rb") as fh:
        data = tomllib.load(fh)
    for entry in data.values():
        if not isinstance(entry, dict):
            continue
        nl = str(entry.get("nl_slug", ""))
        fr = str(entry.get("fr_slug", ""))
        if input_slug in (nl, fr):
            return nl, fr
    raise ValueError(
        f"Unknown sector slug {input_slug!r}. Check "
        f".claude/skills/goudengids-listing/references/sectors.toml"
    )


def _get_goudengids_slug(config: PipelineConfig) -> str:
    """Return the correct slug (NL or FR) for goudengids based on config.lang."""
    if config.lang == "nl":
        return config.sector_slug
    try:
        _, fr_slug = resolve_sector_slugs(config.sector_slug)
        return fr_slug
    except ValueError:
        return config.sector_slug


def _create_fixture_zip(mini_dir: Path) -> tuple[Path, Path]:
    """Pack synthetic_mini CSVs into a temporary ZIP. Returns (zip_path, tmp_dir)."""
    tmp = Path(tempfile.mkdtemp())
    out = tmp / "KboOpenData_fixture_Full.zip"
    with zipfile.ZipFile(out, "w") as zf:
        for f in mini_dir.glob("*.csv"):
            zf.write(f, arcname=f.name)
    return out, tmp


async def _count_companies_in_view(pool: asyncpg.Pool) -> int:
    row = await pool.fetchrow("SELECT COUNT(DISTINCT kbo_number) AS n FROM companies_current")
    return int(row["n"]) if row else 0


async def _get_real_kbos(
    pool: asyncpg.Pool,
    since: datetime,
    kbo_dump_run_id: UUID | None = None,
) -> list[str]:
    """Return non-placeholder KBOs from the current pipeline run.

    Uses observed_at for the fixture/ingest_zip path (real-time observations) and
    run_id for the staging path (observed_at is the snapshot date, not today).
    """
    if kbo_dump_run_id is not None:
        rows = await pool.fetch(
            "SELECT DISTINCT kbo_number FROM observations "
            "WHERE kbo_number NOT LIKE '9%' AND run_id = $1",
            kbo_dump_run_id,
        )
    else:
        rows = await pool.fetch(
            "SELECT DISTINCT kbo_number FROM observations "
            "WHERE kbo_number NOT LIKE '9%' AND observed_at >= $1",
            since,
        )
    return [str(r["kbo_number"]).strip() for r in rows]


async def _get_website_pairs(pool: asyncpg.Pool, since: datetime) -> list[tuple[str, str]]:
    """Return (kbo, url) pairs for websites observed on or after *since* (current pipeline run)."""
    rows = await pool.fetch(
        "SELECT DISTINCT kbo_number, value->>'url' AS url FROM observations "
        "WHERE field = 'website' AND observed_at >= $1",
        since,
    )
    return [(str(r["kbo_number"]).strip(), r["url"]) for r in rows if r["url"]]


async def _get_real_kbos_for_sector_city(
    pool: asyncpg.Pool, nace_prefixes: list[str], city: str
) -> list[str]:
    """Return KBOs from kbo_dump matching sector NACE prefix(es) and city (all-time).

    Used as fallback when the current pipeline run produced no new KBOs
    (e.g. kbo_dump was skipped because no ZIP was provided).
    """
    rows = await pool.fetch(
        "SELECT DISTINCT a.kbo_number FROM observations a "
        "JOIN observations b ON a.kbo_number = b.kbo_number "
        "WHERE a.source = 'kbo_dump' AND a.field = 'address' "
        "AND a.value->>'city' ILIKE $1 "
        "AND b.source = 'kbo_dump' AND b.field = 'nace_code' "
        "AND b.value->>'code' LIKE ANY($2::text[])",
        f"%{city}%",
        [f"{p}%" for p in nace_prefixes],
    )
    return [str(r["kbo_number"]).strip() for r in rows]


async def _get_placeholder_inputs(
    pool: asyncpg.Pool, since: datetime
) -> list[tuple[str, str, str]]:
    """Return (kbo_number, name, city) for placeholder KBOs observed in the current pipeline run."""
    name_rows = await pool.fetch(
        "SELECT DISTINCT kbo_number, value->>'text' AS name FROM observations "
        "WHERE field = 'name' AND kbo_number LIKE '9%' AND observed_at >= $1",
        since,
    )
    addr_rows = await pool.fetch(
        "SELECT DISTINCT kbo_number, value->>'city' AS city FROM observations "
        "WHERE field = 'address' AND kbo_number LIKE '9%' AND observed_at >= $1",
        since,
    )
    names = {str(r["kbo_number"]): r["name"] or "" for r in name_rows}
    cities = {str(r["kbo_number"]): r["city"] or "" for r in addr_rows}
    return [(kbo, names[kbo], cities.get(kbo, "")) for kbo in names if names[kbo]]


# ── Per-source helper coroutines ───────────────────────────────────────────────
# Each catches all exceptions internally so TaskGroup never sees an unhandled
# exception (which would cancel sibling tasks).


async def _run_kbo_dump(
    config: PipelineConfig,
    pool: asyncpg.Pool,
    started_at: datetime,
    report: PipelineReport,
) -> None:
    t0 = time.monotonic()
    tmp_dir: Path | None = None
    log = logger.bind(sector=config.sector, city=config.city)
    try:
        if config.use_fixture:
            # Synthetic test data — re-parse the fixture ZIP directly (fast, no staging).
            from scraper.sources.kbo_dump.ingester import ingest_zip

            mini_dir = (
                Path(__file__).parents[3] / "tests" / "golden" / "kbo_dump" / "synthetic_mini"
            )
            zip_path, tmp_dir = _create_fixture_zip(mini_dir)
            kbo_report = await ingest_zip(
                zip_path, pool, sector_filter=None, city_filter=[config.city], refresh_view=False
            )
            report.sources_run.append("kbo_dump")
            report.observations_inserted_per_source["kbo_dump"] = kbo_report.observations_inserted
            log.info(
                "kbo_dump_done",
                observations=kbo_report.observations_inserted,
                enterprises=kbo_report.enterprises_processed,
            )

        elif config.fixture_zip_path is not None:
            # Real ZIP — stage once (idempotent), then read from staging tables.
            from datetime import UTC

            from scraper.db.repositories.runs import RunsRepo
            from scraper.pipeline.batch import (
                emit_phase_a,
                get_entity_filter,
                resolve_snapshot_date,
            )
            from scraper.sources.kbo_dump.staging import stage_zip

            zip_path = config.fixture_zip_path
            staging = await stage_zip(zip_path, pool)
            if not staging.skipped:
                log.info("kbo_stage_auto_staged", duration_s=round(staging.duration_s, 2))

            snapshot_date = await resolve_snapshot_date(pool)
            if snapshot_date is None:
                raise RuntimeError("Staging tables empty after stage_zip")

            observed_at = datetime(
                snapshot_date.year, snapshot_date.month, snapshot_date.day, tzinfo=UTC
            )
            nace_prefixes = _SECTOR_NACE_PREFIXES.get(config.sector_slug, [])
            entity_numbers = await get_entity_filter(
                pool, snapshot_date, config.city, nace_prefixes
            )
            log.info("entity_filter_computed", count=len(entity_numbers))

            runs_repo = RunsRepo(pool)
            run_id = await runs_repo.start_run(
                source="kbo_dump",
                city_slug=config.city,
                notes=f"snapshot={snapshot_date}",
            )
            report.kbo_dump_run_id = run_id
            n_obs = 0
            if entity_numbers:
                n_obs = await emit_phase_a(pool, snapshot_date, entity_numbers, run_id, observed_at)
            await runs_repo.finish_run(run_id, jobs_done=n_obs)

            report.sources_run.append("kbo_dump")
            report.observations_inserted_per_source["kbo_dump"] = n_obs
            log.info("kbo_dump_done", observations=n_obs, enterprises=len(entity_numbers))

        else:
            raise ValueError(
                "kbo_dump requires --use-fixture or --fixture-zip path. "
                "Real KBO Open Data ZIP must be provided explicitly."
            )

    except Exception as exc:
        report.sources_failed["kbo_dump"] = str(exc)
        log.error("kbo_dump_failed", error=str(exc))
    finally:
        report.duration_per_source["kbo_dump"] = round(time.monotonic() - t0, 2)
        if tmp_dir is not None:
            shutil.rmtree(tmp_dir, ignore_errors=True)


async def _run_goudengids(
    config: PipelineConfig,
    pool: asyncpg.Pool,
    polite_client: PoliteClient,
    report: PipelineReport,
) -> None:
    t0 = time.monotonic()
    log = logger.bind(sector=config.sector, city=config.city)
    try:
        # Industrial sectors are KBO Open Data only — they don't exist on goudengids.be.
        # Detect this by checking whether the slug is in sectors.toml; skip gracefully if not.
        try:
            resolve_sector_slugs(config.sector_slug)
        except ValueError:
            report.sources_skipped.append("goudengids")
            log.info("goudengids_skipped_kbo_only_sector", sector_slug=config.sector_slug)
            return

        from scraper.sources.goudengids.fetcher import BrowserListingFetcher
        from scraper.sources.goudengids.ingester import ingest_sector_city

        domain = "pagesdor.be" if config.lang == "fr" else "goudengids.be"
        fetcher = BrowserListingFetcher(polite_client.limiter, domain=domain)
        slug = _get_goudengids_slug(config)

        goud_report = await ingest_sector_city(
            slug,
            config.city,
            pool,
            fetcher,
            max_pages=config.max_pages,
            lang=config.lang,
            skip_recent_hours=0,
        )
        report.sources_run.append("goudengids")
        report.observations_inserted_per_source["goudengids"] = goud_report.observations_inserted
        report.placeholders_created += goud_report.placeholders_created
        log.info(
            "goudengids_done",
            observations=goud_report.observations_inserted,
            placeholders=goud_report.placeholders_created,
        )
    except Exception as exc:
        error_str = str(exc) or repr(exc)
        report.sources_failed["goudengids"] = error_str
        log.error("goudengids_failed", error=error_str)
    finally:
        report.duration_per_source["goudengids"] = round(time.monotonic() - t0, 2)


async def _run_kbopub(
    config: PipelineConfig,
    pool: asyncpg.Pool,
    polite_client: PoliteClient,
    started_at: datetime,
    report: PipelineReport,
) -> None:
    t0 = time.monotonic()
    log = logger.bind(sector=config.sector, city=config.city)
    try:
        from scraper.sources.kbopub_html.ingester import ingest_kbos as kbopub_ingest

        real_kbos = await _get_real_kbos(pool, started_at, kbo_dump_run_id=report.kbo_dump_run_id)
        skip_hours = 0
        if not real_kbos:
            nace_prefixes = _SECTOR_NACE_PREFIXES.get(config.sector_slug, [])
            if nace_prefixes:
                real_kbos = await _get_real_kbos_for_sector_city(pool, nace_prefixes, config.city)
                skip_hours = 24
        if real_kbos:
            kbopub_report = await kbopub_ingest(
                real_kbos,
                pool,
                polite_client.limiter,
                lang=config.lang,
                skip_recent_hours=skip_hours,
            )
            report.sources_run.append("kbopub_html")
            report.observations_inserted_per_source["kbopub_html"] = (
                kbopub_report.observations_inserted
            )
            log.info(
                "kbopub_done",
                kbos=kbopub_report.kbos_processed,
                observations=kbopub_report.observations_inserted,
            )
        else:
            report.sources_skipped.append("kbopub_html")
            log.info("kbopub_skipped_no_real_kbos")
    except Exception as exc:
        report.sources_failed["kbopub_html"] = str(exc)
        log.error("kbopub_failed", error=str(exc))
    finally:
        report.duration_per_source["kbopub_html"] = round(time.monotonic() - t0, 2)


async def _run_nbb(
    config: PipelineConfig,
    pool: asyncpg.Pool,
    polite_client: PoliteClient,
    started_at: datetime,
    report: PipelineReport,
) -> None:
    t0 = time.monotonic()
    log = logger.bind(sector=config.sector, city=config.city)
    try:
        from scraper.sources.nbb_authentic.client import NbbClient
        from scraper.sources.nbb_authentic.ingester import ingest_kbos as nbb_ingest

        nbb_client = NbbClient(polite_client, config.nbb_subscription_key or "")
        real_kbos = await _get_real_kbos(pool, started_at, kbo_dump_run_id=report.kbo_dump_run_id)
        if real_kbos:
            nbb_report = await nbb_ingest(
                real_kbos, pool, nbb_client, skip_recent_hours=0, years_back=3
            )
            report.sources_run.append("nbb_authentic")
            report.observations_inserted_per_source["nbb_authentic"] = (
                nbb_report.observations_inserted
            )
            log.info(
                "nbb_done",
                kbos=nbb_report.kbos_processed,
                observations=nbb_report.observations_inserted,
            )
        else:
            report.sources_skipped.append("nbb_authentic")
    except Exception as exc:
        report.sources_failed["nbb_authentic"] = str(exc)
        log.error("nbb_failed", error=str(exc))
    finally:
        report.duration_per_source["nbb_authentic"] = round(time.monotonic() - t0, 2)


async def _run_website(
    config: PipelineConfig,
    pool: asyncpg.Pool,
    polite_client: PoliteClient,
    started_at: datetime,
    report: PipelineReport,
) -> None:
    t0 = time.monotonic()
    log = logger.bind(sector=config.sector, city=config.city)
    try:
        from scraper.sources.website.ingester import ingest_kbos as website_ingest

        pairs = await _get_website_pairs(pool, started_at)
        if pairs:
            web_report = await website_ingest(pairs, pool, polite_client, skip_recent_hours=0)
            report.sources_run.append("website")
            report.observations_inserted_per_source["website"] = web_report.observations_inserted
            log.info(
                "website_done",
                kbos=web_report.kbos_processed,
                observations=web_report.observations_inserted,
            )
        else:
            report.sources_skipped.append("website")
            log.info("website_skipped_no_pairs")
    except Exception as exc:
        report.sources_failed["website"] = str(exc)
        log.error("website_failed", error=str(exc))
    finally:
        report.duration_per_source["website"] = round(time.monotonic() - t0, 2)


async def _run_search(
    config: PipelineConfig,
    pool: asyncpg.Pool,
    polite_client: PoliteClient,
    started_at: datetime,
    report: PipelineReport,
) -> None:
    t0 = time.monotonic()
    log = logger.bind(sector=config.sector, city=config.city)
    try:
        from scraper.sources.ddg_brave.brave_client import BraveClient
        from scraper.sources.ddg_brave.ddg_client import DdgClient
        from scraper.sources.ddg_brave.ingester import validate_companies

        brave_client: BraveClient | None = None
        if config.brave_subscription_key:
            brave_client = BraveClient(polite_client, config.brave_subscription_key)
        ddg_client = DdgClient()

        inputs = await _get_placeholder_inputs(pool, started_at)
        if inputs:
            search_report = await validate_companies(
                inputs,
                pool,
                polite_client,
                brave_client=brave_client,
                ddg_client=ddg_client,
                skip_recent_hours=0,
            )
            report.sources_run.append("ddg_brave")
            report.observations_inserted_per_source["ddg_brave"] = (
                search_report.observations_inserted
            )
            log.info(
                "search_done",
                queries=search_report.queries_processed,
                observations=search_report.observations_inserted,
            )
        else:
            report.sources_skipped.append("ddg_brave")
            log.info("search_skipped_no_placeholders")
    except Exception as exc:
        report.sources_failed["ddg_brave"] = str(exc)
        log.error("search_failed", error=str(exc))
    finally:
        report.duration_per_source["ddg_brave"] = round(time.monotonic() - t0, 2)


async def run_pipeline(
    config: PipelineConfig,
    pool: asyncpg.Pool,
    polite_client: PoliteClient,
) -> PipelineReport:
    """Run all six sources in two dependency waves with per-source error isolation.

    Wave A (no deps):   kbo_dump || goudengids
    Wave B (need A):    kbopub_html || nbb_authentic || website || ddg_brave
    Then:               consolidate → refresh materialised view

    Sources hit different hosts, so running them in parallel does not violate
    the per-host politeness policy enforced by HostLimiter.
    """
    t0 = time.monotonic()
    started_at = datetime.now(tz=UTC)
    report = PipelineReport(
        run_id=None,
        sector=config.sector,
        city=config.city,
        started_at=started_at,
        ended_at=None,
    )

    log = logger.bind(sector=config.sector, city=config.city)
    log.info("pipeline_started")

    # Close any orphaned run_log rows left by a previous crashed/killed process.
    # Without this, the status query shows phantom "still running" entries forever.
    try:
        await pool.execute(
            "UPDATE run_log SET ended_at = NOW(), notes = COALESCE(notes || ' ', '') || '[crashed]'"
            " WHERE ended_at IS NULL AND started_at < $1",
            started_at,
        )
    except Exception:
        pass

    # ── Wave A: kbo_dump (CPU-heavy ZIP parse — runs alone to avoid starving Chromium) ──
    async with asyncio.TaskGroup() as tg_a:
        if config.do_kbo_dump:
            tg_a.create_task(_run_kbo_dump(config, pool, started_at, report))
        else:
            report.sources_skipped.append("kbo_dump")
            report.duration_per_source["kbo_dump"] = 0.0

    # ── Wave B: network sources (goudengids gets CPU headroom now that ZIP is done) ──
    async with asyncio.TaskGroup() as tg_b:
        if config.do_goudengids:
            tg_b.create_task(_run_goudengids(config, pool, polite_client, report))
        else:
            report.sources_skipped.append("goudengids")
            report.duration_per_source["goudengids"] = 0.0

        if config.do_kbopub:
            tg_b.create_task(_run_kbopub(config, pool, polite_client, started_at, report))
        else:
            report.sources_skipped.append("kbopub_html")
            report.duration_per_source["kbopub_html"] = 0.0

        if config.do_nbb and config.nbb_subscription_key:
            tg_b.create_task(_run_nbb(config, pool, polite_client, started_at, report))
        else:
            reason = "no_key" if not config.nbb_subscription_key else "disabled"
            report.sources_skipped.append("nbb_authentic")
            report.duration_per_source["nbb_authentic"] = 0.0
            log.debug("nbb_skipped", reason=reason)

        if config.do_website:
            tg_b.create_task(_run_website(config, pool, polite_client, started_at, report))
        else:
            report.sources_skipped.append("website")
            report.duration_per_source["website"] = 0.0

        if config.do_search:
            tg_b.create_task(_run_search(config, pool, polite_client, started_at, report))
        else:
            report.sources_skipped.append("ddg_brave")
            report.duration_per_source["ddg_brave"] = 0.0

    # ── Consolidation pass ─────────────────────────────────────────────────────
    try:
        matches = await consolidate(pool)
        report.placeholders_resolved = len(matches)
        log.info("consolidation_done", matches=len(matches))
    except Exception as exc:
        log.error("consolidation_failed", error=str(exc))

    # ── Refresh materialised view ──────────────────────────────────────────────
    try:
        await pool.execute("SELECT refresh_companies_current()")
    except Exception as exc:
        log.error("matview_refresh_failed", error=str(exc))

    # ── Refresh prospect scores ────────────────────────────────────────────────
    try:
        from scraper.scoring.prospect import refresh_prospect_scores as _refresh_ps

        n = await _refresh_ps(pool)
        log.info("prospect_scores_refreshed", kbos=n)
    except Exception as exc:
        log.error("prospect_scores_refresh_failed", error=str(exc))

    report.ended_at = datetime.now(tz=UTC)
    report.companies_in_view = await _count_companies_in_view(pool)
    report.duration_s = time.monotonic() - t0

    log.info(
        "pipeline_finished",
        sources_run=report.sources_run,
        sources_failed=list(report.sources_failed.keys()),
        companies_in_view=report.companies_in_view,
        duration_s=round(report.duration_s, 2),
    )
    return report
