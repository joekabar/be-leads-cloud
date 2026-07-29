"""The goudengids ingester must not refresh the matview once per sector in a batch.

refresh_companies_current() rebuilds a DISTINCT ON view over ~8.7M observation rows and
costs ~130 s. The ingester ran it in a finally block after every sector, so a 103-sector
batch paid for 103 rebuilds — measured live: a sector that found ZERO cards still took
161.8 s, essentially all of it the refresh.

Nothing in the batch reads companies_current until Phase D (consolidate), and the batch
orchestrator refreshes before it. The per-sector refresh is therefore redundant inside a
batch — but it stays the default so the standalone CLI
(``be-leads-discover-goudengids``) still leaves the view consistent for a human running
one sector by hand.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from scraper.sources.goudengids import ingester as ing


def _pool() -> tuple[MagicMock, list[str]]:
    executed: list[str] = []
    pool = MagicMock()

    async def _execute(sql: str, *a: Any, **k: Any) -> None:
        executed.append(sql)

    async def _fetch(*_a: Any, **_k: Any) -> list[Any]:
        return []

    pool.execute = _execute
    pool.fetch = _fetch
    pool.fetchrow = AsyncMock(return_value=None)
    return pool, executed


def _fetcher() -> MagicMock:
    """Fetcher whose first page is already the last, so the loop exits immediately."""
    f = MagicMock()
    f._domain = "goudengids.be"
    f.__aenter__ = AsyncMock(return_value=f)
    f.__aexit__ = AsyncMock(return_value=False)
    listing = MagicMock()
    listing.is_last_page = True
    listing.html = ""
    f.fetch_page = AsyncMock(return_value=listing)
    return f


async def _run(pool: MagicMock, **kwargs: Any) -> Any:
    with (
        patch.object(ing, "RunsRepo") as runs,
        patch.object(ing, "ObservationsRepo"),
    ):
        runs.return_value.start_run = AsyncMock(return_value=uuid4())
        runs.return_value.finish_run = AsyncMock()
        result = await ing.ingest_sector_city(
            "dakdekkers", "oostende", pool, _fetcher(), skip_recent_hours=0, **kwargs
        )
        return result, runs.return_value.finish_run


class TestRefreshMatviewFlag:
    async def test_refreshes_by_default_for_standalone_cli(self) -> None:
        pool, executed = _pool()
        await _run(pool)
        assert any("refresh_companies_current" in s for s in executed)

    async def test_skips_refresh_when_disabled(self) -> None:
        pool, executed = _pool()
        await _run(pool, refresh_matview=False)
        assert not any("refresh_companies_current" in s for s in executed)

    async def test_run_is_still_finished_when_refresh_disabled(self) -> None:
        """Skipping the refresh must not skip closing out the run_log row."""
        pool, _ = _pool()
        _result, finish = await _run(pool, refresh_matview=False)
        finish.assert_awaited_once()


class TestReportExposesOutOfCityCount:
    def test_report_has_cards_out_of_city_field(self) -> None:
        r = ing.GoudengidsReport(sector="dakdekkers", city="oostende")
        assert r.cards_out_of_city == 0

    def test_finished_log_includes_out_of_city(self) -> None:
        """The count was tracked but never logged, so a thin run could not be
        explained from the batch log — which is exactly when you need it."""
        import inspect

        src = inspect.getsource(ing.ingest_sector_city)
        after = src.split("goudengids_ingest_finished", 1)[1]
        assert "cards_out_of_city" in after
