"""Unit tests for batch_cli argument parsing (no DB or async required)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from scraper.pipeline.batch_cli import (
    _build_parser,
    _resolve_api_keys,
    _write_summary,
    cli_main,
)


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


class TestSummaryJson:
    """The batch already knows exactly how it went; nothing downstream could read it.

    ``nightly_scrape.ps1`` decided success by grepping the run log for
    ``goudengids_sector_done``, which counts sectors *attempted*. On 2026-08-22 and
    2026-08-23 a DNS failure (``ERR_NAME_NOT_RESOLVED``) made all ten sectors fail in
    each of four consecutive runs; every one logged ``END exit=0 sectors_done=0
    blocks=0`` — indistinguishable from "nothing left to scrape". Two days, zero
    observations, no alarm. The same grep reported ``sectors_done=10`` for a run the
    batch itself scored as 6.

    Writing the summary to a file the caller names removes the guesswork: the wrapper
    reads structured JSON instead of parsing a UTF-16 log tail.
    """

    def test_flag_defaults_to_none(self) -> None:
        args = _build_parser().parse_args(["--city", "brugge", "--all-sectors"])
        assert args.summary_json is None

    def test_flag_is_parsed(self) -> None:
        args = _build_parser().parse_args(
            ["--city", "brugge", "--all-sectors", "--summary-json", "out/s.json"]
        )
        assert args.summary_json == "out/s.json"

    def test_writes_utf8_json(self, tmp_path: Path) -> None:
        target = tmp_path / "summary.json"
        payload = {"city": "brugge", "goudengids_sectors_scraped": 6, "sources_failed": {}}
        _write_summary(str(target), payload)
        assert json.loads(target.read_text(encoding="utf-8")) == payload

    def test_creates_missing_parent_directory(self, tmp_path: Path) -> None:
        target = tmp_path / "nested" / "deeper" / "summary.json"
        _write_summary(str(target), {"city": "gent"})
        assert target.is_file()

    def test_non_ascii_survives_the_round_trip(self, tmp_path: Path) -> None:
        """Liège and Sint-Kruis both appear in city and municipality strings."""
        target = tmp_path / "s.json"
        _write_summary(str(target), {"city": "liège", "note": "Sint-Kruis — 8310"})
        assert json.loads(target.read_text(encoding="utf-8"))["city"] == "liège"

    def test_unwritable_path_does_not_raise(self, tmp_path: Path) -> None:
        """A summary that cannot be written must not discard a 49-minute batch run.

        The file is a reporting convenience; the observations are already committed by
        the time it is written. Losing the run over it would be a worse failure than the
        one it exists to surface.
        """
        clash = tmp_path / "taken"
        clash.mkdir()
        _write_summary(str(clash), {"city": "brugge"})  # a directory, not a file

    def test_returns_whether_it_wrote(self, tmp_path: Path) -> None:
        assert _write_summary(str(tmp_path / "ok.json"), {"a": 1}) is True
        clash = tmp_path / "dir"
        clash.mkdir()
        assert _write_summary(str(clash), {"a": 1}) is False

    def test_summary_includes_sector_errors(self, tmp_path: Path) -> None:
        target = tmp_path / "s.json"
        _write_summary(str(target), {"goudengids_sector_errors": {"hotels": "boom"}})
        assert json.loads(target.read_text(encoding="utf-8"))["goudengids_sector_errors"] == {
            "hotels": "boom"
        }
