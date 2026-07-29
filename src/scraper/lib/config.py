from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from scraper.lib.errors import ConfigError


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str
    log_level: str = "INFO"
    run_env: str = "dev"


def project_root() -> Path:
    """Return the checkout root: the nearest ancestor holding pyproject.toml.

    Derived from this file, never from os.getcwd(), so it is stable regardless of
    where the process was started.
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    # Installed as a wheel with no checkout present — fall back to the package parent.
    return here.parents[2]


def load_settings(env_file: Path | None = None) -> Settings:
    """Load .env via python-dotenv if present, then read from os.environ.

    When *env_file* is omitted the file is read from the **project root**, not the
    working directory: a bare ``load_dotenv()`` searches upward from ``os.getcwd()``,
    so launching ``streamlit run`` from elsewhere would silently find no .env.
    """
    try:
        from dotenv import load_dotenv

        load_dotenv(env_file if env_file is not None else project_root() / ".env")
    except ImportError:
        pass

    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        raise ConfigError(
            "DATABASE_URL is not set. Export it or add it to .env before running be-leads."
        )

    return Settings(
        database_url=database_url,
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
        run_env=os.environ.get("RUN_ENV", "dev"),
    )


def database_url() -> str:
    """Return DATABASE_URL after loading .env, or "" when it is not configured.

    Non-raising counterpart to :func:`load_settings` for the Streamlit pages, which
    must render an actionable message rather than abort the script. Always use this
    instead of reading ``os.environ["DATABASE_URL"]`` directly: a raw read executes
    before anything has loaded .env and yields "", which silently disables the results
    fetch and leaves an empty table with no error.
    """
    try:
        return load_settings().database_url
    except ConfigError:
        return ""
