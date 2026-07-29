"""Pick the next slice of sectors to scrape, so nightly runs continue rather than repeat.

goudengids' WAF blocked a 103-sector run after ~30 minutes (observed 2026-07-29: 8
sectors served, then every subsequent sector blocked on page 1). The fix is to scrape a
small slice per night and stop while still under the threshold.

That only works if each night knows what previous nights finished. "Finished" must mean
*productive*: a sector that was blocked reached the WAF, not the data, and has to be
retried — treating it as done would silently skip it forever.
"""

from __future__ import annotations

import pytest

from scraper.pipeline.sector_queue import select_pending_sectors

_ALL = ["a", "b", "c", "d", "e"]


class TestSelectPendingSectors:
    def test_returns_first_slice_when_nothing_done(self) -> None:
        assert select_pending_sectors(_ALL, done=set(), limit=2) == ["a", "b"]

    def test_skips_completed_sectors(self) -> None:
        assert select_pending_sectors(_ALL, done={"a", "b"}, limit=2) == ["c", "d"]

    def test_limit_larger_than_remaining_returns_the_rest(self) -> None:
        assert select_pending_sectors(_ALL, done={"a", "b", "c"}, limit=10) == ["d", "e"]

    def test_all_done_returns_empty(self) -> None:
        assert select_pending_sectors(_ALL, done=set(_ALL), limit=5) == []

    def test_order_is_preserved(self) -> None:
        """Stable order means the cycle covers everything before repeating."""
        assert select_pending_sectors(_ALL, done={"c"}, limit=5) == ["a", "b", "d", "e"]

    def test_unknown_done_entries_are_ignored(self) -> None:
        """A sector removed from the config must not shift the slice."""
        assert select_pending_sectors(_ALL, done={"zzz"}, limit=2) == ["a", "b"]

    def test_limit_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="limit"):
            select_pending_sectors(_ALL, done=set(), limit=0)

    def test_wraps_when_every_sector_is_done_and_cycle_requested(self) -> None:
        """With --cycle, a fully-covered city starts the rotation again instead of
        doing nothing forever."""
        assert select_pending_sectors(_ALL, done=set(_ALL), limit=2, cycle=True) == ["a", "b"]


class TestBlockedSectorsAreNotDone:
    def test_blocked_sector_is_retried(self) -> None:
        """A blocked run reached the WAF, not the data. If it counted as done the
        sector would be skipped forever and its leads never collected."""
        from scraper.pipeline.sector_queue import completed_sectors

        rows = [
            {"sector_slug": "a", "jobs_done": 12},
            {"sector_slug": "b", "jobs_done": 0},  # blocked on page 1
        ]
        assert completed_sectors(rows) == {"a"}

    def test_sector_with_observations_counts_as_done(self) -> None:
        from scraper.pipeline.sector_queue import completed_sectors

        assert completed_sectors([{"sector_slug": "x", "jobs_done": 1}]) == {"x"}

    def test_null_sector_slug_is_ignored(self) -> None:
        from scraper.pipeline.sector_queue import completed_sectors

        assert completed_sectors([{"sector_slug": None, "jobs_done": 5}]) == set()
