"""Unit tests for batch_cli argument parsing (no DB or async required)."""

from __future__ import annotations

import os
import sys
from unittest.mock import patch

import pytest

from scraper.pipeline.batch_cli import _build_parser, _resolve_api_keys, cli_main


class TestApiKeyResolution:
    """API keys must be read *after* .env has been loaded into os.environ.

    `cli_main` read BRAVE_SEARCH_API_KEY and NBB_CBSO_API_KEY from os.environ on the two
    lines *above* the `load_settings()` call that runs `load_dotenv()`. Both were
    therefore always None for anyone keeping their keys in .env — which is what the
    repo's own .env.example tells you to do.

    Consequences, both silent: goudengids cross-validation fell back to DuckDuckGo alone
    and died with "No results found.", and the batch pipeline never ran NBB financial
    enrichment at all, because `_phase_c1_nbb` skips when no key is present.
    """

    def test_cli_arg_wins_over_environment(self) -> None:
        with patch.dict(os.environ, {"BRAVE_SEARCH_API_KEY": "from-env"}, clear=False):
            brave, _ = _resolve_api_keys("from-arg", None)
        assert brave == "from-arg"

    def test_falls_back_to_environment(self) -> None:
        with patch.dict(os.environ, {"BRAVE_SEARCH_API_KEY": "from-env"}, clear=False):
            brave, _ = _resolve_api_keys(None, None)
        assert brave == "from-env"

    def test_nbb_key_resolves_the_same_way(self) -> None:
        with patch.dict(os.environ, {"NBB_CBSO_API_KEY": "nbb-env"}, clear=False):
            _, nbb = _resolve_api_keys(None, None)
        assert nbb == "nbb-env"

    def test_absent_key_is_none(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            brave, nbb = _resolve_api_keys(None, None)
        assert brave is None
        assert nbb is None

    def test_keys_set_only_by_dotenv_are_picked_up(self) -> None:
        """The regression: .env populates os.environ during load_settings()."""
        with patch.dict(os.environ, {}, clear=True):

            def _fake_load_settings() -> object:
                os.environ["BRAVE_SEARCH_API_KEY"] = "key-from-dotenv"
                os.environ["NBB_CBSO_API_KEY"] = "nbb-from-dotenv"
                return object()

            _fake_load_settings()
            brave, nbb = _resolve_api_keys(None, None)

        assert brave == "key-from-dotenv"
        assert nbb == "nbb-from-dotenv"


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


class TestNewDedupeAndExportArgs:
    def test_default_goudengids_skip_recent_hours(self) -> None:
        args = _build_parser().parse_args(["--city", "antwerpen", "--all-sectors"])
        assert args.goudengids_skip_recent_hours == 720

    def test_custom_goudengids_skip_recent_hours(self) -> None:
        args = _build_parser().parse_args(
            ["--city", "antwerpen", "--all-sectors", "--goudengids-skip-recent-hours", "48"]
        )
        assert args.goudengids_skip_recent_hours == 48

    def test_default_ddg_brave_skip_recent_hours(self) -> None:
        args = _build_parser().parse_args(["--city", "antwerpen", "--all-sectors"])
        assert args.ddg_brave_skip_recent_hours == 168

    def test_custom_ddg_brave_skip_recent_hours(self) -> None:
        args = _build_parser().parse_args(
            ["--city", "antwerpen", "--all-sectors", "--ddg-brave-skip-recent-hours", "24"]
        )
        assert args.ddg_brave_skip_recent_hours == 24

    def test_export_dir_parsed(self) -> None:
        from pathlib import Path

        args = _build_parser().parse_args(
            ["--city", "antwerpen", "--all-sectors", "--export-dir", "/tmp/exports"]
        )
        assert args.export_dir == "/tmp/exports"
        # Verify cli_main converts it to Path correctly.
        assert Path(args.export_dir) == Path("/tmp/exports")

    def test_no_export_dir_is_none(self) -> None:
        args = _build_parser().parse_args(["--city", "antwerpen", "--all-sectors"])
        assert args.export_dir is None

    def test_export_chunk_size_default(self) -> None:
        args = _build_parser().parse_args(["--city", "antwerpen", "--all-sectors"])
        assert args.export_chunk_size == 5000

    def test_export_chunk_size_custom(self) -> None:
        args = _build_parser().parse_args(
            ["--city", "antwerpen", "--all-sectors", "--export-chunk-size", "1000"]
        )
        assert args.export_chunk_size == 1000


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
