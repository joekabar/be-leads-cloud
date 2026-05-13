"""Pipeline orchestrator: run all six sources in dependency order."""

from __future__ import annotations

import shutil
import tempfile
import tomllib
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import structlog

from scraper.pipeline.consolidate import consolidate

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

# Mapping from NL sector slug → NACE prefix(es) for kbo_dump filtering.
_SECTOR_NACE_PREFIXES: dict[str, list[str]] = {
    "elektriciens": ["43.2"],
    "loodgieters": ["43.22"],
    "schilders": ["43.34"],
    "metselaars": ["43.3"],
    "dakdekkers": ["43.91"],
    "timmerlieden": ["43.32"],
    "garagisten": ["45.2"],
    "bakkers": ["10.71"],
    "slagers": ["10.13"],
    "kappers": ["96.02"],
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
    placeholders_created: int = 0
    placeholders_resolved: int = 0
    companies_in_view: int = 0
    duration_s: float = 0.0


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


async def _get_real_kbos(pool: asyncpg.Pool) -> list[str]:
    rows = await pool.fetch(
        "SELECT DISTINCT kbo_number FROM observations WHERE kbo_number NOT LIKE '9%'"
    )
    return [str(r["kbo_number"]).strip() for r in rows]


async def _get_website_pairs(pool: asyncpg.Pool) -> list[tuple[str, str]]:
    rows = await pool.fetch(
        "SELECT kbo_number, value->>'url' AS url FROM companies_current "
        "WHERE field = 'website' AND kbo_number NOT LIKE '9%'"
    )
    return [(str(r["kbo_number"]).strip(), r["url"]) for r in rows if r["url"]]


async def _get_placeholder_inputs(pool: asyncpg.Pool) -> list[tuple[str, str, str]]:
    """Return (kbo_number, name, city) for placeholder KBOs."""
    name_rows = await pool.fetch(
        "SELECT kbo_number, value->>'text' AS name FROM companies_current "
        "WHERE field = 'name' AND kbo_number LIKE '9%'"
    )
    addr_rows = await pool.fetch(
        "SELECT kbo_number, value->>'city' AS city FROM companies_current "
        "WHERE field = 'address' AND kbo_number LIKE '9%'"
    )
    names = {str(r["kbo_number"]): r["name"] or "" for r in name_rows}
    cities = {str(r["kbo_number"]): r["city"] or "" for r in addr_rows}
    return [(kbo, names[kbo], cities.get(kbo, "")) for kbo in names if names[kbo]]


async def run_pipeline(
    config: PipelineConfig,
    pool: asyncpg.Pool,
    polite_client: PoliteClient,
) -> PipelineReport:
    """Run all six sources in dependency order with per-source error isolation."""
    import time

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

    tmp_dir: Path | None = None

    # ── Source 1: kbo_dump ─────────────────────────────────────────────────
    if config.do_kbo_dump:
        try:
            from scraper.sources.kbo_dump.ingester import ingest_zip

            if config.use_fixture:
                mini_dir = (
                    Path(__file__).parents[3] / "tests" / "golden" / "kbo_dump" / "synthetic_mini"
                )
                zip_path, tmp_dir = _create_fixture_zip(mini_dir)
            elif config.fixture_zip_path is not None:
                zip_path = config.fixture_zip_path
            else:
                raise ValueError(
                    "kbo_dump requires --use-fixture or --fixture-zip path. "
                    "Real KBO Open Data ZIP must be provided explicitly."
                )

            nace_filter: list[str] | None = None
            if not config.use_fixture:
                nace_filter = _SECTOR_NACE_PREFIXES.get(config.sector_slug)

            kbo_report = await ingest_zip(
                zip_path,
                pool,
                sector_filter=nace_filter,
                city_filter=[config.city],
                refresh_view=False,
            )
            report.sources_run.append("kbo_dump")
            report.observations_inserted_per_source["kbo_dump"] = kbo_report.observations_inserted
            log.info(
                "kbo_dump_done",
                observations=kbo_report.observations_inserted,
                enterprises=kbo_report.enterprises_processed,
            )
        except Exception as exc:
            report.sources_failed["kbo_dump"] = str(exc)
            log.error("kbo_dump_failed", error=str(exc))
        finally:
            if tmp_dir is not None:
                shutil.rmtree(tmp_dir, ignore_errors=True)
    else:
        report.sources_skipped.append("kbo_dump")

    # ── Source 2: goudengids ───────────────────────────────────────────────
    if config.do_goudengids:
        try:
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
            report.observations_inserted_per_source["goudengids"] = (
                goud_report.observations_inserted
            )
            report.placeholders_created += goud_report.placeholders_created
            log.info(
                "goudengids_done",
                observations=goud_report.observations_inserted,
                placeholders=goud_report.placeholders_created,
            )
        except Exception as exc:
            report.sources_failed["goudengids"] = str(exc)
            log.error("goudengids_failed", error=str(exc))
    else:
        report.sources_skipped.append("goudengids")

    # ── Source 3: kbopub_html ──────────────────────────────────────────────
    if config.do_kbopub:
        try:
            from scraper.sources.kbopub_html.ingester import ingest_kbos as kbopub_ingest

            real_kbos = await _get_real_kbos(pool)
            if real_kbos:
                kbopub_report = await kbopub_ingest(
                    real_kbos,
                    pool,
                    polite_client.limiter,
                    lang=config.lang,
                    skip_recent_hours=0,
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
    else:
        report.sources_skipped.append("kbopub_html")

    # ── Source 4: nbb_authentic ────────────────────────────────────────────
    if config.do_nbb and config.nbb_subscription_key:
        try:
            from scraper.sources.nbb_authentic.client import NbbClient
            from scraper.sources.nbb_authentic.ingester import ingest_kbos as nbb_ingest

            nbb_client = NbbClient(polite_client, config.nbb_subscription_key)
            real_kbos = await _get_real_kbos(pool)
            if real_kbos:
                nbb_report = await nbb_ingest(real_kbos, pool, nbb_client, skip_recent_hours=0)
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
    else:
        reason = "no_key" if not config.nbb_subscription_key else "disabled"
        report.sources_skipped.append("nbb_authentic")
        log.debug("nbb_skipped", reason=reason)

    # ── Source 5: website ──────────────────────────────────────────────────
    if config.do_website:
        try:
            from scraper.sources.website.ingester import ingest_kbos as website_ingest

            pairs = await _get_website_pairs(pool)
            if pairs:
                web_report = await website_ingest(pairs, pool, polite_client, skip_recent_hours=0)
                report.sources_run.append("website")
                report.observations_inserted_per_source["website"] = (
                    web_report.observations_inserted
                )
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
    else:
        report.sources_skipped.append("website")

    # ── Source 6: ddg_brave ────────────────────────────────────────────────
    if config.do_search:
        try:
            from scraper.sources.ddg_brave.brave_client import BraveClient
            from scraper.sources.ddg_brave.ddg_client import DdgClient
            from scraper.sources.ddg_brave.ingester import validate_companies

            brave_client: BraveClient | None = None
            if config.brave_subscription_key:
                brave_client = BraveClient(polite_client, config.brave_subscription_key)
            ddg_client = DdgClient()

            inputs = await _get_placeholder_inputs(pool)
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
    else:
        report.sources_skipped.append("ddg_brave")

    # ── Consolidation pass ─────────────────────────────────────────────────
    try:
        matches = await consolidate(pool)
        report.placeholders_resolved = len(matches)
        log.info("consolidation_done", matches=len(matches))
    except Exception as exc:
        log.error("consolidation_failed", error=str(exc))

    # ── Refresh materialised view ──────────────────────────────────────────
    try:
        await pool.execute("SELECT refresh_companies_current()")
    except Exception as exc:
        log.error("matview_refresh_failed", error=str(exc))

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
