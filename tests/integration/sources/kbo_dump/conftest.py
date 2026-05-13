from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

_MINI = Path("tests/golden/kbo_dump/synthetic_mini")

_LARGE_CACHE = Path(__file__).parents[3] / "golden" / "kbo_dump" / "large_10k" / "cached.zip"


@pytest.fixture(scope="session")
def synthetic_zip(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("zips") / "KboOpenData_42_2026_04_Full.zip"
    with zipfile.ZipFile(out, "w") as zf:
        for f in _MINI.glob("*.csv"):
            zf.write(f, arcname=f.name)
    return out


@pytest.fixture(scope="session")
def large_zip() -> Path:
    """10k-enterprise fixture ZIP, generated once per session and cached on disk."""
    if not _LARGE_CACHE.exists():
        from tests.integration.sources.kbo_dump._generate_large_fixture import build

        _LARGE_CACHE.parent.mkdir(parents=True, exist_ok=True)
        build(_LARGE_CACHE, n_enterprises=10_000, seed=42)
    return _LARGE_CACHE
