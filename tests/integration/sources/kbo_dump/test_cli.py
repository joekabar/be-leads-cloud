from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def test_cli_ingest_exit_zero(synthetic_zip: Path, test_db_dsn: str) -> None:
    result = subprocess.run(
        [
            "uv",
            "run",
            "be-leads-ingest-kbo",
            "--zip",
            str(synthetic_zip),
            "--database-url",
            test_db_dsn,
            "--no-refresh",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    # structlog lines go to stdout; the JSON report is the last line
    json_line = result.stdout.strip().splitlines()[-1]
    report = json.loads(json_line)
    assert report["extract_type"] == "Full"
    assert report["snapshot_date"] == "2026-04-15"
    assert isinstance(report["observations_inserted"], int)
    assert report["phones_invalid_skipped"] == 1


def test_cli_validate_valid() -> None:
    result = subprocess.run(
        ["uv", "run", "be-leads-validate-kbo", "0439.401.387"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "valid" in result.stdout
    assert "0439401387" in result.stdout


def test_cli_validate_valid_with_prefix() -> None:
    result = subprocess.run(
        ["uv", "run", "be-leads-validate-kbo", "BE0439401387"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "valid" in result.stdout


def test_cli_validate_invalid_exits_2() -> None:
    result = subprocess.run(
        ["uv", "run", "be-leads-validate-kbo", "123"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "invalid" in result.stderr


def test_cli_validate_wrong_check_digit() -> None:
    result = subprocess.run(
        ["uv", "run", "be-leads-validate-kbo", "0439401388"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
