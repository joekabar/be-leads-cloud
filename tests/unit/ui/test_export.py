from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from scraper.ui.export import _COLUMNS, _tier, export_csv


class TestTier:
    @pytest.mark.parametrize(
        "hv, expected",
        [
            (1.00, "T1"),
            (0.80, "T1"),
            (0.79, "T2"),
            (0.55, "T2"),
            (0.54, "T3"),
            (0.30, "T3"),
            (0.29, "T4"),
            (0.00, "T4"),
        ],
    )
    def test_tier_boundaries(self, hv: float, expected: str) -> None:
        assert _tier(hv) == expected


class TestExportCsv:
    def _make_pool(
        self,
        kbos: list[str],
        obs_rows: list[dict[str, Any]],
        ps_rows: list[dict[str, Any]],
        fin_rows: list[dict[str, Any]],
        addr_rows: list[dict[str, Any]],
    ) -> MagicMock:
        pool = MagicMock()

        async def _fetch(sql: str, *args: Any, **kwargs: Any) -> list[Any]:
            if (
                "observations WHERE run_id" in sql
                or "DISTINCT kbo_number FROM companies_current" in sql
            ):
                return [{"kbo_number": k} for k in kbos]
            if "FROM observations " in sql and "char(10)" in sql and "revenue_" in sql:
                return list(fin_rows)
            if "FROM observations " in sql and "char(10)" in sql:
                return list(obs_rows)
            if "FROM prospect_scores" in sql:
                return list(ps_rows)
            if "FROM companies_current" in sql and "address" in sql:
                return list(addr_rows)
            return []

        pool.fetch = AsyncMock(side_effect=_fetch)
        return pool

    async def test_columns_present(self, tmp_path: Path) -> None:
        out = tmp_path / "leads.csv"

        from scraper.db.models import Observation

        obs = Observation(
            kbo_number="9000000001",
            field="name",
            value={"text": "Acme"},
            raw_value=None,
            source="kbo_dump",
            source_url=None,
            observed_at=datetime.now(tz=UTC),
            confidence=0.95,
            run_id=uuid4(),
        )

        with patch("scraper.ui.export._row_to_obs", return_value=obs):
            pool = self._make_pool(
                kbos=["9000000001"],
                obs_rows=[
                    {
                        "kbo_number": "9000000001",
                        "field": "name",
                        "value": {"text": "Acme"},
                        "raw_value": None,
                        "source": "kbo_dump",
                        "source_url": None,
                        "observed_at": datetime.now(tz=UTC),
                        "confidence": 0.95,
                        "run_id": uuid4(),
                        "id": 1,
                    }
                ],
                ps_rows=[
                    {
                        "kbo_number": "9000000001",
                        "hv_probability": 0.95,
                        "business_activity": 1.0,
                        "contact_quality": 0.667,
                        "growth_signal": 0.0,
                        "overall_prospect": 0.72,
                    }
                ],
                fin_rows=[],
                addr_rows=[
                    {
                        "kbo_number": "9000000001",
                        "value": {"postal_code": "2000", "city": "Antwerpen"},
                    }
                ],
            )
            n = await export_csv(pool, out)

        assert n == 1
        assert out.exists()
        with out.open(encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            assert reader.fieldnames == _COLUMNS
            rows = list(reader)
        assert len(rows) == 1

    async def test_sorted_by_overall_prospect_desc(self, tmp_path: Path) -> None:
        out = tmp_path / "leads.csv"

        from scraper.db.models import Observation

        def make_obs(kbo: str) -> Observation:
            return Observation(
                kbo_number=kbo,
                field="name",
                value={"text": f"Company {kbo}"},
                raw_value=None,
                source="kbo_dump",
                source_url=None,
                observed_at=datetime.now(tz=UTC),
                confidence=0.9,
                run_id=uuid4(),
            )

        kbo_list = ["9000000001", "9000000002", "9000000003"]

        with patch(
            "scraper.ui.export._row_to_obs",
            side_effect=lambda r: make_obs(str(r["kbo_number"]).strip()),
        ):
            pool = self._make_pool(
                kbos=kbo_list,
                obs_rows=[
                    {
                        "kbo_number": k,
                        "field": "name",
                        "value": {"text": f"C{k}"},
                        "raw_value": None,
                        "source": "kbo_dump",
                        "source_url": None,
                        "observed_at": datetime.now(tz=UTC),
                        "confidence": 0.9,
                        "run_id": uuid4(),
                        "id": i,
                    }
                    for i, k in enumerate(kbo_list)
                ],
                ps_rows=[
                    {
                        "kbo_number": "9000000001",
                        "hv_probability": 0.30,
                        "business_activity": 0.5,
                        "contact_quality": 0.0,
                        "growth_signal": 0.0,
                        "overall_prospect": 0.235,
                    },
                    {
                        "kbo_number": "9000000002",
                        "hv_probability": 1.00,
                        "business_activity": 1.0,
                        "contact_quality": 1.0,
                        "growth_signal": 0.0,
                        "overall_prospect": 0.8,
                    },
                    {
                        "kbo_number": "9000000003",
                        "hv_probability": 0.65,
                        "business_activity": 0.5,
                        "contact_quality": 0.33,
                        "growth_signal": 0.0,
                        "overall_prospect": 0.43,
                    },
                ],
                fin_rows=[],
                addr_rows=[],
            )
            await export_csv(pool, out)

        with out.open(encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            rows = list(reader)

        prospects = [float(r["overall_prospect"]) for r in rows]
        assert prospects == sorted(prospects, reverse=True)

    async def test_null_becomes_empty_string(self, tmp_path: Path) -> None:
        out = tmp_path / "leads.csv"

        from scraper.db.models import Observation

        obs = Observation(
            kbo_number="9000000001",
            field="name",
            value={"text": ""},
            raw_value=None,
            source="kbo_dump",
            source_url=None,
            observed_at=datetime.now(tz=UTC),
            confidence=0.9,
            run_id=uuid4(),
        )

        with patch("scraper.ui.export._row_to_obs", return_value=obs):
            pool = self._make_pool(
                kbos=["9000000001"],
                obs_rows=[
                    {
                        "kbo_number": "9000000001",
                        "field": "name",
                        "value": {"text": ""},
                        "raw_value": None,
                        "source": "kbo_dump",
                        "source_url": None,
                        "observed_at": datetime.now(tz=UTC),
                        "confidence": 0.9,
                        "run_id": uuid4(),
                        "id": 1,
                    }
                ],
                ps_rows=[],
                fin_rows=[],
                addr_rows=[],
            )
            await export_csv(pool, out)

        with out.open(encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            rows = list(reader)

        assert len(rows) == 1
        for col in ["revenue_2023", "revenue_2024", "employees_2024"]:
            assert rows[0][col] == ""
        # score fields default to "0.0" when no prospect row exists
        assert rows[0]["hv_probability"] == "0.0"

    async def test_empty_kbo_list_writes_empty_csv(self, tmp_path: Path) -> None:
        out = tmp_path / "leads.csv"

        pool = MagicMock()
        pool.fetch = AsyncMock(return_value=[])

        n = await export_csv(pool, out)
        assert n == 0
        assert out.read_text(encoding="utf-8") == ""

    async def test_run_id_uses_observations_query(self, tmp_path: Path) -> None:
        out = tmp_path / "leads.csv"
        rid = uuid4()

        async def _fetch(sql: str, *args: Any, **kwargs: Any) -> list[Any]:
            if "observations WHERE run_id" in sql:
                return []
            return []

        pool = MagicMock()
        pool.fetch = AsyncMock(side_effect=_fetch)

        n = await export_csv(pool, out, run_id=rid)
        assert n == 0
        first_call_sql = pool.fetch.call_args_list[0][0][0]
        assert "observations WHERE run_id" in first_call_sql

    async def test_financial_rows_populate_columns(self, tmp_path: Path) -> None:
        out = tmp_path / "leads.csv"

        from scraper.db.models import Observation

        obs = Observation(
            kbo_number="9000000001",
            field="name",
            value={"text": "Acme"},
            raw_value=None,
            source="kbo_dump",
            source_url=None,
            observed_at=datetime.now(tz=UTC),
            confidence=0.95,
            run_id=uuid4(),
        )

        with patch("scraper.ui.export._row_to_obs", return_value=obs):
            pool = self._make_pool(
                kbos=["9000000001"],
                obs_rows=[
                    {
                        "kbo_number": "9000000001",
                        "field": "name",
                        "value": {"text": "Acme"},
                        "raw_value": None,
                        "source": "kbo_dump",
                        "source_url": None,
                        "observed_at": datetime.now(tz=UTC),
                        "confidence": 0.95,
                        "run_id": uuid4(),
                        "id": 1,
                    }
                ],
                ps_rows=[],
                fin_rows=[
                    {
                        "kbo_number": "9000000001",
                        "field": "revenue_2023",
                        "value": {"eur": 1500000},
                    }
                ],
                addr_rows=[],
            )
            await export_csv(pool, out)

        with out.open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert len(rows) == 1
        assert rows[0]["revenue_2023"] == "1500000.0"

    async def test_kbo_with_no_obs_is_skipped(self, tmp_path: Path) -> None:
        out = tmp_path / "leads.csv"

        async def _fetch(sql: str, *args: Any, **kwargs: Any) -> list[Any]:
            if "DISTINCT kbo_number FROM companies_current" in sql:
                return [{"kbo_number": "9000000001"}, {"kbo_number": "9000000002"}]
            if "FROM observations " in sql and "char(10)" in sql and "revenue_" not in sql:
                # Only return obs for the first KBO; second has none
                return [
                    {
                        "kbo_number": "9000000001",
                        "field": "name",
                        "value": {"text": "Acme"},
                        "raw_value": None,
                        "source": "kbo_dump",
                        "source_url": None,
                        "observed_at": datetime.now(tz=UTC),
                        "confidence": 0.95,
                        "run_id": uuid4(),
                        "id": 1,
                    }
                ]
            return []

        from scraper.db.models import Observation

        obs = Observation(
            kbo_number="9000000001",
            field="name",
            value={"text": "Acme"},
            raw_value=None,
            source="kbo_dump",
            source_url=None,
            observed_at=datetime.now(tz=UTC),
            confidence=0.95,
            run_id=uuid4(),
        )

        pool = MagicMock()
        pool.fetch = AsyncMock(side_effect=_fetch)

        with patch("scraper.ui.export._row_to_obs", return_value=obs):
            n = await export_csv(pool, out)

        # Second KBO had no obs → skipped; only first KBO written
        assert n == 1
