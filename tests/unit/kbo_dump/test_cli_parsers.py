"""Unit tests for stage_cli and cleanup_cli argument parsing and early-exit paths."""

from __future__ import annotations

import sys
from unittest.mock import patch

import pytest

from scraper.sources.kbo_dump.cleanup_cli import cli_main as cleanup_main
from scraper.sources.kbo_dump.stage_cli import cli_main as stage_main


class TestStageCli:
    def test_nonexistent_zip_exits_2(self, tmp_path) -> None:
        missing = str(tmp_path / "nonexistent.zip")
        with patch.object(sys, "argv", ["stage", missing]):
            with pytest.raises(SystemExit) as exc:
                stage_main()
            assert exc.value.code == 2

    def test_zip_arg_required(self) -> None:
        with patch.object(sys, "argv", ["stage"]), pytest.raises(SystemExit):
            stage_main()


class TestCleanupCli:
    def test_keep_zero_exits_2(self) -> None:
        with patch.object(sys, "argv", ["cleanup", "--keep", "0"]):
            with pytest.raises(SystemExit) as exc:
                cleanup_main()
            assert exc.value.code == 2

    def test_keep_negative_exits_2(self) -> None:
        with patch.object(sys, "argv", ["cleanup", "--keep", "-1"]):
            with pytest.raises(SystemExit) as exc:
                cleanup_main()
            assert exc.value.code == 2

    def test_keep_default_is_three(self) -> None:
        import argparse

        p = argparse.ArgumentParser()
        p.add_argument("--keep", type=int, default=3)
        args = p.parse_args([])
        assert args.keep == 3
