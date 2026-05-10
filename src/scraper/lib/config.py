from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from scraper.lib.errors import ConfigError

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str
    log_level: str = "INFO"
    run_env: str = "dev"


def load_settings(env_file: Path | None = None) -> Settings:
    """Load .env via python-dotenv if present, then read from os.environ."""
    try:
        from dotenv import load_dotenv

        if env_file is not None:
            load_dotenv(env_file)
        else:
            load_dotenv()
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
