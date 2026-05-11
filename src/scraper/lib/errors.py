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


class InvalidKboError(ScraperError):
    """KBO number is syntactically invalid (fails mod-97 checksum)."""

    def __init__(self, number: str) -> None:
        super().__init__(f"Invalid KBO number: {number!r}")
        self.number = number


class KboNotFoundError(ScraperError):
    """KBO number is valid but not found in the kbopub registry (HTTP 404)."""

    def __init__(self, number: str, url: str) -> None:
        super().__init__(f"KBO not found: {number!r} at {url}")
        self.number = number
        self.url = url


class NbbNotFoundError(ScraperError):
    """KBO not found in NBB CBSO (HTTP 404) — entity never filed, or does not exist."""

    def __init__(self, number: str, url: str) -> None:
        super().__init__(f"KBO not found in NBB CBSO: {number!r} at {url}")
        self.number = number
        self.url = url


class NbbAuthError(HttpError):
    """NBB CBSO returned 401 — subscription key invalid or expired."""
