"""Parse raw Brave JSON / DDG list-of-dicts into typed SearchResult objects."""

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass
from typing import Any, Literal

import structlog

logger = structlog.get_logger()


@dataclass(frozen=True, slots=True)
class SearchResult:
    title: str
    url: str
    domain: str  # netloc lowercased, www. stripped
    language: str | None
    engine: Literal["brave", "ddg"]


def _parse_domain(url: str) -> str:
    netloc = urllib.parse.urlparse(url).netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc


def parse_brave(payload: dict[str, Any]) -> list[SearchResult]:
    """Walk the Brave JSON payload and return one SearchResult per organic result."""
    web = payload.get("web")
    if not isinstance(web, dict):
        logger.warning("brave_payload_missing_web_key")
        return []
    raw_results = web.get("results", [])
    if not isinstance(raw_results, list):
        return []

    out: list[SearchResult] = []
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url", ""))
        if not url:
            continue
        out.append(
            SearchResult(
                title=str(item.get("title", "")),
                url=url,
                domain=_parse_domain(url),
                language=item.get("language") or None,
                engine="brave",
            )
        )
    return out


def parse_ddg(results: list[dict[str, str]]) -> list[SearchResult]:
    """Convert ddgs.DDGS.text() output into SearchResult objects."""
    out: list[SearchResult] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        url = str(item.get("href", ""))
        if not url:
            continue
        out.append(
            SearchResult(
                title=str(item.get("title", "")),
                url=url,
                domain=_parse_domain(url),
                language=None,
                engine="ddg",
            )
        )
    return out
