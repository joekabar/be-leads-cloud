from __future__ import annotations

import csv
import json
import sys
from enum import StrEnum
from pathlib import Path
from typing import Any

import phonenumbers
from phonenumbers import NumberParseException, PhoneNumberFormat, PhoneNumberType
from pydantic import BaseModel, ConfigDict

from scraper.lib.errors import ScraperError

_TSV_PATH = (
    Path(__file__).parents[4]
    / ".claude"
    / "skills"
    / "belgian-phone-validation"
    / "references"
    / "prefixes.tsv"
)


class PhoneType(StrEnum):
    FIXED_LINE = "fixed_line"
    MOBILE = "mobile"
    PREMIUM_RATE = "premium_rate"
    TOLL_FREE = "toll_free"
    SHARED_COST = "shared_cost"
    M2M = "m2m"
    VOIP = "voip"
    UNKNOWN = "unknown"


class PhoneValidation(BaseModel):
    """Canonical phone observation value. Matches the provenance-schema
    contract: every field listed becomes a key in observations.value JSONB."""

    model_config = ConfigDict(frozen=True)

    e164: str
    raw: str
    type: PhoneType
    region: str | None
    original_carrier: str | None


class InvalidPhoneError(ScraperError):
    def __init__(self, value: Any) -> None:
        super().__init__(f"Invalid Belgian phone number: {value!r}")
        self.value = value


def _load_prefixes() -> dict[str, tuple[str, str | None]]:
    if not _TSV_PATH.exists():
        raise RuntimeError(
            f"Belgian phone prefix table not found: {_TSV_PATH}. Cannot initialise phone validator."
        )
    result: dict[str, tuple[str, str | None]] = {}
    with _TSV_PATH.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for row in reader:
            prefix = str(row["prefix"]).strip()
            kind = str(row["kind"]).strip()
            carrier_region = str(row["region_or_carrier"]).strip()
            result[prefix] = (kind, None if carrier_region in ("—", "") else carrier_region)
    return result


# Loaded once at module import; cached for the lifetime of the process.
_PREFIXES: dict[str, tuple[str, str | None]] = _load_prefixes()

_NUMBER_TYPE_MAP: dict[int, PhoneType] = {
    PhoneNumberType.FIXED_LINE: PhoneType.FIXED_LINE,
    PhoneNumberType.FIXED_LINE_OR_MOBILE: PhoneType.FIXED_LINE,
    PhoneNumberType.MOBILE: PhoneType.MOBILE,
    PhoneNumberType.PREMIUM_RATE: PhoneType.PREMIUM_RATE,
    PhoneNumberType.TOLL_FREE: PhoneType.TOLL_FREE,
    PhoneNumberType.SHARED_COST: PhoneType.SHARED_COST,
    PhoneNumberType.VOIP: PhoneType.VOIP,
}


def _classify(e164: str) -> tuple[PhoneType, str | None, str | None]:
    """Return (type, region, original_carrier) from an E.164 Belgian number."""
    nsn = e164[3:]  # strip "+32"
    national = "0" + nsn

    # Liège trap: 04 xxx xx xx (9-digit total = NSN 8 digits) is a landline,
    # NOT a mobile — even though it shares the '4' first digit with mobiles.
    if nsn[0] == "4" and len(nsn) == 8 and int(nsn[1:3]) < 55:
        return PhoneType.FIXED_LINE, "Liège-Voeren", None

    # Longest-prefix match from the BIPT allocation table.
    best: str | None = None
    for prefix in _PREFIXES:
        if national.startswith(prefix) and (best is None or len(prefix) > len(best)):
            best = prefix

    if best is not None:
        kind, region_carrier = _PREFIXES[best]
        phone_type = PhoneType(kind)
        region = region_carrier if phone_type == PhoneType.FIXED_LINE else None
        carrier = region_carrier if phone_type == PhoneType.MOBILE else None
        return phone_type, region, carrier

    # Fallback: delegate to phonenumbers when no TSV prefix matched.
    parsed = phonenumbers.parse(e164)
    num_type = phonenumbers.number_type(parsed)
    return _NUMBER_TYPE_MAP.get(num_type, PhoneType.UNKNOWN), None, None


def validate_phone(s: str, *, default_region: str = "BE") -> PhoneValidation:
    """Parse and classify a Belgian phone string. Raises InvalidPhoneError on bad input."""
    if not isinstance(s, str) or not s.strip():
        raise InvalidPhoneError(s)
    try:
        parsed = phonenumbers.parse(s, default_region)
    except NumberParseException as exc:
        raise InvalidPhoneError(s) from exc
    e164 = phonenumbers.format_number(parsed, PhoneNumberFormat.E164)
    # Belgian numbers are always 9 or 10 digits (trunk-0 national format).
    # This length guard catches clearly-wrong input before the TSV lookup.
    national = "0" + e164[3:]
    if len(national) not in {9, 10}:
        raise InvalidPhoneError(s)
    phone_type, region, original_carrier = _classify(e164)
    # TSV-matched numbers are accepted even when phonenumbers doesn't recognise
    # the allocation (e.g. M2M 077). Only reject when both the TSV has no entry
    # and phonenumbers also says the number is invalid.
    if phone_type is PhoneType.UNKNOWN and not phonenumbers.is_valid_number(parsed):
        raise InvalidPhoneError(s)
    return PhoneValidation(
        e164=e164,
        raw=s,
        type=phone_type,
        region=region,
        original_carrier=original_carrier,
    )


def cli_main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Validate a Belgian phone number")
    parser.add_argument("phone", help="Phone number string to validate")
    parser.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        default=True,
        help="Output result as JSON (default: true)",
    )
    args = parser.parse_args()
    try:
        result = validate_phone(args.phone)
        print(json.dumps(result.model_dump()))
    except InvalidPhoneError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
