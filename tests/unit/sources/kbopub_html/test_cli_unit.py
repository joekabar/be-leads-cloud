"""Unit tests for kbopub_html CLI argument parsing and _run() wiring."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scraper.sources.kbopub_html.cli import _run, cli_main

# ---------------------------------------------------------------------------
# cli_main — argument-parsing branches (no DB, no HTTP)
# ---------------------------------------------------------------------------


def test_missing_at_file_exits_2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["prog", "--kbos", "@/nonexistent_path/kbos.txt"])
    with pytest.raises(SystemExit) as exc:
        cli_main()
    assert exc.value.code == 2


def test_empty_kbos_exits_2(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["prog", "--kbos", " , , ", "--database-url", "x"])
    with pytest.raises(SystemExit) as exc:
        cli_main()
    assert exc.value.code == 2


def test_no_database_url_exits_1(monkeypatch: pytest.MonkeyPatch) -> None:
    # Patch load_settings directly so dotenv can't supply a fallback DATABASE_URL.
    from scraper.lib.errors import ConfigError

    monkeypatch.setattr(sys, "argv", ["prog", "--kbos", "0439401387"])
    with (
        patch("scraper.lib.config.load_settings", side_effect=ConfigError("DATABASE_URL not set")),
        pytest.raises(SystemExit) as exc,
    ):
        cli_main()
    assert exc.value.code == 1


def test_at_file_kbos_forwarded_to_asyncio_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kbo_file = tmp_path / "kbos.txt"
    kbo_file.write_text("0439401387\n# comment-like blank\n0123456749\n")
    monkeypatch.setattr(
        sys,
        "argv",
        ["prog", "--kbos", f"@{kbo_file}", "--database-url", "postgresql://localhost/x"],
    )
    with patch("asyncio.run") as mock_run:
        cli_main()
    mock_run.assert_called_once()


def test_comma_kbos_forwarded_to_asyncio_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["prog", "--kbos", "0439401387,0123456749", "--database-url", "postgresql://localhost/x"],
    )
    with patch("asyncio.run") as mock_run:
        cli_main()
    mock_run.assert_called_once()


def test_lang_fr_forwarded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["prog", "--kbos", "0439401387", "--lang", "fr", "--database-url", "postgresql://x"],
    )
    with patch("asyncio.run") as mock_run:
        cli_main()
    mock_run.assert_called_once()


# ---------------------------------------------------------------------------
# _run() — async wiring test with all I/O mocked
# ---------------------------------------------------------------------------


@dataclass
class _FakeReport:
    kbos_processed: int = 1
    kbos_not_found: int = 0
    kbos_invalid: int = 0
    function_holders_total: int = 1
    observations_inserted: int = 1
    duration_s: float = 0.1
    errors: list[str] = field(default_factory=list)


@pytest.mark.asyncio
async def test_run_prints_json_report(capsys: pytest.CaptureFixture[str]) -> None:
    fake_pool = MagicMock()
    fake_pool.close = AsyncMock()

    fake_limiter = MagicMock()
    fake_report = _FakeReport()

    with (
        patch("scraper.sources.kbopub_html.cli.Path") as mock_path_cls,
        patch("scraper.db.pool.init_pool", new_callable=AsyncMock, return_value=fake_pool),
        patch("scraper.lib.http.limiter.load_from_toml", return_value=fake_limiter),
        patch(
            "scraper.sources.kbopub_html.ingester.ingest_kbos",
            new_callable=AsyncMock,
            return_value=fake_report,
        ),
    ):
        # Make Path(__file__).parents[4] / ... return a valid toml path that exists.
        mock_path_instance = MagicMock()
        mock_path_instance.__truediv__ = MagicMock(return_value=mock_path_instance)
        mock_path_cls.return_value = mock_path_instance

        await _run(
            kbos=["0439401387"],
            database_url="postgresql://leads:leads@localhost/leads_test",
            lang="nl",
            skip_recent_hours=24,
        )

    captured = capsys.readouterr()
    last_line = captured.out.strip().splitlines()[-1]
    report = json.loads(last_line)
    assert report["kbos_processed"] == 1
    assert report["observations_inserted"] == 1
