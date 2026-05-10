from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

_SCRIPT = (
    Path(__file__).parents[3]
    / ".claude"
    / "skills"
    / "provenance-schema"
    / "scripts"
    / "verify_no_updates.sh"
)
_SRC = Path(__file__).parents[3] / "src"


def _bash() -> str:
    """Return the path to a working bash, preferring Git bash on Windows."""
    if sys.platform == "win32":
        git_bash = Path(r"C:\Program Files\Git\usr\bin\bash.exe")
        if git_bash.exists():
            return str(git_bash)
    import shutil

    found = shutil.which("bash")
    if found:
        return found
    pytest.skip("bash not available on this system")
    return ""  # unreachable


def _run_guard(search_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_bash(), str(_SCRIPT), str(search_dir)],
        capture_output=True,
        text=True,
    )


def test_guard_passes_on_clean_tree() -> None:
    result = _run_guard(_SRC)
    assert result.returncode == 0, f"Expected exit 0, stderr: {result.stderr}"


def test_guard_fails_on_injected_update(tmp_path: Path) -> None:
    bad_file = tmp_path / "bad_temp.py"
    bad_file.write_text("conn.execute('UPDATE observations SET confidence=1')\n")
    result = _run_guard(tmp_path)
    assert result.returncode == 2, f"Expected exit 2, got {result.returncode}"
    assert "ERROR" in result.stderr


def test_guard_fails_on_companies_current_update(tmp_path: Path) -> None:
    bad_file = tmp_path / "bad_view.sql"
    bad_file.write_text("UPDATE companies_current SET confidence = 1.0;\n")
    result = _run_guard(tmp_path)
    assert result.returncode == 2
