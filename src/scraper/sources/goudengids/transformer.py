"""Transform ListingCardRow → list[Observation].

Because goudengids listing pages don't include KBO numbers, observations use synthetic
placeholder KBOs formed from (name, postal_code). These start with "9", deliberately
fail the mod-97 checksum, and are reconciled to real KBOs by the consolidation pass
(prompt 11). See .claude/skills/provenance-schema/SKILL.md §9.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import structlog

from scraper.db.models import Observation
from scraper.lib.validators.phone import InvalidPhoneError, validate_phone

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from scraper.sources.goudengids.parser import ListingCardRow

logger = structlog.get_logger()

_SOURCE = "goudengids"
_CONFIDENCE_NAME = 0.85
_CONFIDENCE_PHONE = 0.85
_CONFIDENCE_WEBSITE = 0.85
_CONFIDENCE_ADDRESS = 0.80
_CONFIDENCE_EMAIL = 0.80


def make_placeholder_kbo(name: str, postal_code: str | None) -> str:
    """Deterministic synthetic KBO (9-prefix) for a goudengids card without a real KBO."""
    key = f"{name.lower().strip()}|{(postal_code or '').strip()}".encode()
    h = int(hashlib.sha256(key).hexdigest(), 16)
    return f"9{h % 10**9:09d}"


def card_to_observations(
    card: ListingCardRow,
    run_id: UUID,
    snapshot_at: datetime,
) -> list[Observation]:
    """Emit observations for name, phones, website, address, and optional email.

    Skips phone observations that fail Belgian phone validation (warns, does not crash).
    Skips address observation when street is absent.
    """
    kbo = make_placeholder_kbo(card.name, card.address_postal_code)
    source_url = card.detail_url
    obs: list[Observation] = []

    obs.append(
        Observation(
            kbo_number=kbo,
            field="name",
            value={"text": card.name, "lang": "nl"},
            raw_value=card.name,
            source=_SOURCE,
            source_url=source_url,
            observed_at=snapshot_at,
            confidence=_CONFIDENCE_NAME,
            run_id=run_id,
        )
    )

    for phone_str in card.phones:
        try:
            validated = validate_phone(phone_str)
        except InvalidPhoneError:
            logger.warning(
                "goudengids_invalid_phone_skipped",
                phone=phone_str,
                company=card.name,
            )
            continue
        obs.append(
            Observation(
                kbo_number=kbo,
                field="phone",
                value=validated.model_dump(),
                raw_value=phone_str,
                source=_SOURCE,
                source_url=source_url,
                observed_at=snapshot_at,
                confidence=_CONFIDENCE_PHONE,
                run_id=run_id,
            )
        )

    if card.website:
        parsed = urlparse(card.website)
        tld = parsed.netloc.rsplit(".", 1)[-1] if parsed.netloc else ""
        obs.append(
            Observation(
                kbo_number=kbo,
                field="website",
                value={"url": card.website, "tld": tld},
                raw_value=card.website,
                source=_SOURCE,
                source_url=source_url,
                observed_at=snapshot_at,
                confidence=_CONFIDENCE_WEBSITE,
                run_id=run_id,
            )
        )

    if card.address_street:
        obs.append(
            Observation(
                kbo_number=kbo,
                field="address",
                value={
                    "street": card.address_street,
                    "postal_code": card.address_postal_code or "",
                    "city": card.address_city or "",
                    "country": "BE",
                },
                raw_value=(
                    f"{card.address_street}, "
                    f"{card.address_postal_code or ''} {card.address_city or ''}".strip()
                ),
                source=_SOURCE,
                source_url=source_url,
                observed_at=snapshot_at,
                confidence=_CONFIDENCE_ADDRESS,
                run_id=run_id,
            )
        )

    if card.email:
        obs.append(
            Observation(
                kbo_number=kbo,
                field="email",
                value={"address": card.email, "is_role_account": False},
                raw_value=card.email,
                source=_SOURCE,
                source_url=source_url,
                observed_at=snapshot_at,
                confidence=_CONFIDENCE_EMAIL,
                run_id=run_id,
            )
        )

    return obs
