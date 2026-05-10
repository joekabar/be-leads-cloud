from __future__ import annotations

import pytest

from scraper.db.sources import ALLOWED_SOURCES, validate_source
from scraper.lib.errors import InvalidSourceError


def test_all_allowed_sources_pass() -> None:
    for source in ALLOWED_SOURCES:
        validate_source(source)  # must not raise


def test_unknown_source_raises() -> None:
    with pytest.raises(InvalidSourceError):
        validate_source("not_a_real_source")


def test_empty_source_raises() -> None:
    with pytest.raises(InvalidSourceError):
        validate_source("")
