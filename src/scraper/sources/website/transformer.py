"""Transform an ExtractedSite into a list of Observations."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from scraper.db.models import Observation
from scraper.lib.validators.phone import InvalidPhoneError, validate_phone

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from scraper.sources.website.persons import ContactPerson
    from scraper.sources.website.structured import JsonLdData

logger = structlog.get_logger()

_SOURCE = "website"

_ROLE_EMAIL_RE = re.compile(
    r"^(info|contact|sales|hello|support|admin|office|hallo|bonjour|algemeen|service)@",
    re.IGNORECASE,
)

# NL stopwords — simple heuristic for lang_hint
_NL_WORDS = frozenset(["de", "het", "een", "en", "van", "in", "is", "op", "voor", "met"])
_FR_WORDS = frozenset(["le", "la", "les", "un", "une", "et", "de", "du", "en", "pour"])


def _lang_hint(text: str) -> str | None:
    words = set(text.lower().split())
    nl_hits = len(words & _NL_WORDS)
    fr_hits = len(words & _FR_WORDS)
    if nl_hits == 0 and fr_hits == 0:
        return None
    if nl_hits > fr_hits:
        return "nl"
    if fr_hits > nl_hits:
        return "fr"
    return None


@dataclass
class ExtractedSite:
    url: str
    structured: list[JsonLdData]
    contact_page_url: str | None
    persons: list[ContactPerson]
    activity_summary: str | None
    website_age: tuple[str | None, str]
    phones_found: list[tuple[str, float]]
    emails_found: list[tuple[str, float]]


def site_to_observations(
    kbo_number: str,
    extracted: ExtractedSite,
    run_id: UUID,
    snapshot_at: datetime,
) -> list[Observation]:
    """Emit observations from an extracted website.

    Each phone, email, address, person, activity summary, and website age becomes its
    own observation.  Confidence values per extraction-priorities.md.
    """
    obs: list[Observation] = []

    for entity in extracted.structured:
        source_url = extracted.url

        for phone_raw in entity.telephones:
            _try_add_phone(obs, kbo_number, phone_raw, run_id, snapshot_at, source_url, 1.00)

        for email_raw in entity.emails:
            _add_email(obs, kbo_number, email_raw, run_id, snapshot_at, source_url, 1.00)

        for addr in entity.addresses:
            street = addr.get("streetAddress", "").strip()
            if not street:
                continue
            obs.append(
                Observation(
                    kbo_number=kbo_number,
                    field="address",
                    value={
                        "street": street,
                        "postal_code": addr.get("postalCode", "").strip(),
                        "city": addr.get("addressLocality", "").strip(),
                        "country": addr.get("addressCountry", "").strip() or "BE",
                    },
                    raw_value=street,
                    source=_SOURCE,
                    source_url=source_url,
                    observed_at=snapshot_at,
                    confidence=0.90,
                    run_id=run_id,
                )
            )

    # Phones discovered via heuristic (href="tel:" or text scan)
    for phone_raw, conf in extracted.phones_found:
        _try_add_phone(obs, kbo_number, phone_raw, run_id, snapshot_at, extracted.url, conf)

    # Emails discovered via heuristic
    for email_raw, conf in extracted.emails_found:
        _add_email(obs, kbo_number, email_raw, run_id, snapshot_at, extracted.url, conf)

    # Contact persons
    contact_src_url = extracted.contact_page_url or extracted.url
    for person in extracted.persons:
        confidence = 0.85 if person.source == "microdata" else 0.55
        obs.append(
            Observation(
                kbo_number=kbo_number,
                field="function_holder",
                value={
                    "name": person.name,
                    "role": person.role,
                    "role_canonical": "contact" if person.source == "heuristic" else None,
                    "since": None,
                },
                raw_value=person.name,
                source=_SOURCE,
                source_url=contact_src_url,
                observed_at=snapshot_at,
                confidence=confidence,
                run_id=run_id,
            )
        )

    # Activity summary
    if extracted.activity_summary:
        obs.append(
            Observation(
                kbo_number=kbo_number,
                field="activity_summary",
                value={
                    "text": extracted.activity_summary,
                    "lang_hint": _lang_hint(extracted.activity_summary),
                },
                raw_value=extracted.activity_summary,
                source=_SOURCE,
                source_url=extracted.url,
                observed_at=snapshot_at,
                confidence=0.80,
                run_id=run_id,
            )
        )

    # Website age
    year, age_source = extracted.website_age
    if year is not None:
        age_confidence = 1.00 if age_source == "whois" else 0.70
        obs.append(
            Observation(
                kbo_number=kbo_number,
                field="website_age",
                value={"year": year, "method": age_source},
                raw_value=year,
                source=_SOURCE,
                source_url=extracted.url,
                observed_at=snapshot_at,
                confidence=age_confidence,
                run_id=run_id,
            )
        )

    return obs


def _try_add_phone(
    obs: list[Observation],
    kbo_number: str,
    phone_raw: str,
    run_id: UUID,
    snapshot_at: datetime,
    source_url: str | None,
    confidence: float,
) -> None:
    try:
        validated = validate_phone(phone_raw)
    except InvalidPhoneError:
        logger.warning("website_invalid_phone_skipped", phone=phone_raw)
        return
    obs.append(
        Observation(
            kbo_number=kbo_number,
            field="phone",
            value=validated.model_dump(),
            raw_value=phone_raw,
            source=_SOURCE,
            source_url=source_url,
            observed_at=snapshot_at,
            confidence=confidence,
            run_id=run_id,
        )
    )


def _add_email(
    obs: list[Observation],
    kbo_number: str,
    email_raw: str,
    run_id: UUID,
    snapshot_at: datetime,
    source_url: str | None,
    confidence: float,
) -> None:
    is_role = bool(_ROLE_EMAIL_RE.match(email_raw))
    obs.append(
        Observation(
            kbo_number=kbo_number,
            field="email",
            value={"address": email_raw, "is_role_account": is_role},
            raw_value=email_raw,
            source=_SOURCE,
            source_url=source_url,
            observed_at=snapshot_at,
            confidence=confidence,
            run_id=run_id,
        )
    )
