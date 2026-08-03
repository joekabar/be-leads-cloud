"""A query that matches nothing is an outcome, not a failure.

`ddgs` raises `DDGSException("No results found.")` when a search returns zero hits. That
escaped uncaught, past the caller's rate-limit handler, and aborted Phase C2 entirely:
every batch from 2026-07-30 to 2026-08-02 logged
``phase_c2_failed error='No results found.'`` and cross-validated nothing at all.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from ddgs.exceptions import DDGSException, RatelimitException

from scraper.sources.ddg_brave.ddg_client import DdgClient, DdgRateLimitedError


def _ddgs_raising(exc: Exception) -> MagicMock:
    ddgs_cls = MagicMock()
    ddgs_cls.return_value.text.side_effect = exc
    return ddgs_cls


def _ddgs_returning(rows: list[dict[str, str]]) -> MagicMock:
    ddgs_cls = MagicMock()
    ddgs_cls.return_value.text.return_value = rows
    return ddgs_cls


class TestNoResultsIsNotAnError:
    def test_no_results_returns_empty_list(self) -> None:
        with patch.dict(
            "sys.modules",
            {"ddgs": MagicMock(DDGS=_ddgs_raising(DDGSException("No results found.")))},
        ):
            assert asyncio.run(DdgClient().search("nothing matches this")) == []

    def test_other_ddgs_errors_are_also_survivable(self) -> None:
        """The phase must not die on one query, whatever ddgs decides to raise."""
        with patch.dict(
            "sys.modules",
            {"ddgs": MagicMock(DDGS=_ddgs_raising(DDGSException("upstream parse error")))},
        ):
            assert asyncio.run(DdgClient().search("q")) == []


class TestNormalPaths:
    def test_results_are_returned(self) -> None:
        rows = [{"title": "Bellock", "href": "https://bellock.be", "body": "..."}]
        with patch.dict("sys.modules", {"ddgs": MagicMock(DDGS=_ddgs_returning(rows))}):
            assert asyncio.run(DdgClient().search("Bellock")) == rows

    def test_empty_result_set_is_empty_list(self) -> None:
        with patch.dict("sys.modules", {"ddgs": MagicMock(DDGS=_ddgs_returning([]))}):
            assert asyncio.run(DdgClient().search("q")) == []


class TestRateLimitStillRaises:
    def test_rate_limit_survives_the_new_handler(self) -> None:
        """RatelimitException subclasses DDGSException; it must not be swallowed as 'no results'."""
        with (
            patch.dict(
                "sys.modules",
                {"ddgs": MagicMock(DDGS=_ddgs_raising(RatelimitException("429")))},
            ),
            patch("asyncio.sleep", return_value=None),
            pytest.raises(DdgRateLimitedError),
        ):
            asyncio.run(DdgClient().search("q"))
