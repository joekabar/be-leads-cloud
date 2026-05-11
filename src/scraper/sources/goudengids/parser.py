"""Parse goudengids.be / pagesdor.be listing-page HTML into ListingCardRow objects.

Selectors documented in .claude/skills/goudengids-listing/references/selectors.md.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse

import structlog
from bs4 import BeautifulSoup, Tag

logger = structlog.get_logger()


@dataclass(frozen=True, slots=True)
class ListingCardRow:
    name: str
    detail_url: str
    phones: list[str]
    website: str | None
    email: str | None
    address_street: str | None
    address_postal_code: str | None
    address_city: str | None
    description: str | None
    logo_url: str | None
    raw_card_html: str


def _get_attr(tag: Tag, name: str) -> str:
    val = tag.get(name, "")
    if isinstance(val, list):
        return val[0] if val else ""
    return val or ""


def _parse_card(li: Tag, domain: str) -> ListingCardRow | None:
    raw_json = _get_attr(li, "data-small-result")
    if not raw_json:
        return None
    try:
        data: dict[str, str] = json.loads(raw_json)
    except json.JSONDecodeError:
        return None

    name = data.get("title", "").strip()
    if not name:
        return None

    href = data.get("href", "")
    detail_url = href if href.startswith("http") else f"https://www.{domain}{href}"

    # Collect phones: primary from JSON blob first, then tel: dropdown links.
    phones: list[str] = []
    seen: set[str] = set()
    primary = data.get("phone", "").strip()
    if primary:
        phones.append(primary)
        seen.add(primary)
    for a in li.select('a[href^="tel:"]'):
        raw_href = _get_attr(a, "href")
        ph = raw_href.removeprefix("tel:").strip()
        if ph and ph not in seen:
            phones.append(ph)
            seen.add(ph)

    # Website: strip query/fragment from utm_source=fcrmedia link.
    website: str | None = None
    site_tag = li.select_one('a[href*="utm_source=fcrmedia"]')
    if site_tag:
        raw_site = _get_attr(site_tag, "href")
        if raw_site:
            parsed = urlparse(raw_site)
            website = urlunparse(parsed._replace(query="", fragment="")) or None

    # Email (rare on listing cards).
    email: str | None = None
    mail_tag = li.select_one('a[href^="mailto:"]')
    if mail_tag:
        raw_mail = _get_attr(mail_tag, "href")
        if raw_mail.startswith("mailto:"):
            email = raw_mail.removeprefix("mailto:").strip() or None

    # Address via data-yext spans.
    street_tag = li.select_one('span[data-yext="street"]')
    postal_tag = li.select_one('span[data-yext="postal-code"]')
    city_tag = li.select_one('span[data-yext="city"]')

    street = street_tag.get_text(strip=True) or None if street_tag else None
    postal_code = postal_tag.get_text(strip=True) or None if postal_tag else None
    city = city_tag.get_text(strip=True) or None if city_tag else None

    # Short description.
    desc_tag = li.select_one("div.result-item__description")
    description = desc_tag.get_text(strip=True) or None if desc_tag else None

    logo_url = data.get("logo", "").strip() or None

    return ListingCardRow(
        name=name,
        detail_url=detail_url,
        phones=phones,
        website=website,
        email=email,
        address_street=street,
        address_postal_code=postal_code,
        address_city=city,
        description=description,
        logo_url=logo_url,
        raw_card_html=str(li),
    )


def parse_listing_page(html: str, domain: str = "goudengids.be") -> list[ListingCardRow]:
    """Parse all result cards from a listing-page HTML string."""
    soup = BeautifulSoup(html, "lxml")
    cards: list[ListingCardRow] = []
    for li in soup.find_all("li", attrs={"data-small-result": True}):
        if not isinstance(li, Tag):
            continue
        card = _parse_card(li, domain)
        if card is not None:
            cards.append(card)
    return cards


def is_empty_results_page(html: str) -> bool:
    """Return True when the page shows the 'geen resultaten' / 'aucun résultat' empty state."""
    soup = BeautifulSoup(html, "lxml")
    if soup.select_one(".empty-state"):
        return True
    body_text = soup.get_text(" ", strip=True).lower()
    return "geen resultaten" in body_text or "aucun résultat" in body_text
