"""Orchestrate website enrichment for a batch of KBO+URL pairs."""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import structlog

from scraper.db.repositories.observations import ObservationsRepo
from scraper.db.repositories.runs import RunsRepo
from scraper.sources.website.age import estimate_age
from scraper.sources.website.contact_page import find_contact_page
from scraper.sources.website.fetcher import fetch_page
from scraper.sources.website.persons import extract_persons
from scraper.sources.website.structured import extract_jsonld
from scraper.sources.website.transformer import ExtractedSite, site_to_observations

if TYPE_CHECKING:
    from uuid import UUID

    import asyncpg

    from scraper.db.models import Observation
    from scraper.lib.http.client import PoliteClient

logger = structlog.get_logger()

_PHONE_HREF_RE = re.compile(r"tel:([+\d\s\-\.\/]+)", re.IGNORECASE)
# No decimal point: Belgian phone numbers never contain '.'. Decimal matches
# are CSS calc() values, SVG coords, version strings — all noise.
_PHONE_TEXT_RE = re.compile(r"(?:\+32|0032|\+31|0)[0-9 \-\/]{7,14}")
_EMAIL_HREF_RE = re.compile(r"mailto:([^\s?\"]+)", re.IGNORECASE)
_EMAIL_TEXT_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

_NOISE_TAGS = {"script", "style", "svg", "noscript"}


