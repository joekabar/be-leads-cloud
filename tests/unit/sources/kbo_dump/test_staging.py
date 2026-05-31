"""Unit tests for kbo_dump/staging.py — stage_zip, payload building, drift, indexes."""

from __future__ import annotations

import itertools
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from scraper.sources.kbo_dump import staging
from scraper.sources.kbo_dump.parser import (
    ActivityRow,
    AddressRow,
    ContactRow,
    DenominationRow,
    EnterpriseRow,
)
from scraper.sources.kbo_dump.staging import (
    StagingReport,
    _build_activity_shard,
    _build_payload_file,
    _compute_shards,
    _copy_file,
    _detect_drift,
    stage_zip,
)

# ── helpers ───────────────────────────────────────────────────────────────────


def _make_tx() -> MagicMock:
    tx = MagicMock()
    tx.__aenter__ = AsyncMock(return_value=None)
    tx.__aexit__ = AsyncMock(return_value=False)
    return tx


def _make_pool() -> tuple[MagicMock, MagicMock]:
    conn = MagicMock()
    conn.copy_to_table = AsyncMock()
    conn.execute = AsyncMock(return_value="DELETE 5")
    conn.transaction = MagicMock(return_value=_make_tx())

    acquire_cm = MagicMock()
    acquire_cm.__aenter__ = AsyncMock(return_value=conn)
    acquire_cm.__aexit__ = AsyncMock(return_value=False)

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=acquire_cm)
    pool.fetchval = AsyncMock(return_value=None)
    pool.fetch = AsyncMock(return_value=[])

    return pool, conn


def _delete_call_count(conn: MagicMock) -> int:
    return sum(
        1
        for call in conn.execute.await_args_list
        if call.args and "DELETE FROM" in str(call.args[0])
    )


def _fake_enterprise() -> EnterpriseRow:
    return EnterpriseRow(
        enterprise_number="0403019261",
        status="Active",
        juridical_situation="AC",
        type_of_enterprise="2",
        juridical_form="014",
        juridical_form_cac=None,
        start_date=date(2000, 1, 1),
    )


def _fake_address() -> AddressRow:
    return AddressRow(
        entity_number="0403019261",
        type_of_address="REGO",
        zipcode="1000",
        municipality_nl="Brussel",
        municipality_fr="Bruxelles",
        street_nl="Teststraat",
        street_fr="Rue Test",
        house_number="1",
        box=None,
    )


def _fake_denomination() -> DenominationRow:
    return DenominationRow(
        entity_number="0403019261",
        language="NL",
        type_of_denomination="001",
        denomination="Test NV",
    )


def _fake_contact() -> ContactRow:
    return ContactRow(
        entity_number="0403019261",
        contact_type="WEB",
        value="https://test.be",
    )


def _fake_activity() -> ActivityRow:
    return ActivityRow(
        entity_number="0403019261",
        activity_group="MAIN",
        nace_version="2008",
        nace_code="43211",
        classification="NACE2008",
    )


def _enter_empty_patches(stack: ExitStack, snapshot_date: str = "01-01-2024") -> None:
    stack.enter_context(
        patch(
            "scraper.sources.kbo_dump.staging.parse_meta",
            return_value={"SnapshotDate": snapshot_date},
        )
    )
    for name in (
        "iter_enterprises",
        "iter_addresses",
        "iter_denominations",
        "iter_contacts",
        "iter_activities",
    ):
        stack.enter_context(
            patch(f"scraper.sources.kbo_dump.staging.{name}", return_value=iter([]))
        )


# ── _build_payload_file ─────────────────────────────────────────────────────────


class TestBuildPayloadFile:
    def test_enterprise_one_row(self, tmp_path: Path) -> None:
        with patch(
            "scraper.sources.kbo_dump.staging.iter_enterprises",
            return_value=iter([_fake_enterprise()]),
        ):
            path, n = _build_payload_file(
                Path("/fake.zip"), "enterprise", "2024-01-01", str(tmp_path)
            )
        assert n == 1
        content = Path(path).read_text(encoding="utf-8")
        assert content.count("\n") == 1
        assert content.startswith("0403019261\t2024-01-01\t")

    def test_null_start_date_writes_backslash_n(self, tmp_path: Path) -> None:
        ent = EnterpriseRow(
            enterprise_number="0403019261",
            status="Active",
            juridical_situation="AC",
            type_of_enterprise="2",
            juridical_form=None,
            juridical_form_cac=None,
            start_date=None,
        )
        with patch(
            "scraper.sources.kbo_dump.staging.iter_enterprises",
            return_value=iter([ent]),
        ):
            path, n = _build_payload_file(
                Path("/fake.zip"), "enterprise", "2024-01-01", str(tmp_path)
            )
        assert n == 1
        # juridical_form and start_date are NULL → represented as \N
        assert r"\N" in Path(path).read_text(encoding="utf-8")

    def test_empty_iter_returns_zero(self, tmp_path: Path) -> None:
        with patch(
            "scraper.sources.kbo_dump.staging.iter_activities",
            return_value=iter([]),
        ):
            path, n = _build_payload_file(
                Path("/fake.zip"), "activity", "2024-01-01", str(tmp_path)
            )
        assert n == 0
        assert Path(path).read_text(encoding="utf-8") == ""

    def test_address_row_field_order(self, tmp_path: Path) -> None:
        with patch(
            "scraper.sources.kbo_dump.staging.iter_addresses",
            return_value=iter([_fake_address()]),
        ):
            path, n = _build_payload_file(Path("/fake.zip"), "address", "2024-01-01", str(tmp_path))
        assert n == 1
        cols = Path(path).read_text(encoding="utf-8").rstrip("\n").split("\t")
        # entity_number, snapshot_date, type_of_address, zipcode, municipality_nl, ...
        assert cols[0] == "0403019261"
        assert cols[1] == "2024-01-01"
        assert cols[3] == "1000"


