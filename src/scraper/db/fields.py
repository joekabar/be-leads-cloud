from __future__ import annotations

import re

from scraper.lib.errors import InvalidFieldError

ALLOWED_FIELDS: frozenset[str] = frozenset(
    {
        "phone",
        "email",
        "website",
        "address",
        "name",
        "founding_date",
        "nace_code",
        "function_holder",
        "activity_summary",
        "website_age",
        "postal_code",
        "status",
        "cross_validation",
    }
)

_FINANCIAL_RE = re.compile(r"^(revenue|profit|employees)_(\d{4})$")


def is_financial_field(name: str) -> bool:
    """Return True for revenue_YYYY / profit_YYYY / employees_YYYY (four-digit year)."""
    m = _FINANCIAL_RE.match(name)
    return m is not None and len(m.group(2)) == 4


def validate_field(name: str) -> None:
    """Raise InvalidFieldError if name is not a known static field or valid financial field."""
    if name not in ALLOWED_FIELDS and not is_financial_field(name):
        raise InvalidFieldError(name)
