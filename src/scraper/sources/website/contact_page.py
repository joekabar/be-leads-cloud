"""Discover and return the URL of a company's contact/team page."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlparse

import structlog
from bs4 import BeautifulSoup

if TYPE_CHECKING:
    from scraper.lib.http.client import PoliteClient

logger = structlog.get_logger()

_CONTACT_KEYWORDS = re.compile(
    r"contact|team|over-ons|about|medewerkers|wie-zijn-we|notre-equipe|nous-contacter",
    re.IGNORECASE,
)

_PROBE_PATHS = [
    "/contact",
    "/contact-us",
    "/team",
    "/over-ons",
    "/about",
    "/medewerkers",
    "/wie-zijn-we",
    "/notre-equipe",
]


def _base_url(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


async def find_contact_page(
    client: PoliteClient,
    homepage_url: str,
    homepage_html: str,
) -> str | None:
    """Return the absolute URL of a contact/team page, or None.

    Scans homepage links first; if none found, probes well-known paths via HEAD.
    """
    soup = BeautifulSoup(homepage_html, "lxml")
    base = _base_url(homepage_url)

    for a in soup.find_all("a", href=True):
        href = str(a["href"])
        if _CONTACT_KEYWORDS.search(href):
            absolute = urljoin(homepage_url, href)
            if urlparse(absolute).netloc == urlparse(homepage_url).netloc:
                return absolute

    for path in _PROBE_PATHS:
        candidate = base + path
        try:
            resp = await client._request("HEAD", candidate)
            if resp.status_code == 200:
                return candidate
        except Exception:
            logger.debug("website_contact_probe_failed", url=candidate)

    return None
