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


def _completed_window_clause(within_hours: int | None) -> str:
    """Return the time predicate for 'already done', or "" for all-time.

    All-time is the default: a sector scraped once stays done until someone explicitly
    asks for a refresh. The previous 720-hour window silently re-queued every sector
    after 30 days, which is harmless for a single city but stops an eleven-city rotation
    ever completing — early cities re-enter the queue before the last one is reached.

    ``0`` means all-time too, not "nothing is done". Interpolating it into the interval
    would produce ``started_at >= now()``, marking every sector pending forever — the
    exact inversion of what a caller passing 0 intends.
    """
    if not within_hours or within_hours <= 0:
        return ""
    return " AND started_at >= now() - ($2 || ' hours')::interval"


_SQL_RECENT_RUNS = """
    SELECT sector_slug, jobs_done, notes
    FROM run_log
    WHERE source = 'goudengids'
      AND lower(city_slug) = lower($1)
"""

_SQL_COMPLETED_BY_CITY = """
    SELECT lower(city_slug) AS city, sector_slug, jobs_done, notes
    FROM run_log
    WHERE source = 'goudengids'
      AND lower(city_slug) = ANY($1::text[])
"""


#: Written to ``run_log.notes`` by a goudengids run that read its listing to the end.
COMPLETE_MARKER = "[complete]"
#: Written when a run was cut short by an Imperva block or a page timeout.
INTERRUPTED_MARKER = "[interrupted]"


def completed_sectors(rows: Iterable[Mapping[str, Any]]) -> set[str]:
    """Sectors already covered for a city, from ``run_log`` rows.

    A sector counts as done when a run either produced observations **or** finished
    without being cut short. Productivity alone is the wrong test: "obs=0" conflates
    three unrelated outcomes and only one of them deserves a retry.

    - *No local businesses.* goudengids pads a thin local search with nationwide
      results, so ``machinebouwers`` returned 500 cards of which all 500 were outside
      Oostende. It can never yield a local lead, yet it re-ran twice a day forever.
    - *Already covered.* ``bouwbedrijven`` had 84 in-city cards pass the postcode filter
      and still insert nothing, because those firms were already known from other
      sectors. Complete, not failed.
    - *Blocked or timed out.* The genuine retry case, and the only one now retried.

    Nine of ten nightly slots were stuck on the first two, and the Oostende export sat at
    220 kB for three days while still spending the full WAF budget each night.

    Rows with no marker fall back to the old productivity rule, so historical runs stay
    valid: an unproductive legacy row is ambiguous and simply earns one more attempt,
    which then records a marker.
    """
    aliases = _goudengids_slug_to_config_key()
    done: set[str] = set()
    for row in rows:
        slug = row.get("sector_slug")
        if not slug:
            continue
        notes = str(row.get("notes") or "")
        if INTERRUPTED_MARKER in notes:
            continue
        if COMPLETE_MARKER in notes or int(row.get("jobs_done") or 0) > 0:
            # run_log stores the URL slug; the queue works in config keys. A slug shared
            # by several sectors completes all of them — same URL, same data.
            done.update(aliases.get(str(slug), {str(slug)}))
    return done


def _goudengids_slug_to_config_key() -> dict[str, set[str]]:
    """Map each goudengids slug back to every config sector key that uses it.

    One-to-many on purpose: `recyclagebedrijven` and `recyclagebedrijven-industrieel`
    resolve to the same goudengids slug, so a run under it fetches identical URLs and
    genuinely covers both. Returning only one would leave the other stuck forever.

    ``run_log.sector_slug`` records the slug used in the **URL**, not the config key:
    ``_run_goudengids_sector`` resolves ``bouwbedrijven`` to ``aannemers`` before calling
    the ingester. Six sectors differ that way — bouwbedrijven/aannemers,
    logistiekverleners/logistiek, machinebouwers/machinebouw,
    metaalverwerkingsbedrijven/metaalbewerking, recyclagebedrijven-industrieel/
    recyclagebedrijven and transportbedrijven-zwaar/vrachttransport — and every one of
    them was therefore invisible to the queue, which compares against config keys. They
    could never be marked done however much they produced, so they occupied a slot on
    every run indefinitely.
    """
    import tomllib

    from scraper.lib.data_paths import SECTORS_TOML

    with SECTORS_TOML.open("rb") as fh:
        data = tomllib.load(fh)

    mapping: dict[str, set[str]] = {}
    for key, entry in data.items():
        if not isinstance(entry, dict) or entry.get("goudengids_sector_not_indexed"):
            continue
        for field in ("nl_slug", "fr_slug"):
            slug = str(entry.get(field) or "").strip()
            if slug:
                mapping.setdefault(slug, set()).add(key)
    return mapping


