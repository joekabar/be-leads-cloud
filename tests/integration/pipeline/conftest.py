from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

_MINI = Path("tests/golden/kbo_dump/synthetic_mini")


@pytest.fixture(scope="session")
def pipeline_synthetic_zip(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("pipeline_zips") / "KboOpenData_fixture_Full.zip"
    with zipfile.ZipFile(out, "w") as zf:
        for f in _MINI.glob("*.csv"):
            zf.write(f, arcname=f.name)
    return out
