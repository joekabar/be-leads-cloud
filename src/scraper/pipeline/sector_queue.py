"""Pick the next slice of sectors for a nightly chunked scrape.

goudengids sits behind an Imperva WAF that blocks on sustained volume rather than on
request rate alone: a 103-sector run served 8 sectors over ~30 minutes and then blocked
every subsequent sector on page 1. Scraping a small slice per night keeps each session
under that threshold, but only works if each night knows what earlier nights finished.

"Finished" deliberately means *productive*. A blocked run reached the WAF, not the data,
so it must be retried — counting it as done would skip the sector forever.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

_SQL_RECENT_RUNS = """
    SELECT sector_slug, jobs_done
    FROM run_log
    WHERE source = 'goudengids'
      AND lower(city_slug) = lower($1)
      AND started_at >= now() - ($2 || ' hours')::interval
"""


def completed_sectors(rows: Iterable[Mapping[str, Any]]) -> set[str]:
    """Sectors that actually produced observations, from ``run_log`` rows.

    ``jobs_done`` carries the observation count for the run. Zero means the sector
    yielded nothing — either genuinely empty locally, or blocked before it could read
    anything. Both are worth retrying on a later night; the WAF case especially, since
    treating a block as success would lose the sector permanently.
    """
    done: set[str] = set()
    for row in rows:
        slug = row.get("sector_slug")
        if not slug:
            continue
        if int(row.get("jobs_done") or 0) > 0:
            done.add(str(slug))
    return done


def select_pending_sectors(
    all_sectors: Sequence[str],
    *,
    done: set[str],
    limit: int,
    cycle: bool = False,
) -> list[str]:
    """Return up to *limit* sectors from *all_sectors* that are not in *done*.

    Order follows *all_sectors* so the rotation covers everything once before repeating.
    Entries in *done* that are no longer configured are ignored, so removing a sector
    from the config cannot shift the slice.

    When every sector is done, an empty list is returned — the caller can then skip the
    night's run entirely. Pass *cycle* to start the rotation over instead, for a city
    that should be refreshed continuously.
    """
    if limit <= 0:
        raise ValueError("limit must be positive")

    pending = [s for s in all_sectors if s not in done]
    if not pending and cycle:
        pending = list(all_sectors)
    return pending[:limit]


async def fetch_completed_sectors(
    pool: Any,
    city: str,
    *,
    within_hours: int = 720,
) -> set[str]:
    """Sectors already scraped productively for *city* within *within_hours*.

    The default window matches ``goudengids_skip_recent_hours`` (30 days): past that,
    listings are stale enough to be worth re-scraping.
    """
    rows = await pool.fetch(_SQL_RECENT_RUNS, city, str(within_hours))
    return completed_sectors(rows)