def goudengids_unscrapeable_sectors(all_sectors: Iterable[str]) -> set[str]:
    """Sectors goudengids cannot serve at all, so no night can ever complete them.

    Either the sector carries ``goudengids_sector_not_indexed`` in ``sectors.toml`` or it
    has no goudengids entry at all; both leave no listing URL to fetch.

    This is the case ``completed_sectors`` deliberately does *not* cover. Its rule —
    productive or retry — is correct for a blocked sector, but a sector that does not
    exist on the site yields zero forever, so "retry" means "occupy a slot every night".
    On 2026-07-30 ``afvalverwerkingsindustrie`` and ``automobielfabrieken`` did exactly
    that, sitting at the head of the queue after logging ``goudengids_sector_not_indexed``.
    """
    from scraper.pipeline.batch import _resolve_goudengids_slug

    return {s for s in all_sectors if _resolve_goudengids_slug(s, "nl") is None}


def select_pending_sectors(
    all_sectors: Sequence[str],
    *,
    done: set[str],
    limit: int,
    cycle: bool = False,
    unscrapeable: Iterable[str] = frozenset(),
) -> list[str]:
    """Return up to *limit* sectors from *all_sectors* that are not in *done*.

    Order follows *all_sectors* so the rotation covers everything once before repeating.
    Entries in *done* that are no longer configured are ignored, so removing a sector
    from the config cannot shift the slice.

    Sectors in *unscrapeable* are dropped outright: they can never become done, so
    leaving them in would hand them a slot every night in perpetuity. Unlike *done*, this
    exclusion also survives *cycle* — restarting the rotation must not resurrect them.

    When every sector is done, an empty list is returned — the caller can then skip the
    night's run entirely. Pass *cycle* to start the rotation over instead, for a city
    that should be refreshed continuously.
    """
    if limit <= 0:
        raise ValueError("limit must be positive")

    dead = set(unscrapeable)
    candidates = [s for s in all_sectors if s not in dead]

    pending = [s for s in candidates if s not in done]
    if not pending and cycle:
        pending = list(candidates)
    return pending[:limit]


async def fetch_completed_sectors(
    pool: Any,
    city: str,
    *,
    within_hours: int | None = None,
) -> set[str]:
    """Sectors already scraped productively for *city*.

    Defaults to all-time — refresh only on command. Pass *within_hours* to reinstate a
    rolling window (e.g. 720 for the old 30-day behaviour).
    """
    clause = _completed_window_clause(within_hours)
    if clause:
        rows = await pool.fetch(_SQL_RECENT_RUNS + clause, city, str(within_hours))
    else:
        rows = await pool.fetch(_SQL_RECENT_RUNS, city)
    return completed_sectors(rows)


async def fetch_completed_by_city(
    pool: Any,
    cities: Sequence[str],
    *,
    within_hours: int | None = None,
) -> dict[str, set[str]]:
    """Return ``{city: {productively scraped sectors}}`` in one round trip."""
    lowered = [c.lower() for c in cities]
    clause = _completed_window_clause(within_hours)
    if clause:
        rows = await pool.fetch(_SQL_COMPLETED_BY_CITY + clause, lowered, str(within_hours))
    else:
        rows = await pool.fetch(_SQL_COMPLETED_BY_CITY, lowered)

    by_city: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        by_city.setdefault(str(row["city"]), []).append(row)
    return {city: completed_sectors(rs) for city, rs in by_city.items()}


def select_next_city(
    cities: Sequence[str],
    all_sectors: Sequence[str],
    completed_by_city: Mapping[str, set[str]],
    *,
    unscrapeable: Iterable[str] = frozenset(),
) -> str | None:
    """First city in *cities* order that still has a scrapeable sector outstanding.

    The rotation deliberately finishes one city before starting the next: a complete
    city is a sellable dataset, whereas eleven half-scraped cities are not. Sectors in
    *unscrapeable* are ignored, so a city whose only remaining entries can never be
    served counts as finished rather than pinning the rotation forever.

    Returns ``None`` when every city is complete, letting the caller skip the run.
    """
    dead = set(unscrapeable)
    for city in cities:
        done = completed_by_city.get(city.lower(), set())
        if any(s not in done and s not in dead for s in all_sectors):
            return city
    return None


def load_rotation_cities() -> list[str]:
    """Ordered city rotation from the bundled ``scrape_cities.toml``."""
    import tomllib

    from scraper.lib.data_paths import SCRAPE_CITIES_TOML

    with SCRAPE_CITIES_TOML.open("rb") as fh:
        data = tomllib.load(fh)
    rotation = data.get("rotation", {})
    return [str(c) for c in rotation.get("cities", [])]
