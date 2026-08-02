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


class TestMatchedPlaceholdersAreNotExportedTwice:
    """A consolidated placeholder must not appear beside the real KBO it merged into.

    Consolidation re-emits a placeholder's observations under the matched real KBO but
    never deletes the placeholder -- observations are append-only. The export then
    selected both, so the same company shipped twice: once as 9001582028 (phone, no
    NACE) and once as 1028670251 (phone, NACE 49420). Measured on the 2026-08-01
    Oostende export: 559 of 1,674 rows were the redundant half of a matched pair, so
    the file overstated the lead count by a third.

    The placeholder is the half to drop: the real KBO carries the same contact data plus
    everything the registry knows.
    """

    def _pool(self, kbos: list[str], matched_placeholders: dict[str, str]) -> MagicMock:
        pool = MagicMock()

        async def _fetch(sql: str, *args: Any, **kwargs: Any) -> list[Any]:
            if "consolidation_state" in sql:
                return [
                    {"placeholder_kbo": p, "real_kbo": r} for p, r in matched_placeholders.items()
                ]
            if "DISTINCT kbo_number FROM companies_current" in sql:
                return [{"kbo_number": k} for k in kbos]
            if "FROM observations " in sql and "revenue_" in sql:
                return []
            if "FROM observations " in sql:
                # One name observation per surviving KBO, so the row is not skipped.
                return [{"kbo_number": k, "field": "name", "value": {"text": k}} for k in kbos]
            return []

        pool.fetch = AsyncMock(side_effect=_fetch)
        return pool

    async def test_matched_placeholder_is_dropped(self, tmp_path: Path) -> None:
        from scraper.db.models import Observation

        obs = Observation(
            kbo_number="0439401387",
            field="name",
            value={"text": "Acme"},
            raw_value=None,
            source="kbo_dump",
            observed_at=datetime.now(tz=UTC),
            confidence=0.95,
            run_id=uuid4(),
            source_url=None,
        )
        pool = self._pool(
            ["9000000001", "0439401387"],
            matched_placeholders={"9000000001": "0439401387"},
        )
        out = tmp_path / "leads.csv"
        with patch("scraper.ui.export._row_to_obs", return_value=obs):
            await export_csv(pool, out)

        with out.open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        exported = {r["kbo_number"] for r in rows}
        assert "9000000001" not in exported, "matched placeholder must not be exported"

    async def test_unmatched_placeholder_is_kept(self, tmp_path: Path) -> None:
        """An unmatched placeholder is the only record of that company -- keep it."""
        from scraper.db.models import Observation

        obs = Observation(
            kbo_number="9000000002",
            field="name",
            value={"text": "Unmatched BV"},
            raw_value=None,
            source="goudengids",
            observed_at=datetime.now(tz=UTC),
            confidence=0.8,
            run_id=uuid4(),
            source_url=None,
        )
        pool = self._pool(["9000000002"], matched_placeholders={})
        out = tmp_path / "leads.csv"
        with patch("scraper.ui.export._row_to_obs", return_value=obs):
            await export_csv(pool, out)

        with out.open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert {r["kbo_number"] for r in rows} == {"9000000002"}

    async def test_matched_placeholder_is_kept_when_its_twin_is_not_selected(
        self, tmp_path: Path
    ) -> None:
        """Dropping it would orphan the company: no row would represent it at all.

        A company listed on goudengids in Oostende can be registered elsewhere, so a
        city-filtered export selects the placeholder but not the real KBO. Removing
        matched placeholders unconditionally orphaned 147 real leads — 13% of the file.
        """
        from scraper.db.models import Observation

        obs = Observation(
            kbo_number="9000000003",
            field="name",
            value={"text": "Listed here, registered elsewhere"},
            raw_value=None,
            source="goudengids",
            observed_at=datetime.now(tz=UTC),
            confidence=0.8,
            run_id=uuid4(),
            source_url=None,
        )
        # The placeholder is matched, but its real twin is outside this selection.
        pool = self._pool(["9000000003"], matched_placeholders={"9000000003": "0439401387"})
        out = tmp_path / "leads.csv"
        with patch("scraper.ui.export._row_to_obs", return_value=obs):
            await export_csv(pool, out)

        with out.open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert {r["kbo_number"] for r in rows} == {"9000000003"}

    async def test_real_kbos_are_never_filtered(self, tmp_path: Path) -> None:
        from scraper.db.models import Observation

        obs = Observation(
            kbo_number="0439401387",
            field="name",
            value={"text": "Acme"},
            raw_value=None,
            source="kbo_dump",
            observed_at=datetime.now(tz=UTC),
            confidence=0.95,
            run_id=uuid4(),
            source_url=None,
        )
        pool = self._pool(["0439401387"], matched_placeholders={"9000000001": "0439401387"})
        out = tmp_path / "leads.csv"
        with patch("scraper.ui.export._row_to_obs", return_value=obs):
            await export_csv(pool, out)

        with out.open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert {r["kbo_number"] for r in rows} == {"0439401387"}