# ── _copy_file ───────────────────────────────────────────────────────────────


class TestCopyFile:
    async def test_calls_copy_to_table(self, tmp_path: Path) -> None:
        conn = MagicMock()
        conn.copy_to_table = AsyncMock()
        p = tmp_path / "x.tsv"
        p.write_text("a\tb\n", encoding="utf-8")
        await _copy_file(conn, "tbl", ["c1", "c2"], str(p))
        conn.copy_to_table.assert_called_once()


# ── _detect_drift ──────────────────────────────────────────────────────────────


class TestDetectDrift:
    def test_warns_on_new_column(self, tmp_path: Path) -> None:
        zip_path = tmp_path / "k.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr(
                "enterprise.csv",
                "EnterpriseNumber,Status,NewColumn\n0403019261,AC,x\n",
            )
        with patch.object(staging.logger, "warning") as warn:
            _detect_drift(zip_path)
        assert any("NewColumn" in str(c) for c in warn.call_args_list)

    def test_no_warning_when_columns_expected(self, tmp_path: Path) -> None:
        zip_path = tmp_path / "k.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("contact.csv", "EntityNumber,ContactType,Value\n0403019261,WEB,x\n")
        with patch.object(staging.logger, "warning") as warn:
            _detect_drift(zip_path)
        assert warn.call_count == 0

    def test_missing_zip_is_noop(self) -> None:
        # read_csv_header swallows OSError → no warning, no raise.
        with patch.object(staging.logger, "warning") as warn:
            _detect_drift(Path("/does/not/exist.zip"))
        assert warn.call_count == 0


# ── stage_zip ─────────────────────────────────────────────────────────────────


class TestStageZip:
    async def test_skips_when_already_staged(self) -> None:
        pool, _conn = _make_pool()
        pool.fetchval = AsyncMock(return_value=1)

        with ExitStack() as stack:
            _enter_empty_patches(stack)
            report = await stage_zip(Path("/fake.zip"), pool)

        assert report.skipped is True

    async def test_bad_snapshot_date_falls_back_to_today(self) -> None:
        pool, _conn = _make_pool()

        with ExitStack() as stack, ThreadPoolExecutor(max_workers=2) as ex:
            _enter_empty_patches(stack, snapshot_date="not-a-date")
            report = await stage_zip(Path("/fake.zip"), pool, executor=ex)

        assert isinstance(report, StagingReport)
        assert not report.skipped

    async def test_force_delete_issues_delete_per_table(self) -> None:
        pool, conn = _make_pool()
        pool.fetchval = AsyncMock(return_value=1)

        with ExitStack() as stack, ThreadPoolExecutor(max_workers=2) as ex:
            _enter_empty_patches(stack)
            report = await stage_zip(Path("/fake.zip"), pool, force=True, executor=ex)

        assert not report.skipped
        assert _delete_call_count(conn) == 5

    async def test_empty_zip_returns_zero_rows(self) -> None:
        pool, conn = _make_pool()

        with ExitStack() as stack, ThreadPoolExecutor(max_workers=2) as ex:
            _enter_empty_patches(stack)
            report = await stage_zip(Path("/fake.zip"), pool, executor=ex)

        assert report.rows_enterprise == 0
        assert report.rows_address == 0
        assert report.rows_denomination == 0
        assert report.rows_contact == 0
        assert report.rows_activity == 0
        assert not report.skipped
        # No rows → no COPY.
        conn.copy_to_table.assert_not_called()

    async def test_one_of_each_row_staged(self) -> None:
        pool, conn = _make_pool()

        with ExitStack() as stack, ThreadPoolExecutor(max_workers=3) as ex:
            stack.enter_context(
                patch(
                    "scraper.sources.kbo_dump.staging.parse_meta",
                    return_value={"SnapshotDate": "01-01-2024"},
                )
            )
            stack.enter_context(
                patch(
                    "scraper.sources.kbo_dump.staging.iter_enterprises",
                    return_value=iter([_fake_enterprise()]),
                )
            )
            stack.enter_context(
                patch(
                    "scraper.sources.kbo_dump.staging.iter_addresses",
                    return_value=iter([_fake_address()]),
                )
            )
            stack.enter_context(
                patch(
                    "scraper.sources.kbo_dump.staging.iter_denominations",
                    return_value=iter([_fake_denomination()]),
                )
            )
            stack.enter_context(
                patch(
                    "scraper.sources.kbo_dump.staging.iter_contacts",
                    return_value=iter([_fake_contact()]),
                )
            )
            stack.enter_context(
                patch(
                    "scraper.sources.kbo_dump.staging.iter_activities",
                    return_value=iter([_fake_activity()]),
                )
            )
            report = await stage_zip(Path("/fake.zip"), pool, executor=ex)

        assert report.rows_enterprise == 1
        assert report.rows_address == 1
        assert report.rows_denomination == 1
        assert report.rows_contact == 1
        assert report.rows_activity == 1
        # One COPY per non-empty table.
        assert conn.copy_to_table.await_count == 5

    async def test_indexes_dropped_and_recreated(self) -> None:
        pool, conn = _make_pool()

        with ExitStack() as stack, ThreadPoolExecutor(max_workers=2) as ex:
            _enter_empty_patches(stack)
            await stage_zip(Path("/fake.zip"), pool, executor=ex)

        executed = [str(c.args[0]) for c in conn.execute.await_args_list if c.args]
        assert any("DROP INDEX IF EXISTS" in s for s in executed)
        assert any("CREATE INDEX IF NOT EXISTS" in s for s in executed)


