"""Orchestrate a full goudengids sector x city ingest run."""

from __future__ import annotations

import time
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

import structlog
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from scraper.db.repositories.observations import ObservationsRepo
from scraper.db.repositories.runs import RunsRepo
from scraper.lib.data_paths import SECTORS_TOML as _SECTORS_TOML
from scraper.lib.errors import BlockedError
from scraper.pipeline.city_map import get_postal_codes
from scraper.pipeline.sector_queue import COMPLETE_MARKER, INTERRUPTED_MARKER
from scraper.sources.goudengids.parser import parse_listing_page
from scraper.sources.goudengids.transformer import card_to_observations, make_placeholder_kbo

if TYPE_CHECKING:
    import asyncpg

    from scraper.db.models import Observation
    from scraper.sources.goudengids.fetcher import BrowserListingFetcher

logger = structlog.get_logger()


_BATCH_SIZE = 200


def load_valid_sectors() -> dict[str, str]:
    """Return {nl_slug: display_name} for all sectors in sectors.toml."""
    with _SECTORS_TOML.open("rb") as fh:
        data = tomllib.load(fh)
    return {
        str(v["nl_slug"]): str(v.get("display", v["nl_slug"]))
        for v in data.values()
        if isinstance(v, dict) and "nl_slug" in v
    }


@dataclass
class GoudengidsReport:
    sector: str
    city: str
    pages_scanned: int = 0
    cards_found: int = 0
    #: Cards goudengids returned that are outside the requested city (its nationwide
    #: fallback). Counted rather than silently dropped so thin runs are explainable.
    cards_out_of_city: int = 0
    cards_with_phone: int = 0
    cards_with_website: int = 0
    observations_inserted: int = 0
    placeholders_created: int = 0
    #: True when paging stopped because results had left the requested city. A decision,
    #: not a failure — the sector still counts as covered.
    stopped_early: bool = False
    duration_s: float = 0.0


async def _recent_placeholder_kbos(
    pool: asyncpg.Pool,
    cutoff: datetime,
) -> set[str]:
    rows = await pool.fetch(
        "SELECT DISTINCT kbo_number FROM observations "
        "WHERE source = 'goudengids' AND observed_at > $1 AND kbo_number LIKE '9%'",
        cutoff,
    )
    return {r["kbo_number"] for r in rows}


def card_in_city(postal_code: str | None, allowed_postcodes: set[str]) -> bool:
    """Return True when a listing card belongs to the city that was searched for.

    goudengids falls back to nationwide results when a sector has few matches in the
    requested city, so the URL containing the city is not a guarantee. Filtering on the
    card's own postal code is what actually scopes the run.

    An empty *allowed_postcodes* means the city is not in the postcode map — filtering
    is then impossible and everything is kept, rather than discarding the whole run.
    A card with no postal code cannot be verified and is dropped.
    """
    if not allowed_postcodes:
        return True
    if postal_code is None or not postal_code.strip():
        return False
    return postal_code.strip() in allowed_postcodes


