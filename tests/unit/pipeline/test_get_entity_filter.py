from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock

from scraper.pipeline.batch import get_entity_filter


class TestGetEntityFilter:
    def _make_pool(self, return_value: list[dict]) -> MagicMock:
        pool = MagicMock()
        pool.fetch = AsyncMock(return_value=[MagicMock(**r) for r in return_value])
        return pool

    async def test_postal_code_path_for_known_city(self) -> None:
        pool = MagicMock()
        pool.fetch = AsyncMock(return_value=[])
        await get_entity_filter(pool, date(2024, 1, 1), "antwerpen", [])
        call_sql = pool.fetch.call_args[0][0]
        assert "zipcode = ANY" in call_sql
        assert "municipality_nl" not in call_sql

    async def test_municipality_fallback_for_unknown_city(self) -> None:
        pool = MagicMock()
        pool.fetch = AsyncMock(return_value=[])
        await get_entity_filter(pool, date(2024, 1, 1), "unknown_city_xyz", [])
        call_sql = pool.fetch.call_args[0][0]
        assert "municipality_nl" in call_sql
        assert "zipcode = ANY" not in call_sql
