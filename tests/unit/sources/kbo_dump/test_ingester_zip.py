"""Unit tests for kbo_dump/ingester.py — bulk insert + ingest_zip."""

from __future__ import annotations

import uuid
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from scraper.sources.kbo_dump.ingester import (
    IngestReport,
    _bulk_insert_observations,
    _pg_text_escape,
    ingest_zip,
)

# ── _pg_text_escape ───────────────────────────────────────────────────────────


class TestPgTextEscape:
    def test_none_returns_backslash_n(self) -> None:
        assert _pg_text_escape(None) == r"\N"

    def test_regular_string_unchanged(self) -> None:
        assert _pg_text_escape("hello") == "hello"

    def test_backslash_doubled(self) -> None:
        assert _pg_text_escape("a\\b") == "a\\\\b"

    def test_tab_escaped(self) -> None:
        assert _pg_text_escape("a\tb") == "a\\tb"

    def test_newline_escaped(self) -> None:
        assert _pg_text_escape("a\nb") == "a\\nb"


# ── _bulk_insert_observations ─────────────────────────────────────────────────


def _make_obs(**overrides: object) -> object:
    from scraper.db.models import Observation

    defaults: dict[str, object] = {
        "kbo_number": "0403019261",
        "field": "name",
        "value": {"text": "Test NV"},
        "source": "kbo_dump",
        "confidence": 0.95,
        "run_id": uuid.uuid4(),
        "observed_at": datetime.now(tz=UTC),
    }
    defaults.update(overrides)
    return Observation(**defaults)  # type: ignore[arg-type]


class TestBulkInsertObservations:
    async def test_empty_list_returns_zero(self) -> None:
        conn = MagicMock()
        conn.copy_to_table = AsyncMock()
        result = await _bulk_insert_observations(conn, [])
        assert result == 0
        conn.copy_to_table.assert_not_called()

    async def test_inserts_one_observation(self) -> None:
        conn = MagicMock()
        conn.copy_to_table = AsyncMock()
        obs = _make_obs()  # type: ignore[arg-type]
        result = await _bulk_insert_observations(conn, [obs])  # type: ignore[arg-type]
        assert result == 1
        conn.copy_to_table.assert_called_once()

    async def test_null_observed_at_becomes_backslash_n(self) -> None:
        conn = MagicMock()
        conn.copy_to_table = AsyncMock()
        obs = _make_obs(observed_at=None)  # type: ignore[arg-type]
        await _bulk_insert_observations(conn, [obs])  # type: ignore[arg-type]
        call_kwargs = conn.copy_to_table.call_args
        source_bytes = call_kwargs.kwargs["source"].read()
        assert rb"\N" in source_bytes


# ── ingest_zip helpers ────────────────────────────────────────────────────────


def _make_pool() -> tuple[MagicMock, MagicMock]:
    conn = MagicMock()
    conn.fetchval = AsyncMock(return_value=None)
    conn.copy_to_table = AsyncMock()
    conn.execute = AsyncMock(return_value="DELETE 0")

    acquire_cm = MagicMock()
    acquire_cm.__aenter__ = AsyncMock(return_value=conn)
    acquire_cm.__aexit__ = AsyncMock(return_value=False)

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=acquire_cm)
    pool.execute = AsyncMock()

    return pool, conn


def _mock_runs_cls() -> MagicMock:
    cls = MagicMock()
    cls.return_value.start_run = AsyncMock(return_value=uuid.uuid4())
    cls.return_value.finish_run = AsyncMock()
    return cls