async def ingest_sector_city(
    sector_slug: str,
    city_slug: str,
    pool: asyncpg.Pool,
    fetcher: BrowserListingFetcher,
    *,
    max_pages: int = 25,
    lang: Literal["nl", "fr"] = "nl",
    skip_recent_hours: int = 24,
    #: Consecutive pages with no in-city card before giving up on the sector.
    max_empty_pages: int = 3,
    refresh_matview: bool = True,
) -> GoudengidsReport:
    """Scrape all listing pages for sector x city and write observations.

    Idempotent within skip_recent_hours: cards whose placeholder KBO already has a
    recent goudengids observation are skipped.

    *refresh_matview* rebuilds ``companies_current`` when the run finishes. That costs
    ~130 s against a DISTINCT ON view over millions of observations, so the batch
    orchestrator passes ``False`` and refreshes once before Phase D (consolidate), which
    is the first thing in a batch that actually reads the view. It defaults to ``True``
    so the standalone CLI still leaves the view consistent after a single sector.
    """
    valid_sectors = load_valid_sectors()
    if sector_slug not in valid_sectors:
        raise ValueError(
            f"Unknown sector slug {sector_slug!r}. Valid slugs: {sorted(valid_sectors)}"
        )
    if not city_slug.strip():
        raise ValueError("city_slug must not be empty")

    t0 = time.monotonic()
    report = GoudengidsReport(sector=sector_slug, city=city_slug)

    runs_repo = RunsRepo(pool)
    obs_repo = ObservationsRepo(pool)

    run_id = await runs_repo.start_run(
        source="goudengids",
        sector_slug=sector_slug,
        city_slug=city_slug,
    )
    snapshot_at = datetime.now(tz=UTC)
    log = logger.bind(
        run_id=str(run_id),
        source="goudengids",
        sector=sector_slug,
        city=city_slug,
    )
    log.info("goudengids_ingest_started", max_pages=max_pages, lang=lang)

    # Pre-load recently-seen placeholder KBOs to avoid redundant inserts.
    recent_kbos: set[str] = set()
    if skip_recent_hours > 0:
        cutoff = snapshot_at - timedelta(hours=skip_recent_hours)
        recent_kbos = await _recent_placeholder_kbos(pool, cutoff)

    # Scope results to the requested city. goudengids widens to nationwide results
    # when a sector is thin locally, so the card's own postcode is the real filter.
    allowed_postcodes = set(get_postal_codes(city_slug) or [])
    if not allowed_postcodes:
        log.warning("goudengids_city_not_in_postcode_map", city=city_slug)

    buffer: list[Observation] = []
    seen_placeholders: set[str] = set()
    empty_page_streak = 0
    # Did this run read the listing to the end, or was it cut short? Only a cut-short run
    # deserves a retry — a run that finished has seen everything the sector offers, even
    # if every card was out of city or already known. See pipeline/sector_queue.py.
    interrupted = False

    try:
        async with fetcher:
            for page_num in range(1, max_pages + 1):
                try:
                    listing = await fetcher.fetch_page(sector_slug, city_slug, page_num, lang=lang)
                except BlockedError:
                    log.error("goudengids_blocked_aborting", page=page_num)
                    interrupted = True
                    break
                except (PlaywrightTimeoutError, TimeoutError):
                    log.warning("goudengids_page_timeout_aborting", page=page_num)
                    interrupted = True
                    break

                report.pages_scanned += 1

                if listing.is_last_page:
                    break

                cards = parse_listing_page(listing.html, domain=fetcher._domain)
                report.cards_found += len(cards)
                in_city_this_page = 0

                for card in cards:
                    if not card_in_city(card.address_postal_code, allowed_postcodes):
                        report.cards_out_of_city += 1
                        continue
                    in_city_this_page += 1

                    placeholder = make_placeholder_kbo(card.name, card.address_postal_code)

                    if placeholder in recent_kbos:
                        continue

                    if card.phones:
                        report.cards_with_phone += 1
                    if card.website:
                        report.cards_with_website += 1

                    obs = card_to_observations(card, run_id, snapshot_at)
                    buffer.extend(obs)

                    if placeholder not in seen_placeholders:
                        seen_placeholders.add(placeholder)
                        report.placeholders_created += 1

                    if len(buffer) >= _BATCH_SIZE:
                        ids = await obs_repo.insert_many(buffer)
                        report.observations_inserted += len(ids)
                        buffer.clear()

                # goudengids pads a thin local search with nationwide results, which the
                # postcode filter above then discards. Those pages are the most expensive
                # and least productive requests the scraper makes: machinebouwers fetched
                # 25 pages and 500 cards of which all 500 were out of city. Local results
                # rank first, so a run of pages with nothing local means the useful part
                # is already behind us — and with the WAF tightening from ~120 pages per
                # block to ~11, spending budget on discarded pages is what starves the
                # sectors that would have produced.
                if in_city_this_page == 0:
                    empty_page_streak += 1
                    if empty_page_streak >= max_empty_pages:
                        report.stopped_early = True
                        log.info(
                            "goudengids_left_city_stopping",
                            page=page_num,
                            empty_pages=empty_page_streak,
                            cards_out_of_city=report.cards_out_of_city,
                        )
                        break
                else:
                    empty_page_streak = 0

            if buffer:
                ids = await obs_repo.insert_many(buffer)
                report.observations_inserted += len(ids)
                buffer.clear()

    finally:
        if refresh_matview:
            await pool.execute("SELECT refresh_companies_current()")
        # "Complete" requires proof the listing was actually read: not cut short AND at
        # least one page fetched. pages_scanned only increments after a successful fetch,
        # so a failure that raises out of this function entirely — a DNS outage during
        # warmup, say — leaves it at 0 and cannot be mistaken for coverage. On 2026-08-09
        # and 08-10 exactly that happened: net::ERR_NAME_NOT_RESOLVED on every sector,
        # yet an earlier version of this line still wrote [complete] and retired 25 real
        # sectors that had done no work at all.
        finished_cleanly = not interrupted and report.pages_scanned > 0
        await runs_repo.finish_run(
            run_id,
            jobs_done=report.observations_inserted,
            notes=COMPLETE_MARKER if finished_cleanly else INTERRUPTED_MARKER,
        )

    report.duration_s = time.monotonic() - t0
    log.info(
        "goudengids_ingest_finished",
        pages_scanned=report.pages_scanned,
        cards_found=report.cards_found,
        cards_out_of_city=report.cards_out_of_city,
        observations_inserted=report.observations_inserted,
        placeholders_created=report.placeholders_created,
        duration_s=round(report.duration_s, 2),
    )
    return report
