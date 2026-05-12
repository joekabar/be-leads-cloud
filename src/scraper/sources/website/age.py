"""Estimate website age via WHOIS and footer-year heuristics."""

from __future__ import annotations

import asyncio
import re
from urllib.parse import urlparse

import structlog

logger = structlog.get_logger()

try:
    import whois as _whois_lib  # type: ignore[import-untyped]

    _WHOIS_AVAILABLE = True
except ImportError:
    _whois_lib = None
    _WHOIS_AVAILABLE = False
    logger.warning("python-whois not installed; WHOIS age estimation disabled")


def _footer_year(html: str) -> str | None:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    footer = soup.find("footer")
    text = (footer or soup).get_text()[-1000:]
    # Collect all 4-digit years mentioned near the copyright symbol or anywhere in the footer.
    years = re.findall(r"\b(20\d{2})\b", text)
    return max(years) if years else None


async def estimate_age(url: str, html: str | None = None) -> tuple[str | None, str]:
    """Return (year_4char_or_None, source_label).

    source_label ∈ {"whois", "footer", "none"}.
    """
    if _WHOIS_AVAILABLE:
        try:
            domain = urlparse(url).netloc.removeprefix("www.")
            w = await asyncio.to_thread(_whois_lib.whois, domain)
            cd = w.creation_date
            if isinstance(cd, list):
                cd = cd[0]
            if cd is not None:
                year = str(cd)[:4]
                if year.isdigit() and len(year) == 4:
                    return year, "whois"
        except Exception:
            logger.debug("whois_lookup_failed", url=url)

    if html is not None:
        footer_year = _footer_year(html)
        if footer_year is not None:
            return footer_year, "footer"

    return None, "none"
