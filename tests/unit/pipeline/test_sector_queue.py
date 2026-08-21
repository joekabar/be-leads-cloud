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

from scraper.pipeline.sector_queue import (
    _completed_window_clause,
    completed_sectors,
    select_next_city,
    select_pending_sectors,
)

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


class TestUnscrapeableSectorsLeaveTheRotation:
    """A sector goudengids does not index can never produce observations.

    `completed_sectors` counts a sector done only when `jobs_done > 0`, which is right for
    a *blocked* sector but wrong for one that does not exist on the site. On 2026-07-30
    `afvalverwerkingsindustrie` and `automobielfabrieken` both logged
    `goudengids_sector_not_indexed`, produced nothing, and so stayed pending — they sat at
    the head of the queue and would have consumed a slot every night forever.
    """

    def test_unscrapeable_sector_is_excluded(self) -> None:
        assert select_pending_sectors(_ALL, done=set(), limit=2, unscrapeable={"a"}) == ["b", "c"]

    def test_unscrapeable_combines_with_done(self) -> None:
        result = select_pending_sectors(_ALL, done={"b"}, limit=5, unscrapeable={"a"})
        assert result == ["c", "d", "e"]

    def test_cycle_does_not_resurrect_unscrapeable_sectors(self) -> None:
        """Restarting the rotation must not put dead sectors back in."""
        result = select_pending_sectors(
            _ALL, done=set(_ALL), limit=5, cycle=True, unscrapeable={"a"}
        )
        assert result == ["b", "c", "d", "e"]

    def test_defaults_to_excluding_nothing(self) -> None:
        assert select_pending_sectors(_ALL, done=set(), limit=2) == ["a", "b"]


class TestGoudengidsUnscrapeableSectors:
    def test_flagged_sector_is_unscrapeable(self) -> None:
        from scraper.pipeline.sector_queue import goudengids_unscrapeable_sectors

        # energieproducenten and chemiebedrijven carry goudengids_sector_not_indexed.
        result = goudengids_unscrapeable_sectors(["energieproducenten", "chemiebedrijven"])
        assert result == {"energieproducenten", "chemiebedrijven"}

    def test_indexed_sector_is_scrapeable(self) -> None:
        from scraper.pipeline.sector_queue import goudengids_unscrapeable_sectors

        assert goudengids_unscrapeable_sectors(["elektriciens"]) == set()

    def test_sector_absent_from_the_config_is_unscrapeable(self) -> None:
        """No goudengids entry means no listing URL to fetch — same dead end."""
        from scraper.pipeline.sector_queue import goudengids_unscrapeable_sectors

        assert goudengids_unscrapeable_sectors(["nonexistent-sector-xyz"]) == {
            "nonexistent-sector-xyz"
        }

    def test_the_two_sectors_that_stalled_the_2026_07_30_rotation(self) -> None:
        from scraper.pipeline.sector_queue import goudengids_unscrapeable_sectors

        result = goudengids_unscrapeable_sectors(
            ["afvalverwerkingsindustrie", "automobielfabrieken", "advocaten"]
        )
        assert result == {"afvalverwerkingsindustrie", "automobielfabrieken"}


class TestCityRotation:
    """One city is finished before the next is started.

    Broad-but-shallow coverage of many cities is worth less commercially than one
    complete, sellable city: the rotation therefore stays on a city until it has no
    pending sectors left, then advances.
    """

    def test_first_city_with_pending_work_wins(self) -> None:
        result = select_next_city(
            ["brugge", "oostende"], _ALL, {"brugge": set(), "oostende": set()}
        )
        assert result == "brugge"

    def test_advances_only_when_the_city_is_complete(self) -> None:
        result = select_next_city(
            ["brugge", "oostende"], _ALL, {"brugge": set(_ALL), "oostende": {"a"}}
        )
        assert result == "oostende"

    def test_stays_on_a_partially_done_city(self) -> None:
        result = select_next_city(["brugge", "oostende"], _ALL, {"brugge": {"a", "b"}})
        assert result == "brugge"

    def test_returns_none_when_every_city_is_complete(self) -> None:
        done = {c: set(_ALL) for c in ["brugge", "oostende"]}
        assert select_next_city(["brugge", "oostende"], _ALL, done) is None

    def test_unknown_city_is_treated_as_untouched(self) -> None:
        assert select_next_city(["brugge"], _ALL, {}) == "brugge"

    def test_unscrapeable_sectors_do_not_keep_a_city_alive(self) -> None:
        """A city whose only 'pending' sectors are unscrapeable is finished."""
        done = set(_ALL) - {"e"}
        result = select_next_city(
            ["brugge", "oostende"],
            _ALL,
            {"brugge": done, "oostende": {"a"}},
            unscrapeable={"e"},
        )
        assert result == "oostende"

    def test_empty_city_list_returns_none(self) -> None:
        assert select_next_city([], _ALL, {}) is None