def _visible_text(html: str) -> str:
    """Extract human-visible text, stripping scripts/styles/SVG that contain numeric noise."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    for tag in soup(_NOISE_TAGS):
        tag.decompose()
    return soup.get_text(separator=" ")


def _extract_phones_and_emails(
    html: str,
) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]:
    """Return (phones, emails) as (raw_value, confidence) tuples."""
    phones: list[tuple[str, float]] = []
    seen_phones: set[str] = set()

    emails: list[tuple[str, float]] = []
    seen_emails: set[str] = set()

    # tel: hrefs are intentional links — scan raw HTML.
    for m in _PHONE_HREF_RE.finditer(html):
        raw = m.group(1).strip()
        if raw not in seen_phones:
            seen_phones.add(raw)
            phones.append((raw, 0.85))

    # Text-pattern scan: use visible text only so CSS/SVG/script numeric values
    # (SVG viewBox, calc() dimensions, version strings) don't produce matches.
    text = _visible_text(html)
    for m in _PHONE_TEXT_RE.finditer(text):
        raw = m.group(0).strip()
        if raw not in seen_phones:
            seen_phones.add(raw)
            phones.append((raw, 0.60))

    for m in _EMAIL_HREF_RE.finditer(html):
        raw = m.group(1).strip()
        if raw not in seen_emails:
            seen_emails.add(raw)
            emails.append((raw, 0.85))

    for m in _EMAIL_TEXT_RE.finditer(text):
        raw = m.group(0).strip()
        if raw not in seen_emails:
            seen_emails.add(raw)
            emails.append((raw, 0.50))

    return phones, emails


def _extract_activity_summary(html: str) -> str | None:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")

    for attr_name, attr_val in [
        ("name", "description"),
        ("property", "og:description"),
        ("name", "twitter:description"),
    ]:
        tag = soup.find("meta", attrs={attr_name: attr_val})
        if tag and tag.get("content"):
            text = str(tag["content"]).strip()
            if len(text) > 20:
                return text[:300]

    for container in soup.find_all(["main", "article", "section"]):
        for p in container.find_all("p"):
            text = p.get_text(strip=True)
            if len(text) > 60:
                return text[:300]

    return None


async def _process_company(
    kbo_number: str,
    website_url: str,
    client: PoliteClient,
    run_id: UUID,
    snapshot_at: datetime,
) -> tuple[list[Observation], int]:
    """Fetch + extract one company. Returns (observations, pages_fetched)."""
    log = logger.bind(kbo_number=kbo_number, website=website_url)
    pages_fetched = 0

    try:
        homepage = await fetch_page(client, website_url)
        pages_fetched += 1
    except Exception as exc:
        log.warning("website_fetch_failed", error=str(exc))
        return [], 0

    if homepage.status >= 400:
        log.warning("website_bad_status", status=homepage.status)
        return [], pages_fetched

    structured = extract_jsonld(homepage.html)
    phones, emails = _extract_phones_and_emails(homepage.html)
    activity = _extract_activity_summary(homepage.html)
    age = await estimate_age(homepage.final_url, homepage.html)

    try:
        contact_url = await find_contact_page(client, homepage.final_url, homepage.html)
    except Exception:
        contact_url = None

    all_persons = extract_persons(homepage.html)
    if contact_url and contact_url != homepage.final_url:
        try:
            contact_page = await fetch_page(client, contact_url)
            pages_fetched += 1
            more_persons = extract_persons(contact_page.html)
            seen = {p.name for p in all_persons}
            for p in more_persons:
                if p.name not in seen:
                    all_persons.append(p)
                    seen.add(p.name)
            all_persons = all_persons[:4]
        except Exception as exc:
            log.debug("website_contact_page_fetch_failed", error=str(exc))

    extracted = ExtractedSite(
        url=homepage.final_url,
        structured=structured,
        contact_page_url=contact_url,
        persons=all_persons,
        activity_summary=activity,
        website_age=age,
        phones_found=phones,
        emails_found=emails,
    )

    obs = site_to_observations(kbo_number, extracted, run_id, snapshot_at)
    return obs, pages_fetched


@dataclass
class WebsiteReport:
    kbos_processed: int = 0
    pages_fetched: int = 0
    observations_inserted: int = 0
    fetch_failures: int = 0
    duration_s: float = 0.0


async def _recent_website_kbos(pool: asyncpg.Pool, cutoff: datetime) -> set[str]:
    rows = await pool.fetch(
        "SELECT DISTINCT kbo_number FROM observations "
        "WHERE source = 'website' AND observed_at > $1",
        cutoff,
    )
    return {r["kbo_number"] for r in rows}


async def ingest_kbos(
    kbo_website_pairs: list[tuple[str, str]],
    pool: asyncpg.Pool,
    polite_client: PoliteClient,
    *,
    skip_recent_hours: int = 168,
    concurrent_companies: int = 15,
) -> WebsiteReport:
    """Enrich a batch of KBO+URL pairs with website data."""
    t0 = time.monotonic()
    report = WebsiteReport()

    runs_repo = RunsRepo(pool)
    obs_repo = ObservationsRepo(pool)

    run_id = await runs_repo.start_run(source="website")
    snapshot_at = datetime.now(tz=UTC)
    log = logger.bind(run_id=str(run_id), source="website")

    recent_kbos: set[str] = set()
    if skip_recent_hours > 0:
        cutoff = snapshot_at - timedelta(hours=skip_recent_hours)
        recent_kbos = await _recent_website_kbos(pool, cutoff)

    pairs_to_process = [(kbo, url) for kbo, url in kbo_website_pairs if kbo not in recent_kbos]

    log.info(
        "website_ingest_started",
        total=len(kbo_website_pairs),
        skipped_recent=len(kbo_website_pairs) - len(pairs_to_process),
        to_process=len(pairs_to_process),
    )

    sem = asyncio.Semaphore(concurrent_companies)
    all_obs: list[Observation] = []

    async def _task(kbo: str, url: str) -> None:
        async with sem:
            result_obs, pages = await _process_company(kbo, url, polite_client, run_id, snapshot_at)
            report.pages_fetched += pages
            if not result_obs:
                report.fetch_failures += 1
            else:
                all_obs.extend(result_obs)
            report.kbos_processed += 1

    try:
        async with asyncio.TaskGroup() as tg:
            for kbo, url in pairs_to_process:
                tg.create_task(_task(kbo, url))

        if all_obs:
            ids = await obs_repo.insert_many(all_obs)
            report.observations_inserted = len(ids)

    finally:
        await pool.execute("SELECT refresh_companies_current()")
        await runs_repo.finish_run(
            run_id,
            jobs_done=report.observations_inserted,
            jobs_failed=report.fetch_failures,
        )

    report.duration_s = time.monotonic() - t0
    log.info(
        "website_ingest_finished",
        kbos_processed=report.kbos_processed,
        pages_fetched=report.pages_fetched,
        observations_inserted=report.observations_inserted,
        fetch_failures=report.fetch_failures,
        duration_s=round(report.duration_s, 2),
    )
    return report
