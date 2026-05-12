"""Extract contact persons from a webpage via microdata or role-keyword heuristics."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from bs4 import BeautifulSoup

_ROLE_KEYWORDS = re.compile(
    r"\b(zaakvoerder|ceo|directeur|manager|sales|contact|verantwoordelijke"
    r"|g[eé]rant|director|founder|oprichter|responsable)\b",
    re.IGNORECASE,
)

_NAME_RE = re.compile(r"\b[A-ZÁÉÍÓÚÀÈÙÂÊÎÔÛÄËÏÖÜ][a-záéíóú]+\s[A-ZÁÉÍÓÚ][a-záéíóú]+\b")

_MAX_PERSONS = 4


@dataclass(frozen=True, slots=True)
class ContactPerson:
    name: str
    role: str | None
    source: Literal["microdata", "heuristic"]


def _microdata_persons(soup: BeautifulSoup) -> list[ContactPerson]:
    persons: list[ContactPerson] = []
    person_type_re = re.compile(r"Person", re.IGNORECASE)
    for block in soup.find_all(attrs={"itemtype": person_type_re}):
        name_tag = block.find(attrs={"itemprop": "name"})
        if not name_tag:
            continue
        name = name_tag.get_text(strip=True)
        if not name:
            continue
        role_tag = block.find(attrs={"itemprop": "jobTitle"})
        role = role_tag.get_text(strip=True) if role_tag else None
        persons.append(ContactPerson(name=name, role=role or None, source="microdata"))
    return persons


def _heuristic_persons(soup: BeautifulSoup) -> list[ContactPerson]:
    persons: list[ContactPerson] = []
    seen: set[str] = set()

    candidates = soup.find_all(["h1", "h2", "h3", "h4", "p", "span"])
    for tag in candidates:
        text = tag.get_text(separator=" ", strip=True)
        role_match = _ROLE_KEYWORDS.search(text.lower())
        if not role_match:
            continue
        role = role_match.group(1)
        names = _NAME_RE.findall(text)
        if not names:
            # try next sibling
            sib = tag.find_next_sibling()
            if sib:
                names = _NAME_RE.findall(sib.get_text(separator=" ", strip=True))
        for name in names:
            if name not in seen:
                seen.add(name)
                persons.append(ContactPerson(name=name, role=role, source="heuristic"))

    return persons


def extract_persons(html: str) -> list[ContactPerson]:
    """Up to 4 contact persons via microdata (preferred) or role-keyword heuristic."""
    soup = BeautifulSoup(html, "lxml")
    persons = _microdata_persons(soup)
    if not persons:
        persons = _heuristic_persons(soup)

    seen_names: dict[str, ContactPerson] = {}
    for p in persons:
        if p.name not in seen_names:
            seen_names[p.name] = p

    return list(seen_names.values())[:_MAX_PERSONS]
