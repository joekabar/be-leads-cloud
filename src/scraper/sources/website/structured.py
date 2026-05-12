"""Extract JSON-LD structured data from a webpage."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

_ACCEPTED_TYPES: frozenset[str] = frozenset(
    {
        "LocalBusiness",
        "Organization",
        "ProfessionalService",
        "Store",
        "Restaurant",
        "GeneralContractor",
        "HomeAndConstructionBusiness",
        "ElectricalContractor",
        "Plumber",
        "MedicalBusiness",
        "LegalService",
        "FinancialService",
        "AccountingService",
        "AutoRepair",
        "BeautySalon",
        "HealthAndBeautyBusiness",
        "FoodEstablishment",
        "LodgingBusiness",
        "SportsActivityLocation",
        "EntertainmentBusiness",
        "ChildCare",
        "DryCleaningOrLaundry",
        "EmergencyService",
        "GovernmentOffice",
        "Library",
        "TouristInformationCenter",
        "TravelAgency",
    }
)

_TYPE_RE = re.compile(r"schema\.org/(.+)$")


def _bare_type(type_val: str) -> str:
    """Strip schema.org/ prefix if present."""
    m = _TYPE_RE.search(type_val)
    return m.group(1) if m else type_val


def _as_list(val: object) -> list[str]:
    if val is None:
        return []
    if isinstance(val, str):
        return [val]
    if isinstance(val, list):
        return [str(v) for v in val if v]
    return [str(val)]


def _flatten_address(addr: object) -> dict[str, str]:
    if not isinstance(addr, dict):
        return {}
    return {
        "streetAddress": str(addr.get("streetAddress", "")),
        "postalCode": str(addr.get("postalCode", "")),
        "addressLocality": str(addr.get("addressLocality", "")),
        "addressCountry": str(addr.get("addressCountry", "")),
    }


def _flatten_opening_hours(oh: object) -> list[str]:
    if oh is None:
        return []
    if isinstance(oh, str):
        return [oh]
    if isinstance(oh, list):
        result: list[str] = []
        for item in oh:
            if isinstance(item, str):
                result.append(item)
            elif isinstance(item, dict):
                # openingHoursSpecification
                day_of_week = item.get("dayOfWeek", "")
                opens = item.get("opens", "")
                closes = item.get("closes", "")
                if day_of_week and opens and closes:
                    days = day_of_week if isinstance(day_of_week, str) else ",".join(day_of_week)
                    result.append(f"{days} {opens}-{closes}")
        return result
    return []


def _extract_person_names(persons: object) -> list[str]:
    if persons is None:
        return []
    if isinstance(persons, dict):
        persons = [persons]
    if not isinstance(persons, list):
        return []
    names: list[str] = []
    for p in persons:
        if isinstance(p, dict):
            name = p.get("name")
            if name and isinstance(name, str):
                names.append(name)
    return names


@dataclass(frozen=True, slots=True)
class JsonLdData:
    type: str
    name: str | None
    telephones: list[str]
    emails: list[str]
    addresses: list[dict[str, str]]
    description: str | None
    opening_hours: list[str]
    same_as: list[str]
    founders: list[str]
    employees: list[str]


def _parse_object(obj: dict[str, object]) -> JsonLdData | None:
    raw_type = obj.get("@type", "")
    if isinstance(raw_type, list):
        types = [_bare_type(str(t)) for t in raw_type]
    else:
        types = [_bare_type(str(raw_type))]

    matched_type = next((t for t in types if t in _ACCEPTED_TYPES), None)
    if matched_type is None:
        return None

    raw_addr = obj.get("address")
    if isinstance(raw_addr, list):
        addresses = [_flatten_address(a) for a in raw_addr if isinstance(a, dict)]
    elif isinstance(raw_addr, dict):
        addresses = [_flatten_address(raw_addr)]
    else:
        addresses = []

    desc = obj.get("description")
    name = obj.get("name")

    return JsonLdData(
        type=matched_type,
        name=str(name) if name else None,
        telephones=_as_list(obj.get("telephone")),
        emails=_as_list(obj.get("email")),
        addresses=addresses,
        description=str(desc) if desc else None,
        opening_hours=_flatten_opening_hours(
            obj.get("openingHours") or obj.get("openingHoursSpecification")
        ),
        same_as=_as_list(obj.get("sameAs")),
        founders=_extract_person_names(obj.get("founder")),
        employees=_extract_person_names(obj.get("employee")),
    )


def _flatten_graph(obj: object) -> list[dict[str, object]]:
    """Flatten top-level object, list, or @graph into a list of objects."""
    if isinstance(obj, dict):
        graph = obj.get("@graph")
        if isinstance(graph, list):
            return [item for item in graph if isinstance(item, dict)]
        return [obj]
    if isinstance(obj, list):
        result: list[dict[str, object]] = []
        for item in obj:
            result.extend(_flatten_graph(item))
        return result
    return []


def extract_jsonld(html: str) -> list[JsonLdData]:
    """Parse all JSON-LD scripts from HTML and return structured data for accepted types."""
    soup = BeautifulSoup(html, "lxml")
    results: list[JsonLdData] = []

    for script in soup.find_all("script", {"type": "application/ld+json"}):
        text = script.string
        if not text:
            continue
        try:
            raw = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            continue
        for obj in _flatten_graph(raw):
            parsed = _parse_object(obj)
            if parsed is not None:
                results.append(parsed)

    return results
