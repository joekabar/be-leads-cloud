"""Unit tests for website CLI argument parsing (no DB required)."""

from __future__ import annotations

import pytest

from scraper.sources.website.cli import cli_main


class TestCliMain:
    def test_help_exits_zero(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            import sys

            sys.argv = ["be-leads-enrich-website", "--help"]
            cli_main()
        assert exc_info.value.code == 0

    def test_no_args_exits_nonzero(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            import sys

            sys.argv = ["be-leads-enrich-website"]
            cli_main()
        assert exc_info.value.code != 0

    def test_both_source_args_mutually_exclusive(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            import sys

            sys.argv = [
                "be-leads-enrich-website",
                "--kbos-and-websites",
                "file.tsv",
                "--from-db",
            ]
            cli_main()
        assert exc_info.value.code != 0
