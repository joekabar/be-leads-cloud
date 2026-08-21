"""``cities_to_export`` — which cities the daily export should write a file for.

The export used to take a city slug on the command line. The scraper rotates
(``scrape_cities.toml``), the export did not, so when the rotation moved from Oostende to
Brugge on 2026-08-21 the scheduled task kept asking for Oostende: 2,170 exportable Brugge
leads sat in the database and reached no CSV at all.

The signal is a goudengids run, not the presence of rows. ``companies_current`` holds the
whole country from the KBO dump — every configured city has registry rows, and Brussels
has the most exportable ones (5,952) despite never having been scraped. Keying off
``run_log`` means a city appears the morning after its first scrape and never before.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from scraper.pipeline.city_map import canonical_slug
from scraper.ui.export import cities_to_export


def _pool(city_slugs: list[str | None]) -> MagicMock:
    pool = MagicMock()
    pool.fetch = AsyncMock(return_value=[{"city_slug": s} for s in city_slugs])
    return pool


class TestCitiesToExport:
    async def test_returns_scraped_cities_sorted(self) -> None:
        assert await cities_to_export(_pool(["oostende", "brugge"])) == ["brugge", "oostende"]

    async def test_case_variants_collapse_to_one_city(self) -> None:
        """run_log holds both "oostende" and "Oostende" from before slug normalisation."""
        assert await cities_to_export(_pool(["Oostende", "oostende"])) == ["oostende"]

    async def test_aliases_collapse_to_the_canonical_slug(self) -> None:
        assert await cities_to_export(_pool(["ghent", "gent"])) == ["gent"]
        assert await cities_to_export(_pool(["luik"])) == ["liege"]

    async def test_unknown_slug_is_skipped_not_guessed(self) -> None:
        """A slug with no postcodes would widen the export to the whole country."""
        assert await cities_to_export(_pool(["oostende", "atlantis"])) == ["oostende"]

    async def test_null_slug_is_skipped(self) -> None:
        """Enrichment-only runs carry no city."""
        assert await cities_to_export(_pool([None, "brugge"])) == ["brugge"]

    async def test_no_runs_returns_empty_list(self) -> None:
        assert await cities_to_export(_pool([])) == []

    async def test_queries_goudengids_runs_only(self) -> None:
        """A kbo_dump run covers the whole country and names no city worth exporting."""
        pool = _pool(["oostende"])
        await cities_to_export(pool)
        sql = pool.fetch.await_args[0][0]
        assert "run_log" in sql
        assert "goudengids" in sql


class TestEveryDiscoveredCityCanBeExported:
    """Whatever this returns is fed straight to resolve_city_postcodes()."""

    async def test_discovered_slugs_resolve_to_postcodes(self) -> None:
        from scraper.ui.export import resolve_city_postcodes

        pool = _pool(["oostende", "brugge", "Oostende", "ghent", "atlantis", None])
        discovered = await cities_to_export(pool)
        assert discovered == ["brugge", "gent", "oostende"]
        for slug in discovered:
            assert resolve_city_postcodes([slug]), f"{slug} resolves to no postcodes"


class TestCanonicalSlug:
    @pytest.mark.parametrize(
        ("given", "expected"),
        [
            ("oostende", "oostende"),
            ("Oostende", "oostende"),
            ("  BRUGGE  ", "brugge"),
            ("ghent", "gent"),
            ("luik", "liege"),
            ("bergen", "mons"),
            ("namen", "namur"),
            ("atlantis", None),
            ("", None),
        ],
    )
    def test_folds_case_whitespace_and_aliases(self, given: str, expected: str | None) -> None:
        assert canonical_slug(given) == expected
