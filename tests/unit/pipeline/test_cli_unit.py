"""Unit tests for scraper.pipeline.cli (no network, no DB)."""

from __future__ import annotations

import sys

import pytest

from scraper.pipeline.cli import _build_parser


class TestBuildParser:
    def test_required_sector_and_city(self) -> None:
        p = _build_parser()
        args = p.parse_args(["--sector", "electriciens", "--city", "Antwerpen"])
        assert args.sector == "electriciens"
        assert args.city == "Antwerpen"

    def test_defaults(self) -> None:
        p = _build_parser()
        args = p.parse_args(["--sector", "loodgieters", "--city", "Gent"])
        assert args.max_pages == 5
        assert args.lang == "nl"
        assert args.use_fixture is False
        assert args.skip_kbo_dump is False
        assert args.skip_goudengids is False
        assert args.skip_kbopub is False
        assert args.skip_nbb is False
        assert args.skip_website is False
        assert args.skip_search is False
        assert args.brave_key is None
        assert args.nbb_key is None
        assert args.fixture_zip is None

    def test_skip_flags(self) -> None:
        p = _build_parser()
        args = p.parse_args(
            [
                "--sector",
                "electriciens",
                "--city",
                "Brussel",
                "--skip-kbo-dump",
                "--skip-goudengids",
                "--skip-kbopub",
                "--skip-nbb",
                "--skip-website",
                "--skip-search",
            ]
        )
        assert args.skip_kbo_dump is True
        assert args.skip_goudengids is True
        assert args.skip_kbopub is True
        assert args.skip_nbb is True
        assert args.skip_website is True
        assert args.skip_search is True

    def test_max_pages_and_lang(self) -> None:
        p = _build_parser()
        args = p.parse_args(
            ["--sector", "electriciens", "--city", "Luik", "--max-pages", "10", "--lang", "fr"]
        )
        assert args.max_pages == 10
        assert args.lang == "fr"

    def test_use_fixture(self) -> None:
        p = _build_parser()
        args = p.parse_args(["--sector", "electriciens", "--city", "Antwerpen", "--use-fixture"])
        assert args.use_fixture is True

    def test_missing_required_args_exits(self) -> None:
        p = _build_parser()
        with pytest.raises(SystemExit) as exc_info:
            p.parse_args([])
        assert exc_info.value.code != 0


class TestCliMainInvalidSector:
    def test_invalid_sector_exits_2(self, capsys: pytest.CaptureFixture[str]) -> None:
        from scraper.pipeline.cli import cli_main

        sys.argv = [
            "be-leads-pipeline",
            "--sector",
            "nonexistent_sector_xyz",
            "--city",
            "Antwerpen",
        ]
        with pytest.raises(SystemExit) as exc_info:
            cli_main()
        assert exc_info.value.code == 2
        captured = capsys.readouterr()
        assert "Error" in captured.err