class TestActivityColumns:
    """The CSV must say what a company does, not just which code it is filed under.

    `nace_code` alone ("43320") is unreadable. `nace_label` translates it via the
    official KBO code table; `activity_summary` carries the website-derived sentence
    where enrichment found one (only ~875 companies of 1.96M, so it is often blank).
    """

    def _pool_for(self, obs_specs: list[tuple[str, dict[str, Any]]]) -> MagicMock:
        """Build a pool serving one KBO whose observations are *obs_specs*."""
        from scraper.db.models import Observation

        kbo = "9000000001"
        now = datetime.now(tz=UTC)
        observations = [
            Observation(
                kbo_number=kbo,
                field=field,
                value=value,
                raw_value=None,
                source="kbo_dump",
                source_url=None,
                observed_at=now,
                confidence=0.95,
                run_id=uuid4(),
            )
            for field, value in obs_specs
        ]

        pool = MagicMock()

        async def _fetch(sql: str, *args: Any, **kwargs: Any) -> list[Any]:
            if "DISTINCT kbo_number FROM companies_current" in sql:
                return [{"kbo_number": kbo}]
            if "FROM observations " in sql and "revenue_" in sql:
                return []
            if "FROM observations " in sql:
                return [{"kbo_number": kbo, "field": f, "value": v} for f, v in obs_specs]
            if "FROM prospect_scores" in sql:
                return []
            if "FROM companies_current" in sql and "address" in sql:
                return []
            return []

        pool.fetch = AsyncMock(side_effect=_fetch)
        return pool, observations

    async def _export_row(
        self, tmp_path: Path, obs_specs: list[tuple[str, dict[str, Any]]]
    ) -> dict[str, str]:
        out = tmp_path / "leads.csv"
        pool, observations = self._pool_for(obs_specs)
        with patch("scraper.ui.export._row_to_obs", side_effect=list(observations)):
            await export_csv(pool, out)
        with out.open(encoding="utf-8") as fh:
            return next(iter(csv.DictReader(fh)))

    async def test_both_columns_exist(self) -> None:
        assert "nace_label" in _COLUMNS
        assert "activity_summary" in _COLUMNS

    async def test_nace_code_becomes_a_readable_label(self, tmp_path: Path) -> None:
        row = await self._export_row(
            tmp_path,
            [
                ("name", {"text": "Acme"}),
                ("nace_code", {"code": "01110", "version": "2025"}),
            ],
        )
        assert row["nace_code"] == "01110"
        assert "granen" in row["nace_label"].lower()

    async def test_activity_summary_is_carried_through(self, tmp_path: Path) -> None:
        row = await self._export_row(
            tmp_path,
            [
                ("name", {"text": "Acme"}),
                ("activity_summary", {"text": "Installatie van zonnepanelen.", "lang_hint": "nl"}),
            ],
        )
        assert row["activity_summary"] == "Installatie van zonnepanelen."

    async def test_missing_nace_leaves_label_blank(self, tmp_path: Path) -> None:
        """Most leads have no activity_summary; a blank must not break the row."""
        row = await self._export_row(tmp_path, [("name", {"text": "Acme"})])
        assert row["nace_label"] == ""
        assert row["activity_summary"] == ""

    async def test_unknown_nace_code_leaves_label_blank(self, tmp_path: Path) -> None:
        row = await self._export_row(
            tmp_path,
            [
                ("name", {"text": "Acme"}),
                ("nace_code", {"code": "04999", "version": "2025"}),
            ],
        )
        assert row["nace_label"] == ""

    async def test_old_nace_version_still_resolves(self, tmp_path: Path) -> None:
        """~31k companies carry 2003/2008 codes; they must not export blank."""
        row = await self._export_row(
            tmp_path,
            [
                ("name", {"text": "Acme"}),
                ("nace_code", {"code": "01110", "version": "2008"}),
            ],
        )
        assert row["nace_label"] != ""


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

    async def test_chunk_size_zero_writes_single_file(self, tmp_path: Path) -> None:
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
                fin_rows=[],
                addr_rows=[],
            )
            result = await export_csv(pool, out, chunk_size=0)

        assert isinstance(result, int)
        assert out.exists()
        with out.open(encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            assert reader.fieldnames == _COLUMNS
            rows = list(reader)
        assert len(rows) == 1

    async def test_chunk_size_writes_multiple_files(self, tmp_path: Path) -> None:
        from scraper.db.models import Observation

        kbo_list = [f"9{i:09d}" for i in range(5001)]

        mock_obs = Observation(
            kbo_number=kbo_list[0],
            field="name",
            value={"text": "Company"},
            raw_value=None,
            source="kbo_dump",
            source_url=None,
            observed_at=datetime.now(tz=UTC),
            confidence=0.9,
            run_id=uuid4(),
        )

        obs_rows = [
            {
                "kbo_number": k,
                "field": "name",
                "value": {"text": f"Company {k}"},
                "raw_value": None,
                "source": "kbo_dump",
                "source_url": None,
                "observed_at": datetime.now(tz=UTC),
                "confidence": 0.9,
                "run_id": uuid4(),
                "id": i,
            }
            for i, k in enumerate(kbo_list)
        ]

        async def _fetch(sql: str, *args: Any, **kwargs: Any) -> list[Any]:
            if (
                "observations WHERE run_id" in sql
                or "DISTINCT kbo_number FROM companies_current" in sql
            ):
                return [{"kbo_number": k} for k in kbo_list]
            if "FROM observations " in sql and "char(10)" in sql and "revenue_" in sql:
                return []
            if "FROM observations " in sql and "char(10)" in sql:
                return obs_rows
            if "FROM prospect_scores" in sql:
                return []
            if "FROM companies_current" in sql and "address" in sql:
                return []
            return []

        pool = MagicMock()
        pool.fetch = AsyncMock(side_effect=_fetch)

        out_path = tmp_path / "chunks"

        with patch("scraper.ui.export._row_to_obs", return_value=mock_obs):
            result = await export_csv(pool, out_path, chunk_size=5000)

        assert isinstance(result, list)
        assert len(result) == 2

        part1 = out_path / "leads_part_0001.csv"
        part2 = out_path / "leads_part_0002.csv"
        assert part1 in result
        assert part2 in result

        with part1.open(encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            assert reader.fieldnames == _COLUMNS
            rows1 = list(reader)
        assert len(rows1) == 5000

        with part2.open(encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            assert reader.fieldnames == _COLUMNS
            rows2 = list(reader)
        assert len(rows2) == 1

    async def test_chunk_size_creates_output_dir(self, tmp_path: Path) -> None:
        from scraper.db.models import Observation

        kbo_list = ["9000000001"]

        mock_obs = Observation(
            kbo_number="9000000001",
            field="name",
            value={"text": "Acme"},
            raw_value=None,
            source="kbo_dump",
            source_url=None,
            observed_at=datetime.now(tz=UTC),
            confidence=0.9,
            run_id=uuid4(),
        )

        with patch("scraper.ui.export._row_to_obs", return_value=mock_obs):
            pool = self._make_pool(
                kbos=kbo_list,
                obs_rows=[
                    {
                        "kbo_number": "9000000001",
                        "field": "name",
                        "value": {"text": "Acme"},
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
            out_path = tmp_path / "new_dir"
            assert not out_path.exists()
            result = await export_csv(pool, out_path, chunk_size=1)

        assert out_path.is_dir()
        assert isinstance(result, list)
        assert len(result) == 1

    async def test_chunk_size_errors_when_out_is_existing_file(self, tmp_path: Path) -> None:
        out = tmp_path / "existing.csv"
        out.write_text("")

        pool = MagicMock()
        pool.fetch = AsyncMock(return_value=[])

        with pytest.raises(ValueError, match="--out must be a directory"):
            await export_csv(pool, out, chunk_size=5000)

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
