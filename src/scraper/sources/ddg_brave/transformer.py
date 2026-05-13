"""Transform classified search results into Observation list."""

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import urlparse

from scraper.db.models import Observation

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from scraper.sources.ddg_brave.classifier import ClassifiedResult

_CONFIDENCE: dict[str, float] = {"brave": 0.55, "ddg": 0.50}


@dataclass(frozen=True, slots=True)
class SearchCrossValidation:
    query: str
    engine: Literal["brave", "ddg"]
    official_websites: list[str]
    directory_hits: list[str]
    social_links: list[str]
    news_mentions: int
    total_results: int
    snapshot_at: str  # ISO string


def _search_source_url(engine: Literal["brave", "ddg"], query: str) -> str:
    quoted = urllib.parse.quote(query)
    if engine == "brave":
        return f"https://api.search.brave.com/res/v1/web/search?q={quoted}"
    return f"https://duckduckgo.com/?q={quoted}"


def _pick_best_official(urls: list[str]) -> str | None:
    if not urls:
        return None

    def _sort_key(url: str) -> tuple[int, int, int]:
        netloc = urlparse(url).netloc.lower()
        tld_pref = 0 if netloc.endswith(".be") else 1
        scheme_pref = 0 if url.startswith("https") else 1
        return (tld_pref, len(netloc), scheme_pref)

    return sorted(urls, key=_sort_key)[0]


def query_to_observations(
    kbo_number: str,
    company_name: str,
    query: str,
    engine: Literal["brave", "ddg"],
    results: list[ClassifiedResult],
    run_id: UUID,
    snapshot_at: datetime,
) -> list[Observation]:
    """Convert classified search results into Observation rows.

    Emits:
    - One ``website`` observation per distinct official_website URL.
    - One ``cross_validation`` observation summarising the full result set.
    """
    confidence = _CONFIDENCE[engine]
    source_url = _search_source_url(engine, query)

    official_urls: list[str] = []
    directory_hits: list[str] = []
    social_links: list[str] = []
    news_mentions = 0
    seen_urls: set[str] = set()

    for cr in results:
        url = cr.result.url
        if cr.bucket == "official_website":
            if url not in seen_urls:
                official_urls.append(url)
                seen_urls.add(url)
        elif cr.bucket == "directory":
            if url not in seen_urls:
                directory_hits.append(url)
                seen_urls.add(url)
        elif cr.bucket == "social":
            social_links.append(url)
        elif cr.bucket == "news":
            news_mentions += 1

    obs: list[Observation] = []

    for url in official_urls:
        parsed = urlparse(url)
        tld = parsed.netloc.rsplit(".", 1)[-1] if parsed.netloc else ""
        obs.append(
            Observation(
                kbo_number=kbo_number,
                field="website",
                value={
                    "url": url,
                    "tld": tld,
                    "via_search": True,
                    "search_engine": engine,
                },
                raw_value=url,
                source=engine,
                source_url=source_url,
                observed_at=snapshot_at,
                confidence=confidence,
                run_id=run_id,
            )
        )

    summary: dict[str, Any] = {
        "query": query,
        "engine": engine,
        "total_results": len(results),
        "official_websites_count": len(official_urls),
        "directory_hits_count": len(directory_hits),
        "social_links_count": len(social_links),
        "news_mentions": news_mentions,
        "first_official_website": _pick_best_official(official_urls),
        "snapshot_at": snapshot_at.isoformat(),
    }
    obs.append(
        Observation(
            kbo_number=kbo_number,
            field="cross_validation",
            value=summary,
            raw_value=query,
            source=engine,
            source_url=source_url,
            observed_at=snapshot_at,
            confidence=confidence,
            run_id=run_id,
        )
    )

    return obs
