from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlparse

import structlog

from scraper.db.models import Observation
from scraper.lib.validators.phone import InvalidPhoneError, validate_phone

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from scraper.sources.kbo_dump.parser import (
        ActivityRow,
        AddressRow,
        ContactRow,
        DenominationRow,
        EnterpriseRow,
    )

logger = structlog.get_logger()

_ROLE_ACCOUNTS = frozenset(
    {
        "info",
        "contact",
        "support",
        "admin",
        "sales",
        "service",
        "help",
        "noreply",
        "no-reply",
        "webmaster",
        "postmaster",
        "helpdesk",
        "billing",
        "abuse",
    }
)

_LANG_MAP: dict[str, str] = {"NL": "nl", "FR": "fr", "DE": "de", "EN": "en"}

_DENOM_CONFIDENCE: dict[str, float] = {
    "001": 1.00,
    "002": 0.90,
    "003": 0.95,
}

_DENOM_TYPE: dict[str, str] = {
    "002": "abbreviation",
    "003": "commercial",
}


def enterprise_to_observations(
    row: EnterpriseRow, run_id: UUID, observed_at: datetime
) -> list[Observation]:
    """Produce founding_date and status observations from one enterprise row."""
    obs: list[Observation] = []
    try:
        if row.start_date is not None:
            obs.append(
                Observation(
                    kbo_number=row.enterprise_number,
                    field="founding_date",
                    value={"iso": row.start_date.isoformat()},
                    raw_value=row.start_date.strftime("%d-%m-%Y"),
                    source="kbo_dump",
                    observed_at=observed_at,
                    confidence=1.00,
                    run_id=run_id,
                )
            )
        obs.append(
            Observation(
                kbo_number=row.enterprise_number,
                field="status",
                value={"value": "active"},
                raw_value=row.status,
                source="kbo_dump",
                observed_at=observed_at,
                confidence=1.00,
                run_id=run_id,
            )
        )
    except ValueError:
        logger.warning("invalid_kbo_enterprise_skipped", enterprise_number=row.enterprise_number)
        return []
    return obs


def denomination_to_observation(
    row: DenominationRow, run_id: UUID, observed_at: datetime
) -> Observation | None:
    """Map a denomination row to a name observation.

    Types: 001=legal name (confidence 1.00), 002=abbreviation (0.90), 003=commercial (0.95).
    Unknown types are skipped.
    """
    confidence = _DENOM_CONFIDENCE.get(row.type_of_denomination)
    if confidence is None:
        return None
    lang = _LANG_MAP.get(row.language)
    value: dict[str, str] = {"text": row.denomination}
    if lang is not None:
        value["lang"] = lang
    denom_type = _DENOM_TYPE.get(row.type_of_denomination)
    if denom_type is not None:
        value["type"] = denom_type
    try:
        return Observation(
            kbo_number=row.entity_number,
            field="name",
            value=value,
            raw_value=row.denomination,
            source="kbo_dump",
            observed_at=observed_at,
            confidence=confidence,
            run_id=run_id,
        )
    except ValueError:
        logger.warning("invalid_kbo_denomination_skipped", entity_number=row.entity_number)
        return None


def address_to_observation(
    row: AddressRow, run_id: UUID, observed_at: datetime
) -> Observation | None:
    """Produce one address observation. Uses NL fields, falls back to FR. Skips if no street."""
    street = row.street_nl or row.street_fr
    if not street:
        return None
    city = row.municipality_nl or row.municipality_fr
    hn = row.house_number
    full_street = f"{street} {hn}".strip() if hn else street
    value: dict[str, str | None] = {
        "street": full_street,
        "postal_code": row.zipcode,
        "city": city,
        "country": "BE",
    }
    raw = f"{full_street}, {row.zipcode} {city}".strip(", ")
    try:
        return Observation(
            kbo_number=row.entity_number,
            field="address",
            value={k: v for k, v in value.items() if v is not None},
            raw_value=raw,
            source="kbo_dump",
            observed_at=observed_at,
            confidence=0.95,
            run_id=run_id,
        )
    except ValueError:
        logger.warning("invalid_kbo_address_skipped", entity_number=row.entity_number)
        return None


def contact_to_observation(
    row: ContactRow, run_id: UUID, observed_at: datetime
) -> Observation | None:
    """Map a contact row to a phone/email/website observation.

    For TEL: calls validate_phone(); returns None (and logs) on InvalidPhoneError.
    Callers should count None returns on TEL rows as phones_invalid_skipped.
    """
    raw = row.value.strip()
    if not raw:
        return None

    if row.contact_type == "TEL":
        try:
            phone = validate_phone(raw)
        except InvalidPhoneError:
            logger.warning("invalid_phone_skipped", kbo_number=row.entity_number, raw=raw)
            return None
        value = phone.model_dump()
        try:
            return Observation(
                kbo_number=row.entity_number,
                field="phone",
                value=value,
                raw_value=raw,
                source="kbo_dump",
                observed_at=observed_at,
                confidence=0.95,
                run_id=run_id,
            )
        except ValueError:
            return None

    if row.contact_type == "EMAIL":
        local = raw.split("@")[0].lower() if "@" in raw else ""
        is_role = local in _ROLE_ACCOUNTS
        try:
            return Observation(
                kbo_number=row.entity_number,
                field="email",
                value={"address": raw, "is_role_account": is_role},
                raw_value=raw,
                source="kbo_dump",
                observed_at=observed_at,
                confidence=0.85,
                run_id=run_id,
            )
        except ValueError:
            return None

    if row.contact_type == "WEB":
        try:
            netloc = urlparse(raw).netloc
            parts = netloc.split(".")
            tld = parts[-1] if len(parts) > 1 else None
        except Exception:
            tld = None
        try:
            return Observation(
                kbo_number=row.entity_number,
                field="website",
                value={"url": raw, "tld": tld},
                raw_value=raw,
                source="kbo_dump",
                observed_at=observed_at,
                confidence=0.85,
                run_id=run_id,
            )
        except ValueError:
            return None

    return None


def activity_to_observation(
    row: ActivityRow, run_id: UUID, observed_at: datetime
) -> Observation | None:
    """Produce a nace_code observation for each activity row."""
    try:
        return Observation(
            kbo_number=row.entity_number,
            field="nace_code",
            value={"code": row.nace_code, "version": row.nace_version},
            raw_value=row.nace_code,
            source="kbo_dump",
            observed_at=observed_at,
            confidence=0.95,
            run_id=run_id,
        )
    except ValueError:
        logger.warning("invalid_kbo_activity_skipped", entity_number=row.entity_number)
        return None
