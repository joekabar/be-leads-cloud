"""Unit tests for scraper.lib.data_paths."""

from __future__ import annotations

from pathlib import Path

from scraper.lib.data_paths import PER_HOST_TOML, POSTCODES_TOML, SECTORS_TOML


class TestDataPaths:
    def test_per_host_toml_exists(self) -> None:
        assert PER_HOST_TOML.exists(), f"per-host.toml not found at {PER_HOST_TOML}"

    def test_sectors_toml_exists(self) -> None:
        assert SECTORS_TOML.exists(), f"sectors.toml not found at {SECTORS_TOML}"

    def test_postcodes_toml_exists(self) -> None:
        assert POSTCODES_TOML.exists(), f"postcodes.toml not found at {POSTCODES_TOML}"

    def test_per_host_toml_is_in_lib_dir(self) -> None:
        assert PER_HOST_TOML.parent.name == "lib"

    def test_sectors_toml_is_in_lib_dir(self) -> None:
        assert SECTORS_TOML.parent.name == "lib"

    def test_postcodes_toml_is_in_lib_dir(self) -> None:
        assert POSTCODES_TOML.parent.name == "lib"

    def test_per_host_toml_is_path(self) -> None:
        assert isinstance(PER_HOST_TOML, Path)

    def test_sectors_toml_is_readable(self) -> None:
        import tomllib

        with SECTORS_TOML.open("rb") as fh:
            data = tomllib.load(fh)
        assert isinstance(data, dict)
        assert len(data) > 0

    def test_per_host_toml_is_readable(self) -> None:
        import tomllib

        with PER_HOST_TOML.open("rb") as fh:
            data = tomllib.load(fh)
        assert isinstance(data, dict)
