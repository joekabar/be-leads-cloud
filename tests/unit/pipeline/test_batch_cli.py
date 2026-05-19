"""Unit tests for batch_cli argument parsing (no DB or async required)."""

from __future__ import annotations

import sys
from unittest.mock import patch

import pytest

from scraper.pipeline.batch_cli import _build_parser, cli_main


class TestBuildParser:
    def test_city_required(self) -> None:
        parser = _build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([])

    def test_city_parsed(self) -> None:
        args = _build_parser().parse_args(["--city", "antwerpen", "--all-sectors"])
        assert args.city == "antwerpen"

    def test_all_sectors_flag(self) -> None:
        args = _build_parser().parse_args(["--city", "gent", "--all-sectors"])
        assert args.all_sectors is True
        assert args.sectors == []

    def test_sector_append(self) -> None:
        args = _build_parser().parse_args(
            ["--city", "gent", "--sector", "elektriciens", "--sector", "accountants"]
        )
        assert args.sectors == ["elektriciens", "accountants"]
        assert args.all_sectors is False

    def test_snapshot_date_parsed(self) -> None:
        args = _build_parser().parse_args(
            ["--city", "gent", "--all-sectors", "--snapshot-date", "2026-04-15"]
        )
        assert args.snapshot_date == "2026-04-15"

    def test_lang_default_nl(self) -> None:
        args = _build_parser().parse_args(["--city", "gent", "--all-sectors"])
        assert args.lang == "nl"

    def test_lang_fr(self) -> None:
        args = _build_parser().parse_args(["--city", "gent", "--all-sectors", "--lang", "fr"])
        assert args.lang == "fr"

    def test_max_pages_default(self) -> None:
        args = _build_parser().parse_args(["--city", "gent", "--all-sectors"])
        assert args.max_pages == 25

    def test_max_pages_custom(self) -> None:
        args = _build_parser().parse_args(["--city", "gent", "--all-sectors", "--max-pages", "10"])
        assert args.max_pages == 10

    def test_skip_flags_default_false(self) -> None:
        args = _build_parser().parse_args(["--city", "gent", "--all-sectors"])
        assert args.skip_kbo_dump is False
        assert args.skip_goudengids is False
        assert args.skip_kbopub is False
        assert args.skip_nbb is False
        assert args.skip_website is False
        assert args.skip_search is False

    def test_skip_flags_set(self) -> None:
        args = _build_parser().parse_args(
            [
                "--city",
                "gent",
                "--all-sectors",
                "--skip-kbo-dump",
                "--skip-goudengids",
                "--skip-nbb",
            ]
        )
        assert args.skip_kbo_dump is True
        assert args.skip_goudengids is True
        assert args.skip_nbb is True
        assert args.skip_kbopub is False

    def test_database_url_default_none(self) -> None:
        args = _build_parser().parse_args(["--city", "gent", "--all-sectors"])
        assert args.database_url is None

    def test_brave_and_nbb_keys(self) -> None:
        args = _build_parser().parse_args(
            ["--city", "gent", "--all-sectors", "--brave-key", "BKEY", "--nbb-key", "NKEY"]
        )
        assert args.brave_key == "BKEY"
        assert args.nbb_key == "NKEY"


class TestCliMainErrors:
    def test_no_sectors_exits_2(self) -> None:
        with patch.object(sys, "argv", ["batch", "--city", "gent"]):
            with pytest.raises(SystemExit) as exc:
                cli_main()
            assert exc.value.code == 2

    def test_unknown_sector_exits_2(self) -> None:
        with patch.object(sys, "argv", ["batch", "--city", "gent", "--sector", "nonexistent-xyz"]):
            with pytest.raises(SystemExit) as exc:
                cli_main()
            assert exc.value.code == 2

    def test_invalid_snapshot_date_exits_2(self) -> None:
        with patch.object(
            sys, "argv", ["batch", "--city", "gent", "--all-sectors", "--snapshot-date", "baddate"]
        ):
            with pytest.raises(SystemExit) as exc:
                cli_main()
            assert exc.value.code == 2
