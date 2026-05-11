"""Parse kbopub detail-page HTML to extract function holders.

If kbopub redesigns its detail page, this is the file to update.
See tests/golden/kbopub_html/ for the HTML fixtures that drive these selectors.

Page section structure (NL):
  <tr><td class="I" colspan="4"><h2>Functies</h2></td></tr>
  <tr>
    <td class="QL">Bestuurder</td>
    <td class="QL">Boonen, Jan</td>
    <td class="QL"><span class="upd">Sinds 27 maart 2024</span></td>
  </tr>
The Functies block ends at the next <tr> that contains a <td class="I">, or at </table>.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Literal

import structlog
from bs4 import BeautifulSoup, Tag

logger = structlog.get_logger()

# Month names used in date strings on kbopub pages (NL and FR merged — no name collisions).
_MONTHS: dict[str, int] = {
    # Dutch
    "januari": 1,
    "februari": 2,
    "maart": 3,
    "april": 4,
    "mei": 5,
    "juni": 6,
    "juli": 7,
    "augustus": 8,
    "september": 9,
    "oktober": 10,
    "november": 11,
    "december": 12,
    # French
    "janvier": 1,
    "février": 2,
    "mars": 3,
    "avril": 4,
    "mai": 5,
    "juin": 6,
    "juillet": 7,
    "août": 8,
    "septembre": 9,
    "octobre": 10,
    "novembre": 11,
    "décembre": 12,
}

# Date-string prefixes to strip ("Sinds DD maand YYYY" / "Depuis DD mois YYYY").
_SINCE_PREFIXES = ("sinds ", "depuis ")

# Mapping from raw role label (NL or FR) to canonical English slug.
_ROLE_MAP: dict[str, str] = {
    # NL
    "Bestuurder": "director",
    "Gedelegeerd bestuurder": "managing_director",
    "Zaakvoerder": "manager",
    "Vaste vertegenwoordiger": "permanent_representative",
    "Voorzitter": "chairman",
    "Ondervoorzitter": "vice_chairman",
    "Algemeen directeur": "general_director",
    "CEO": "ceo",
    "CFO": "cfo",
    "COO": "coo",
    "Vereffenaar": "liquidator",
    "Commissaris": "auditor",
    # FR
    "Administrateur": "director",
    "Administrateur délégué": "managing_director",
    "Gérant": "manager",
    "Représentant permanent": "permanent_representative",
    "Président": "chairman",
    "Vice-président": "vice_chairman",
    "Directeur général": "general_director",
    "Liquidateur": "liquidator",
    "Commissaire": "auditor",
}

# Legal-form suffixes that mark a name as a legal person.
_LEGAL_FORM_SUFFIXES = frozenset(
    {"BV", "NV", "SRL", "SA", "BVBA", "SPRL", "CVBA", "SCRL", "VZW", "ASBL"}
)

# Detect embedded KBO reference: "met KBO 0123456789" / "avec BCE 0123456789" / bare 10 digits.
_LINKED_KBO_RE = re.compile(
    r"(?:met KBO|avec BCE)\s+([\d.]+)"
    r"|(?<!\d)(\d{10})(?!\d)"
)


@dataclass(frozen=True, slots=True)
class FunctionHolderRow:
    role: str
    role_canonical: str
    name: str
    is_legal_person: bool
    linked_kbo: str | None
    since: date | None
    raw_html: str


def detect_lang(html: str) -> Literal["nl", "fr"]:
    """Detect page language by looking for the NL or FR page title h1."""
    if "Données de l" in html or 'lang="fr"' in html or "Fonctions" in html:
        return "fr"
    return "nl"


def _parse_since(text: str) -> date | None:
    """Parse 'Sinds 27 maart 2024' or 'Depuis 10 février 2019' → date. Returns None on failure."""
    lower = text.strip().lower()
    for prefix in _SINCE_PREFIXES:
        if lower.startswith(prefix):
            lower = lower[len(prefix) :]
            break

    parts = lower.split()
    if len(parts) != 3:
        return None
    try:
        day = int(parts[0])
        year = int(parts[2])
    except ValueError:
        return None
    month = _MONTHS.get(parts[1])
    if month is None:
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _detect_legal_person(name: str) -> tuple[bool, str | None]:
    """Return (is_legal_person, linked_kbo_or_None) for a function-holder name string."""
    m = _LINKED_KBO_RE.search(name)
    if m:
        raw = (m.group(1) or m.group(2) or "").replace(".", "").replace(" ", "")
        return True, raw if len(raw) == 10 else None

    words = name.split()
    if words and words[-1].upper() in _LEGAL_FORM_SUFFIXES:
        return True, None

    return False, None


def parse_function_holders(html: str) -> list[FunctionHolderRow]:
    """Parse function-holder rows from a kbopub detail-page HTML string.

    Returns an empty list if the Functies/Fonctions section is absent or empty.
    Unknown role labels are kept verbatim and logged as warnings.
    """
    soup = BeautifulSoup(html, "lxml")

    # Find the section header <h2>. BeautifulSoup's typed overloads don't allow
    # name + string together, so we iterate find_all("h2") and filter by text.
    h2 = next(
        (
            tag
            for tag in soup.find_all("h2")
            if isinstance(tag, Tag) and tag.get_text(strip=True) in ("Functies", "Fonctions")
        ),
        None,
    )
    if h2 is None:
        return []

    section_tr = h2.find_parent("tr")
    if section_tr is None or not isinstance(section_tr, Tag):
        return []

    rows: list[FunctionHolderRow] = []
    for sibling in section_tr.next_siblings:
        if not isinstance(sibling, Tag) or sibling.name != "tr":
            continue
        # Stop at next section header (any <tr> whose <td class="I"> child contains an <h2>).
        if sibling.find("td", class_="I"):
            break

        tds = sibling.find_all("td")
        if len(tds) < 2:
            continue

        role_text = tds[0].get_text(strip=True)
        if not role_text:
            continue

        canonical = _ROLE_MAP.get(role_text)
        if canonical is None:
            logger.warning("unknown_role_label", role=role_text)
            canonical = role_text

        name = tds[1].get_text(strip=True)
        since: date | None = None
        if len(tds) >= 3:
            span = tds[2].find("span", class_="upd")
            if span:
                since = _parse_since(span.get_text(strip=True))

        is_legal, linked_kbo = _detect_legal_person(name)

        rows.append(
            FunctionHolderRow(
                role=role_text,
                role_canonical=canonical,
                name=name,
                is_legal_person=is_legal,
                linked_kbo=linked_kbo,
                since=since,
                raw_html=str(sibling),
            )
        )

    return rows