class TestRotationConfig:
    def test_bundled_rotation_is_loadable_and_ordered(self) -> None:
        from scraper.pipeline.sector_queue import load_rotation_cities

        cities = load_rotation_cities()
        assert cities[0] == "oostende", "oostende leads the rotation by request"
        assert len(cities) >= 2
        assert len(set(cities)) == len(cities), "a duplicate city would be scraped twice"

    def test_rotation_excludes_french_speaking_cities(self) -> None:
        """Those live on pagesdor.be and need lang=fr, which is separate work."""
        from scraper.pipeline.sector_queue import load_rotation_cities

        cities = set(load_rotation_cities())
        assert not cities & {"charleroi", "liege", "luik", "mons", "bergen", "namur", "namen"}

    def test_rotation_has_no_gent_ghent_duplicate(self) -> None:
        """Both spellings resolve to the same city, so listing both scrapes it twice.

        city_map.toml declares "ghent" as an alias of "gent" rather than a second entry
        with a copy of the postcodes — see TestAliases in test_city_map.py.
        """
        from scraper.pipeline.sector_queue import load_rotation_cities

        cities = set(load_rotation_cities())
        assert not {"gent", "ghent"} <= cities


class TestRefreshOnlyOnCommand:
    """A completed sector is never re-offered until someone asks for it.

    The 720-hour window meant every sector silently came back after 30 days. With one
    city that was harmless; across eleven cities it would mean the rotation never
    finishes, because early cities keep re-entering the queue before the last is reached.
    """

    def test_all_time_is_the_default(self) -> None:
        assert _completed_window_clause(None) == ""

    def test_a_window_still_filters_when_requested(self) -> None:
        assert "interval" in _completed_window_clause(720)

    def test_zero_hours_means_all_time_not_nothing(self) -> None:
        """0 must not become 'started_at >= now()', which would mark everything pending."""
        assert _completed_window_clause(0) == ""


class TestSectorsThatFinishedAreDone:
    """A sector that read its listing to the end is covered, whatever it inserted.

    "obs=0" conflated three unrelated outcomes, and the queue retried all of them:

    1. **No local businesses.** goudengids pads a thin local search with nationwide
       results, so `machinebouwers` returned 500 cards of which 500 were outside
       Oostende. It can never yield a local lead, yet ran twice a day forever.
    2. **Already covered.** `bouwbedrijven` had 84 in-city cards pass the postcode
       filter and still insert nothing — those firms were already in the database from
       other sectors. The sector is complete, not failed.
    3. **Blocked or timed out.** The only case that genuinely deserves a retry.

    Nine of ten nightly slots were stuck on cases 1 and 2. The export flatlined at
    220 kB for three days while still spending the whole WAF budget.

    Completion, not productivity, is therefore the signal: a run that was not cut short
    has seen everything the sector offers.
    """

    def test_completed_run_counts_even_with_zero_observations(self) -> None:
        rows = [{"sector_slug": "a", "jobs_done": 0, "notes": "[complete]"}]
        assert completed_sectors(rows) == {"a"}

    def test_interrupted_run_still_retries(self) -> None:
        rows = [{"sector_slug": "a", "jobs_done": 0, "notes": "[interrupted]"}]
        assert completed_sectors(rows) == set()

    def test_productive_run_counts_without_a_marker(self) -> None:
        """Backwards compatibility: historical rows predate the marker."""
        assert completed_sectors([{"sector_slug": "a", "jobs_done": 12}]) == {"a"}

    def test_legacy_zero_row_without_marker_still_retries(self) -> None:
        """An old unproductive row is ambiguous, so it gets one more run to mark itself."""
        assert completed_sectors([{"sector_slug": "a", "jobs_done": 0}]) == set()

    def test_one_completed_run_outweighs_earlier_blocks(self) -> None:
        rows = [
            {"sector_slug": "a", "jobs_done": 0, "notes": "[interrupted]"},
            {"sector_slug": "a", "jobs_done": 0, "notes": "[complete]"},
        ]
        assert completed_sectors(rows) == {"a"}

    def test_null_notes_are_tolerated(self) -> None:
        assert completed_sectors([{"sector_slug": "a", "jobs_done": 3, "notes": None}]) == {"a"}

    def test_marker_inside_longer_notes_is_found(self) -> None:
        rows = [{"sector_slug": "a", "jobs_done": 0, "notes": "ran ok [complete] 25 pages"}]
        assert completed_sectors(rows) == {"a"}


