"""Unit tests for ddg_brave.cli — lazy imports patched at source modules."""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scraper.sources.ddg_brave.ingester import SearchValidationReport


def _make_report(**kwargs) -> SearchValidationReport:  # type: ignore[no-untyped-def]
    defaults = {
        "queries_processed": 1,
        "brave_queries": 1,
        "ddg_queries": 0,
        "brave_quota_exhausted": False,
        "observations_inserted": 2,
        "websites_confirmed": 1,
        "duration_s": 0.1,
    }
    defaults.update(kwargs)
    return SearchValidationReport(**defaults)


@contextlib.asynccontextmanager  # type: ignore[arg-type]
async def _fake_polite_client(_limiter):  # type: ignore[no-untyped-def]
    yield MagicMock()


@pytest.fixture()
def tsv_file(tmp_path: Path) -> Path:
    f = tmp_path / "inputs.tsv"
    f.write_text("0439401387\tBellock\tAntwerpen\n", encoding="utf-8")
    return f


@pytest.mark.asyncio
async def test_run_inputs_file_prints_json(tsv_file: Path, capsys: pytest.CaptureFixture) -> None:  # type: ignore[no-untyped-def]
    from scraper.sources.ddg_brave.cli import _run

    report = _make_report()
    mock_pool = AsyncMock()
    mock_pool.close = AsyncMock()

    with (
        patch("scraper.db.pool.init_pool", return_value=mock_pool),
        patch("scraper.lib.http.limiter.load_from_toml", return_value=MagicMock()),
        patch("scraper.lib.http.client.get_polite_client", _fake_polite_client),
        patch(
            "scraper.sources.ddg_brave.ingester.validate_companies", AsyncMock(return_value=report)
        ),
    ):
        await _run(
            inputs_file=str(tsv_file),
            from_db=False,
            limit=None,
            engine="brave",
            skip_recent_hours=0,
            brave_key="test-key",
            database_url="postgresql://x:x@localhost/x",
        )

    out = json.loads(capsys.readouterr().out)
    assert out["queries_processed"] == 1
    assert out["observations_inserted"] == 2


@pytest.mark.asyncio
async def test_run_empty_inputs_prints_zeros(capsys: pytest.CaptureFixture) -> None:  # type: ignore[no-untyped-def]
    from scraper.sources.ddg_brave.cli import _run

    mock_pool = AsyncMock()
    mock_pool.close = AsyncMock()

    with patch("scraper.db.pool.init_pool", return_value=mock_pool):
        await _run(
            inputs_file=None,
            from_db=False,
            limit=None,
            engine="auto",
            skip_recent_hours=168,
            brave_key=None,
            database_url="postgresql://x:x@localhost/x",
        )

    out = json.loads(capsys.readouterr().out)
    assert out["queries_processed"] == 0


@pytest.mark.asyncio
async def test_run_limit_zero_returns_zeros(tsv_file: Path, capsys: pytest.CaptureFixture) -> None:  # type: ignore[no-untyped-def]
    from scraper.sources.ddg_brave.cli import _run

    mock_pool = AsyncMock()
    mock_pool.close = AsyncMock()

    with patch("scraper.db.pool.init_pool", return_value=mock_pool):
        await _run(
            inputs_file=str(tsv_file),
            from_db=False,
            limit=0,
            engine="auto",
            skip_recent_hours=0,
            brave_key="key",
            database_url="postgresql://x:x@localhost/x",
        )

    out = json.loads(capsys.readouterr().out)
    assert out["queries_processed"] == 0


@pytest.mark.asyncio
async def test_run_ddg_engine_passes_none_brave(
    tsv_file: Path, capsys: pytest.CaptureFixture
) -> None:  # type: ignore[no-untyped-def]
    from scraper.sources.ddg_brave.cli import _run

    report = _make_report(brave_queries=0, ddg_queries=1)
    mock_pool = AsyncMock()
    mock_pool.close = AsyncMock()
    captured: list[dict] = []  # type: ignore[type-arg]

    async def _mock_validate(inputs, pool, pc, **kwargs):  # type: ignore[no-untyped-def]
        captured.append(kwargs)
        return report

    with (
        patch("scraper.db.pool.init_pool", return_value=mock_pool),
        patch("scraper.lib.http.limiter.load_from_toml", return_value=MagicMock()),
        patch("scraper.lib.http.client.get_polite_client", _fake_polite_client),
        patch("scraper.sources.ddg_brave.ingester.validate_companies", _mock_validate),
    ):
        await _run(
            inputs_file=str(tsv_file),
            from_db=False,
            limit=None,
            engine="ddg",
            skip_recent_hours=0,
            brave_key=None,
            database_url="postgresql://x:x@localhost/x",
        )

    assert captured[0]["brave_client"] is None
    assert captured[0]["ddg_client"] is not None


class TestCliMain:
    def test_from_db_calls_asyncio_run(self) -> None:
        import sys
        from unittest.mock import patch

        with (
            patch.object(
                sys,
                "argv",
                ["be-leads-search-validate", "--from-db", "--database-url", "postgresql://x"],
            ),
            patch("asyncio.run") as mock_run,
        ):
            from scraper.sources.ddg_brave.cli import cli_main

            cli_main()
        mock_run.assert_called_once()

    def test_inputs_file_calls_asyncio_run(self, tmp_path: Path) -> None:
        import sys
        from unittest.mock import patch

        tsv = tmp_path / "i.tsv"
        tsv.write_text("0439401387\tTest\tAntwerpen\n")
        with (
            patch.object(
                sys,
                "argv",
                [
                    "be-leads-search-validate",
                    "--inputs",
                    str(tsv),
                    "--database-url",
                    "postgresql://x",
                ],
            ),
            patch("asyncio.run") as mock_run,
        ):
            from scraper.sources.ddg_brave.cli import cli_main

            cli_main()
        mock_run.assert_called_once()

    def test_engine_brave_only(self) -> None:
        import sys
        from unittest.mock import patch

        with (
            patch.object(
                sys,
                "argv",
                [
                    "be-leads-search-validate",
                    "--from-db",
                    "--engine",
                    "brave",
                    "--brave-key",
                    "key",
                    "--database-url",
                    "postgresql://x",
                ],
            ),
            patch("asyncio.run") as mock_run,
        ):
            from scraper.sources.ddg_brave.cli import cli_main

            cli_main()
        mock_run.assert_called_once()

    def test_no_db_url_uses_settings(self) -> None:
        import sys
        from unittest.mock import MagicMock, patch

        with (
            patch.object(sys, "argv", ["be-leads-search-validate", "--from-db"]),
            patch(
                "scraper.lib.config.load_settings",
                return_value=MagicMock(database_url="postgresql://s"),
            ),
            patch("asyncio.run") as mock_run,
        ):
            from scraper.sources.ddg_brave.cli import cli_main

            cli_main()
        mock_run.assert_called_once()
