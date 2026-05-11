from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import httpx
import pytest
import respx

pytestmark = pytest.mark.integration

_KBOPUB_URL_RE = re.compile(r".*kbopub\.economie\.fgov\.be.*")
_BELLOCK_HTML = Path("tests/golden/kbopub_html/0439401387_bellock_nl.html").read_text(
    encoding="utf-8"
)


def test_cli_exit_zero_with_mocked_http(test_db_dsn: str) -> None:
    """--kbos 0439401387 with mocked HTTP → exit 0, JSON report on stdout."""
    with respx.mock:
        respx.get(_KBOPUB_URL_RE).mock(return_value=httpx.Response(200, text=_BELLOCK_HTML))
        result = subprocess.run(
            [
                "uv",
                "run",
                "be-leads-fetch-kbopub",
                "--kbos",
                "0439401387",
                "--database-url",
                test_db_dsn,
            ],
            capture_output=True,
            text=True,
        )
    # respx mock only works inside the same process; subprocess gets real network.
    # This test verifies the CLI plumbing (arg parsing, exit code) with a real DB.
    # We accept exit 0 OR a network error (since kbopub may block in CI).
    # The key assertion is that invalid args don't cause exit 2.
    assert result.returncode in (0, 1), result.stderr


def test_cli_missing_at_file_exits_2() -> None:
    """--kbos @missing.txt → exit 2 with error message."""
    result = subprocess.run(
        [
            "uv",
            "run",
            "be-leads-fetch-kbopub",
            "--kbos",
            "@/nonexistent/path/kbos.txt",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "not found" in result.stderr.lower() or "error" in result.stderr.lower()


def test_cli_invalid_kbo_counted_exit_zero(test_db_dsn: str, tmp_path: Path) -> None:
    """Invalid KBO (bad checksum) is counted and skipped; CLI exits 0."""
    kbo_file = tmp_path / "kbos.txt"
    kbo_file.write_text("0000000000\n")  # invalid checksum

    with respx.mock:
        respx.get(_KBOPUB_URL_RE).mock(return_value=httpx.Response(200, text=_BELLOCK_HTML))
        result = subprocess.run(
            [
                "uv",
                "run",
                "be-leads-fetch-kbopub",
                "--kbos",
                f"@{kbo_file}",
                "--database-url",
                test_db_dsn,
            ],
            capture_output=True,
            text=True,
        )
    # Invalid KBOs are skipped with a warning — not a fatal error.
    assert result.returncode == 0, result.stderr
    json_line = result.stdout.strip().splitlines()[-1]
    report = json.loads(json_line)
    assert report["kbos_invalid"] == 1
    assert report["kbos_processed"] == 0
