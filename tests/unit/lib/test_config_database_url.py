"""Tests for the non-raising DATABASE_URL accessor used by the Streamlit pages.

Both UI pages read os.environ["DATABASE_URL"] directly, which returns "" whenever
nothing has loaded .env yet — the results fetch is then silently skipped and the page
renders an empty table with no error.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scraper.lib.config import database_url, load_settings, project_root


class TestProjectRoot:
    def test_finds_directory_with_pyproject(self) -> None:
        assert (project_root() / "pyproject.toml").is_file()

    def test_is_cwd_independent(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        before = project_root()
        monkeypatch.chdir(tmp_path)
        assert project_root() == before


class TestDatabaseUrl:
    def test_returns_configured_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost/db")
        assert database_url() == "postgresql://u:p@localhost/db"

    def test_returns_empty_string_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Non-raising so the page can render an actionable error instead of crashing."""
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: True)
        assert database_url() == ""


class TestDotenvIsRootAnchored:
    def test_default_env_file_is_project_root(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: list[Path | None] = []

        def _spy(path: Path | None = None, **_: object) -> bool:
            seen.append(path)
            return True

        monkeypatch.setattr("dotenv.load_dotenv", _spy)
        monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost/db")
        monkeypatch.chdir(tmp_path)

        load_settings()

        assert seen == [project_root() / ".env"]
