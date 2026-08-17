from __future__ import annotations

import pytest

from scraper.db.suppress_cli import _resolve_dsn
from scraper.lib.errors import ConfigError


class TestResolveDsn:
    """``--database-url`` must work without DATABASE_URL also being set.

    ``load_settings()`` raises when DATABASE_URL is missing, so consulting it before the
    explicit flag made the flag unusable in the one situation it exists for: pointing the
    tool at a database other than the one in the environment.
    """

    def test_explicit_dsn_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", "postgresql://env/leads")
        assert _resolve_dsn("postgresql://explicit/other") == "postgresql://explicit/other"

    def test_explicit_dsn_does_not_need_the_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        assert _resolve_dsn("postgresql://explicit/other") == "postgresql://explicit/other"

    def test_falls_back_to_the_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", "postgresql://env/leads")
        assert _resolve_dsn(None) == "postgresql://env/leads"

    def test_no_dsn_anywhere_is_an_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Better a named ConfigError than a connection attempt to an empty string."""
        monkeypatch.delenv("DATABASE_URL", raising=False)
        with pytest.raises(ConfigError):
            _resolve_dsn(None)
