from __future__ import annotations

from pathlib import Path

import pytest

from scraper.lib.config import Settings, load_settings
from scraper.lib.errors import ConfigError

# Use a non-existent env_file so load_dotenv is a no-op and we rely only on
# the monkeypatched os.environ — avoids picking up the project's .env file.
_NO_ENV_FILE = Path("/does/not/exist/.env")


def test_load_settings_reads_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost/db")
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    monkeypatch.delenv("RUN_ENV", raising=False)
    settings = load_settings(env_file=_NO_ENV_FILE)
    assert settings.database_url == "postgresql://u:p@localhost/db"
    assert settings.log_level == "INFO"
    assert settings.run_env == "dev"


def test_load_settings_reads_optional_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost/db")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("RUN_ENV", "prod")
    settings = load_settings(env_file=_NO_ENV_FILE)
    assert settings.log_level == "DEBUG"
    assert settings.run_env == "prod"


def test_load_settings_missing_url_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ConfigError):
        load_settings(env_file=_NO_ENV_FILE)


def test_settings_is_frozen() -> None:
    s = Settings(database_url="postgresql://x")
    with pytest.raises((AttributeError, TypeError)):
        s.database_url = "other"  # type: ignore[misc]