class TestRunLogSlugAliases:
    """run_log records the URL slug; the queue works in config keys.

    `_run_goudengids_sector` resolves `bouwbedrijven` to `aannemers` before calling the
    ingester, which is what `start_run` then stores. Six sectors differ that way, and all
    six were invisible to the queue: they could never be marked done however much they
    produced, so each held a nightly slot indefinitely. Five of them were the sectors
    observed stuck across eleven consecutive runs.
    """

    def test_alias_row_marks_the_config_key_done(self) -> None:
        rows = [{"sector_slug": "aannemers", "jobs_done": 40, "notes": "[complete]"}]
        assert completed_sectors(rows) == {"bouwbedrijven"}

    def test_every_known_alias_resolves(self) -> None:
        expected = {
            "aannemers": "bouwbedrijven",
            "logistiek": "logistiekverleners",
            "machinebouw": "machinebouwers",
            "metaalbewerking": "metaalverwerkingsbedrijven",
            "vrachttransport": "transportbedrijven-zwaar",
        }
        for slug, key in expected.items():
            rows = [{"sector_slug": slug, "jobs_done": 1}]
            assert completed_sectors(rows) == {key}, f"{slug} must map to {key}"

    def test_non_alias_slug_is_unchanged(self) -> None:
        assert completed_sectors([{"sector_slug": "advocaten", "jobs_done": 5}]) == {"advocaten"}

    def test_a_shared_slug_completes_every_sector_using_it(self) -> None:
        """recyclagebedrijven is a config key *and* the alias for the -industrieel one.

        Both resolve to the same URL, so one run genuinely covers both. Mapping to a
        single key would leave the other pending forever.
        """
        done = completed_sectors([{"sector_slug": "recyclagebedrijven", "jobs_done": 7}])
        assert done == {"recyclagebedrijven", "recyclagebedrijven-industrieel"}


class TestCompleteRequiresEvidenceOfWork:
    """A run that never reached the site must not count as coverage.

    On 2026-08-09/10 every sector failed with net::ERR_NAME_NOT_RESOLVED — a DNS outage
    raising during warmup, before the page loop. The marker was still written, retiring
    25 real sectors (restaurants, scholen, supermarkten, tandartsen…) that had done no
    work whatsoever. `pages_scanned` only increments after a successful fetch, so it is
    the evidence that the listing was actually read.
    """

    def test_zero_page_run_is_not_coverage(self) -> None:
        rows = [{"sector_slug": "restaurants", "jobs_done": 0, "notes": "[interrupted]"}]
        assert completed_sectors(rows) == set()

    def test_a_later_good_run_still_rescues_the_sector(self) -> None:
        rows = [
            {"sector_slug": "restaurants", "jobs_done": 0, "notes": "[interrupted]"},
            {"sector_slug": "restaurants", "jobs_done": 0, "notes": "[complete]"},
        ]
        assert completed_sectors(rows) == {"restaurants"}


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
