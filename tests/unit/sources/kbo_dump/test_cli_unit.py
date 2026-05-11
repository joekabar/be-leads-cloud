from __future__ import annotations

import sys
from pathlib import Path

import pytest

from scraper.sources.kbo_dump.cli import cli_validate


def test_cli_validate_valid_number(capsys: pytest.CaptureFixture[str]) -> None:
    sys.argv = ["be-leads-validate-kbo", "0439401387"]
    cli_validate()
    captured = capsys.readouterr()
    assert "valid" in captured.out
    assert "0439401387" in captured.out


def test_cli_validate_with_dots(capsys: pytest.CaptureFixture[str]) -> None:
    sys.argv = ["be-leads-validate-kbo", "0439.401.387"]
    cli_validate()
    captured = capsys.readouterr()
    assert "valid" in captured.out


def test_cli_validate_modern_prefix(capsys: pytest.CaptureFixture[str]) -> None:
    sys.argv = ["be-leads-validate-kbo", "1000000021"]
    cli_validate()
    captured = capsys.readouterr()
    assert "valid" in captured.out


def test_cli_validate_invalid_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    sys.argv = ["be-leads-validate-kbo", "0000000000"]
    with pytest.raises(SystemExit) as exc_info:
        cli_validate()
    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "invalid" in captured.err


def test_cli_validate_wrong_check_digit(capsys: pytest.CaptureFixture[str]) -> None:
    sys.argv = ["be-leads-validate-kbo", "0439401388"]
    with pytest.raises(SystemExit) as exc_info:
        cli_validate()
    assert exc_info.value.code == 2


def test_cli_main_missing_zip_exits_1(capsys: pytest.CaptureFixture[str]) -> None:
    from scraper.sources.kbo_dump.cli import cli_main

    sys.argv = ["be-leads-ingest-kbo", "--zip", "/nonexistent/path.zip"]
    with pytest.raises(SystemExit) as exc_info:
        cli_main()
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Error" in captured.err


def test_downloader_stub_raises(tmp_path: Path) -> None:
    """Downloader is a stub; importing and checking it raises NotImplementedError."""
    import asyncio

    from scraper.lib.config import Settings
    from scraper.sources.kbo_dump.downloader import KboDumpDownloader

    settings = Settings(database_url="postgresql://x:x@localhost/x")
    dl = KboDumpDownloader(settings)

    async def _check() -> None:
        with pytest.raises(NotImplementedError):
            await dl.download_latest_full(tmp_path)
        with pytest.raises(NotImplementedError):
            await dl.download_latest_update(tmp_path)

    asyncio.run(_check())
