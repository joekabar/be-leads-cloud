from __future__ import annotations


class ScraperError(Exception):
    pass


class ConfigError(ScraperError):
    """Required configuration value is missing or invalid."""


class InvalidFieldError(ScraperError):
    """Observation field name is not in the allowed set."""

    def __init__(self, name: str) -> None:
        super().__init__(f"Unknown observation field: {name!r}")
        self.name = name


class InvalidSourceError(ScraperError):
    """Observation source name is not in the allowed set."""

    def __init__(self, name: str) -> None:
        super().__init__(f"Unknown observation source: {name!r}")
        self.name = name


class HttpError(ScraperError):
    def __init__(self, status: int, url: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.url = url


class RateLimitedError(HttpError):
    """HTTP 429 — back off and retry."""


class BlockedError(HttpError):
    """HTTP 403 — WAF block; caller must NOT retry."""


class TransientServerError(HttpError):
    """HTTP 500/502/503/504 — transient; safe to retry."""


class TerminalServerError(HttpError):
    """Other 4xx/5xx — not retriable."""


class RetriesExhaustedError(ScraperError):
    """All retry attempts consumed without a successful response."""
