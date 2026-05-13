"""Classify SearchResult URLs into official_website | directory | social | news | other."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlparse

if TYPE_CHECKING:
    from scraper.sources.ddg_brave.parser import SearchResult

_LEGAL_FORMS: frozenset[str] = frozenset(
    {
        "bv",
        "nv",
        "sa",
        "sprl",
        "srl",
        "bvba",
        "cvba",
        "scrl",
        "commv",
        "cv",
        "vzw",
        "asbl",
    }
)

DIRECTORY_DOMAINS: frozenset[str] = frozenset(
    {
        "goudengids",
        "pagesdor",
        "goldenpages",
        "kbo",
        "kompass",
        "europages",
        "trustlocal",
        "companyweb",
        "bizzy",
        "trendstop",
        "opencorporates",
        "dnb",
        "theorg",
        "freightnet",
        "panjiva",
        "exporthub",
        "b2bhint",
        "namesdir",
        "radaris",
        "cybo",
        "marketinsider",
        "glassdoor",
        "indeed",
    }
)

SOCIAL_DOMAINS: frozenset[str] = frozenset(
    {
        "facebook",
        "linkedin",
        "instagram",
        "twitter",
        "x",
        "youtube",
        "tiktok",
        "pinterest",
        "vimeo",
        "foursquare",
        "snapchat",
    }
)

NEWS_DOMAINS: frozenset[str] = frozenset(
    {
        "vrt",
        "hln",
        "demorgen",
        "standaard",
        "tijd",
        "knack",
        "lalibre",
        "lesoir",
        "rtbf",
        "sudinfo",
    }
)

_NEWS_PATH_FRAGMENTS: tuple[str, ...] = ("/article/", "/nieuws/", "/actualite/")

_NON_ALNUM = re.compile(r"[^a-z0-9]")


@dataclass(frozen=True, slots=True)
class ClassifiedResult:
    result: SearchResult
    bucket: Literal["official_website", "directory", "social", "news", "other"]


def normalize_name(name: str) -> str:
    """Normalise a company name to an alphanumeric slug for domain matching."""
    if not name:
        raise ValueError("company name must not be empty")
    nfkd = unicodedata.normalize("NFD", name)
    ascii_str = nfkd.encode("ascii", "ignore").decode("ascii")
    lower = ascii_str.lower()
    words = re.split(r"\W+", lower)
    filtered = [w for w in words if w and w not in _LEGAL_FORMS]
    return _NON_ALNUM.sub("", "".join(filtered))


def _domain_labels(domain: str) -> list[str]:
    return domain.split(".")


def _matches_known(domain: str, known: frozenset[str]) -> bool:
    return any(label in known for label in _domain_labels(domain))


def _domain_stem_normalized(domain: str) -> str:
    """Return normalised stem: domain without TLD, dashes/dots stripped."""
    parts = domain.split(".")
    if len(parts) < 2:
        return _NON_ALNUM.sub("", domain.lower())
    stem = ".".join(parts[:-1])
    return _NON_ALNUM.sub("", stem.lower())


def _domain_tld(domain: str) -> str:
    parts = domain.split(".")
    return parts[-1].lower() if len(parts) >= 2 else ""


def _is_official(domain: str, normalized_company: str) -> bool:
    if not normalized_company:
        return False
    stem = _domain_stem_normalized(domain)
    if not stem:
        return False
    if stem == normalized_company:
        return True
    return _domain_tld(domain) == "be" and normalized_company in stem


def classify(result: SearchResult, company_name: str) -> ClassifiedResult:
    """Assign a bucket to a SearchResult for the given company name."""
    if not company_name:
        raise ValueError("company_name must not be empty")

    domain = result.domain

    if _matches_known(domain, SOCIAL_DOMAINS):
        return ClassifiedResult(result=result, bucket="social")

    if _matches_known(domain, DIRECTORY_DOMAINS):
        return ClassifiedResult(result=result, bucket="directory")

    if _matches_known(domain, NEWS_DOMAINS):
        return ClassifiedResult(result=result, bucket="news")

    path = urlparse(result.url).path.lower()
    if any(frag in path for frag in _NEWS_PATH_FRAGMENTS):
        return ClassifiedResult(result=result, bucket="news")

    normalized = normalize_name(company_name)
    if _is_official(domain, normalized):
        return ClassifiedResult(result=result, bucket="official_website")

    return ClassifiedResult(result=result, bucket="other")
