from __future__ import annotations

from scraper.lib.errors import InvalidSourceError

ALLOWED_SOURCES: frozenset[str] = frozenset(
    {
        "kbo_dump",
        "kbopub",
        "nbb_authentic",
        "goudengids",
        "pagesdor",
        "website",
        "ddg",
        "brave",
        "wayback",
        "manual",
    }
)


def validate_source(name: str) -> None:
    """Raise InvalidSourceError if name is not a known source."""
    if name not in ALLOWED_SOURCES:
        raise InvalidSourceError(name)