# ── _compute_shards ──────────────────────────────────────────────────────────

_ACT_HEADER = "EntityNumber,ActivityGroup,NaceVersion,NaceCode,Classification"


def _write_activity_csv(path: Path, n_rows: int) -> Path:
    lines = [_ACT_HEADER]
    lines += [f"040301926{i % 10},001,2008,4321{i % 9},NACE2008" for i in range(n_rows)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


class TestComputeShards:
    def test_single_shard_when_n_is_one(self, tmp_path: Path) -> None:
        p = _write_activity_csv(tmp_path / "plain.csv", 5)
        assert len(_compute_shards(str(p), 1)) == 1

    def test_header_only_returns_empty(self, tmp_path: Path) -> None:
        p = tmp_path / "h.csv"
        p.write_text(_ACT_HEADER + "\n", encoding="utf-8")
        assert _compute_shards(str(p), 4) == []

    def test_multiple_shards_contiguous_and_cover_body(self, tmp_path: Path) -> None:
        p = _write_activity_csv(tmp_path / "plain.csv", 50)
        size = p.stat().st_size
        shards = _compute_shards(str(p), 4)
        assert len(shards) >= 2
        assert shards[0][0] > 0  # starts after the header
        assert shards[-1][1] == size  # ends at EOF
        for (_, end_prev), (start_next, _) in itertools.pairwise(shards):
            assert end_prev == start_next  # contiguous, no gaps/overlap


class TestBuildActivityShard:
    def test_parses_byte_range(self, tmp_path: Path) -> None:
        p = tmp_path / "plain.csv"
        p.write_text(
            _ACT_HEADER + "\n"
            "0403.019.261,001,2008,43211,NACE2008\n"
            "0820.346.306,002,2008,69201,NACE2008\n",
            encoding="utf-8",
        )
        col_idx = {name: i for i, name in enumerate(_ACT_HEADER.split(","))}
        header_len = len(_ACT_HEADER + "\n")
        out_path, n = _build_activity_shard(
            str(p), header_len, p.stat().st_size, col_idx, "2024-01-01", str(tmp_path)
        )
        assert n == 2
        text = Path(out_path).read_text(encoding="utf-8")
        # KBO compacted (dots stripped), snapshot date injected, field order preserved.
        assert "0403019261\t2024-01-01\t001\t2008\t43211\tNACE2008" in text


class TestStageZipShardedActivity:
    async def test_activity_sharded_from_real_zip(self, tmp_path: Path) -> None:
        zip_path = tmp_path / "KboOpenData_test_Full.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            _write_activity_csv(tmp_path / "activity.csv", 20)
            zf.write(tmp_path / "activity.csv", "activity.csv")

        pool, conn = _make_pool()
        with ThreadPoolExecutor(max_workers=3) as ex:
            report = await stage_zip(zip_path, pool, executor=ex)

        assert report.rows_activity == 20
        copied_tables = [c.args[0] for c in conn.copy_to_table.await_args_list if c.args]
        assert "kbo_stage_activity" in copied_tables