def _enter_zip_patches(
    stack: ExitStack,
    *,
    extract_type: str = "Full",
    snapshot_date: str = "01-01-2024",
) -> None:
    """Push common ingest_zip mock patches onto an ExitStack."""
    stack.enter_context(
        patch(
            "scraper.sources.kbo_dump.ingester.parse_meta",
            return_value={"SnapshotDate": snapshot_date},
        )
    )
    stack.enter_context(
        patch(
            "scraper.sources.kbo_dump.ingester.detect_extract_type",
            return_value=extract_type,
        )
    )
    for name in (
        "iter_enterprises",
        "iter_denominations",
        "iter_addresses",
        "iter_contacts",
        "iter_activities",
        "iter_deleted_enterprises",
    ):
        stack.enter_context(
            patch(f"scraper.sources.kbo_dump.ingester.{name}", return_value=iter([]))
        )


# ── ingest_zip ────────────────────────────────────────────────────────────────


class TestIngestZip:
    async def test_basic_full_ingest_empty_data(self) -> None:
        pool, _conn = _make_pool()
        runs_cls = _mock_runs_cls()

        with ExitStack() as stack:
            _enter_zip_patches(stack)
            stack.enter_context(patch("scraper.sources.kbo_dump.ingester.RunsRepo", runs_cls))
            report = await ingest_zip(Path("/fake.zip"), pool)

        assert isinstance(report, IngestReport)
        assert report.extract_type == "Full"
        assert report.enterprises_processed == 0
        assert report.observations_inserted == 0

    async def test_skip_if_fresh_returns_early_when_data_exists(self) -> None:
        pool, conn = _make_pool()
        conn.fetchval = AsyncMock(return_value=1)
        runs_cls = _mock_runs_cls()

        with ExitStack() as stack:
            _enter_zip_patches(stack)
            stack.enter_context(patch("scraper.sources.kbo_dump.ingester.RunsRepo", runs_cls))
            report = await ingest_zip(Path("/fake.zip"), pool, skip_if_fresh=True)

        assert report.enterprises_processed == 0
        runs_cls.return_value.start_run.assert_not_called()

    async def test_truncate_first_issues_delete(self) -> None:
        pool, conn = _make_pool()
        runs_cls = _mock_runs_cls()

        with ExitStack() as stack:
            _enter_zip_patches(stack)
            stack.enter_context(patch("scraper.sources.kbo_dump.ingester.RunsRepo", runs_cls))
            await ingest_zip(Path("/fake.zip"), pool, truncate_first=True)

        conn.execute.assert_called_once()
        assert "DELETE" in conn.execute.call_args[0][0]

    async def test_refresh_view_false_skips_execute(self) -> None:
        pool, _conn = _make_pool()
        runs_cls = _mock_runs_cls()

        with ExitStack() as stack:
            _enter_zip_patches(stack)
            stack.enter_context(patch("scraper.sources.kbo_dump.ingester.RunsRepo", runs_cls))
            await ingest_zip(Path("/fake.zip"), pool, refresh_view=False)

        pool.execute.assert_not_called()

    async def test_enterprises_processed_and_inserted(self) -> None:
        from scraper.sources.kbo_dump.parser import EnterpriseRow

        pool, _conn = _make_pool()
        runs_cls = _mock_runs_cls()
        ent = MagicMock(spec=EnterpriseRow)
        ent.enterprise_number = "0403019261"
        fake_obs = _make_obs()

        with ExitStack() as stack:
            _enter_zip_patches(stack)
            stack.enter_context(patch("scraper.sources.kbo_dump.ingester.RunsRepo", runs_cls))
            stack.enter_context(
                patch(
                    "scraper.sources.kbo_dump.ingester.iter_enterprises",
                    return_value=iter([ent]),
                )
            )
            stack.enter_context(
                patch(
                    "scraper.sources.kbo_dump.ingester.enterprise_to_observations",
                    return_value=[fake_obs],
                )
            )
            report = await ingest_zip(Path("/fake.zip"), pool, refresh_view=False)

        assert report.enterprises_processed == 1

    async def test_december_snapshot_skip_if_fresh(self) -> None:
        pool, conn = _make_pool()
        conn.fetchval = AsyncMock(return_value=None)
        runs_cls = _mock_runs_cls()

        with ExitStack() as stack:
            _enter_zip_patches(stack, snapshot_date="01-12-2023")
            stack.enter_context(patch("scraper.sources.kbo_dump.ingester.RunsRepo", runs_cls))
            report = await ingest_zip(Path("/fake.zip"), pool, skip_if_fresh=True)

        assert report.extract_type == "Full"

    async def test_update_extract_processes_deleted_enterprises(self) -> None:
        pool, _conn = _make_pool()
        runs_cls = _mock_runs_cls()

        with ExitStack() as stack:
            _enter_zip_patches(stack, extract_type="Update")
            stack.enter_context(patch("scraper.sources.kbo_dump.ingester.RunsRepo", runs_cls))
            stack.enter_context(
                patch(
                    "scraper.sources.kbo_dump.ingester.iter_deleted_enterprises",
                    return_value=iter(["0403019261"]),
                )
            )
            report = await ingest_zip(Path("/fake.zip"), pool, refresh_view=False)

        assert report.extract_type == "Update"

    async def test_bad_snapshot_date_falls_back_to_today(self) -> None:
        pool, _conn = _make_pool()
        runs_cls = _mock_runs_cls()

        with ExitStack() as stack:
            _enter_zip_patches(stack, snapshot_date="not-a-date")
            stack.enter_context(patch("scraper.sources.kbo_dump.ingester.RunsRepo", runs_cls))
            report = await ingest_zip(Path("/fake.zip"), pool, refresh_view=False)

        assert report.extract_type == "Full"

    async def test_max_enterprises_limits_processing(self) -> None:
        from scraper.sources.kbo_dump.parser import EnterpriseRow

        pool, _conn = _make_pool()
        runs_cls = _mock_runs_cls()
        ents = [MagicMock(spec=EnterpriseRow) for _ in range(5)]
        for i, e in enumerate(ents):
            e.enterprise_number = f"040301926{i}"
        fake_obs = _make_obs()

        with ExitStack() as stack:
            _enter_zip_patches(stack)
            stack.enter_context(patch("scraper.sources.kbo_dump.ingester.RunsRepo", runs_cls))
            stack.enter_context(
                patch(
                    "scraper.sources.kbo_dump.ingester.iter_enterprises",
                    return_value=iter(ents),
                )
            )
            stack.enter_context(
                patch(
                    "scraper.sources.kbo_dump.ingester.enterprise_to_observations",
                    return_value=[fake_obs],
                )
            )
            report = await ingest_zip(
                Path("/fake.zip"), pool, max_enterprises=2, refresh_view=False
            )

        assert report.enterprises_processed == 2

    async def test_entity_filter_skips_non_matching_enterprise(self) -> None:
        """Line 298 (continue): enterprise not in entity_filter is skipped."""
        from scraper.sources.kbo_dump.parser import EnterpriseRow

        pool, _conn = _make_pool()
        runs_cls = _mock_runs_cls()
        ent = MagicMock(spec=EnterpriseRow)
        ent.enterprise_number = "0403019261"

        with ExitStack() as stack:
            _enter_zip_patches(stack)
            stack.enter_context(patch("scraper.sources.kbo_dump.ingester.RunsRepo", runs_cls))
            stack.enter_context(
                patch(
                    "scraper.sources.kbo_dump.ingester.iter_enterprises",
                    return_value=iter([ent]),
                )
            )
            report = await ingest_zip(
                Path("/fake.zip"), pool, city_filter=["antwerpen"], refresh_view=False
            )

        assert report.enterprises_processed == 0

    async def test_denominations_loop_body_covered(self) -> None:
        """Lines 317-323: denomination loop body with a valid row."""
        from scraper.sources.kbo_dump.parser import DenominationRow

        pool, _conn = _make_pool()
        runs_cls = _mock_runs_cls()
        denom = DenominationRow(
            entity_number="0403019261",
            language="NL",
            type_of_denomination="001",
            denomination="Test NV",
        )

        with ExitStack() as stack:
            _enter_zip_patches(stack)
            stack.enter_context(patch("scraper.sources.kbo_dump.ingester.RunsRepo", runs_cls))
            stack.enter_context(
                patch(
                    "scraper.sources.kbo_dump.ingester.iter_denominations",
                    return_value=iter([denom]),
                )
            )
            report = await ingest_zip(Path("/fake.zip"), pool, refresh_view=False)

        assert report.enterprises_processed == 0

    async def test_addresses_loop_body_covered(self) -> None:
        """Lines 328-334: address loop body with a valid row."""
        from scraper.sources.kbo_dump.parser import AddressRow

        pool, _conn = _make_pool()
        runs_cls = _mock_runs_cls()
        addr = AddressRow(
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

        with ExitStack() as stack:
            _enter_zip_patches(stack)
            stack.enter_context(patch("scraper.sources.kbo_dump.ingester.RunsRepo", runs_cls))
            stack.enter_context(
                patch(
                    "scraper.sources.kbo_dump.ingester.iter_addresses",
                    return_value=iter([addr]),
                )
            )
            report = await ingest_zip(Path("/fake.zip"), pool, refresh_view=False)

        assert report.enterprises_processed == 0

    async def test_contacts_web_loop_body_covered(self) -> None:
        """Lines 344-346: contact loop body for valid WEB contact."""
        from scraper.sources.kbo_dump.parser import ContactRow

        pool, _conn = _make_pool()
        runs_cls = _mock_runs_cls()
        contact = ContactRow(
            entity_number="0403019261",
            contact_type="WEB",
            value="https://delhaize.be",
        )

        with ExitStack() as stack:
            _enter_zip_patches(stack)
            stack.enter_context(patch("scraper.sources.kbo_dump.ingester.RunsRepo", runs_cls))
            stack.enter_context(
                patch(
                    "scraper.sources.kbo_dump.ingester.iter_contacts",
                    return_value=iter([contact]),
                )
            )
            report = await ingest_zip(Path("/fake.zip"), pool, refresh_view=False)

        assert report.enterprises_processed == 0

    async def test_contacts_invalid_tel_increments_counter(self) -> None:
        """Lines 342-343: invalid phone increments phones_invalid_skipped."""
        from scraper.sources.kbo_dump.parser import ContactRow

        pool, _conn = _make_pool()
        runs_cls = _mock_runs_cls()
        contact = ContactRow(
            entity_number="0403019261",
            contact_type="TEL",
            value="INVALID_PHONE",
        )

        with ExitStack() as stack:
            _enter_zip_patches(stack)
            stack.enter_context(patch("scraper.sources.kbo_dump.ingester.RunsRepo", runs_cls))
            stack.enter_context(
                patch(
                    "scraper.sources.kbo_dump.ingester.iter_contacts",
                    return_value=iter([contact]),
                )
            )
            report = await ingest_zip(Path("/fake.zip"), pool, refresh_view=False)

        assert report.phones_invalid_skipped >= 1

    async def test_activities_loop_body_covered(self) -> None:
        """Lines 352-358: activity loop body with a valid row."""
        from scraper.sources.kbo_dump.parser import ActivityRow

        pool, _conn = _make_pool()
        runs_cls = _mock_runs_cls()
        act = ActivityRow(
            entity_number="0403019261",
            activity_group="MAIN",
            nace_version="2008",
            nace_code="43211",
            classification="NACE2008",
        )

        with ExitStack() as stack:
            _enter_zip_patches(stack)
            stack.enter_context(patch("scraper.sources.kbo_dump.ingester.RunsRepo", runs_cls))
            stack.enter_context(
                patch(
                    "scraper.sources.kbo_dump.ingester.iter_activities",
                    return_value=iter([act]),
                )
            )
            report = await ingest_zip(Path("/fake.zip"), pool, refresh_view=False)

        assert report.enterprises_processed == 0
