from __future__ import annotations

import json
import re
import sys

import pytest
import respx

from scraper.sources.nbb_authentic import cli as cli_module
from scraper.sources.nbb_authentic.cli import cli_main

from .conftest import nbb_side_effect

pytestmark = pytest.mark.integration

_NBB_RE = re.compile(r".*ws\.cbso\.nbb\.be.*")


# ---------------------------------------------------------------------------
# Missing subscription key → exit 2
# ---------------------------------------------------------------------------


def test_missing_key_exits_2(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["be-leads-fetch-nbb", "--kbos", "0439401387"])
    monkeypatch.delenv("NBB_CBSO_API_KEY", raising=False)
    with pytest.raises(SystemExit) as exc:
        cli_main()
    assert exc.value.code == 2


# ---------------------------------------------------------------------------
# Successful run → exit 0, JSON report on stdout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_success_prints_json(
    clean_pool,  # type: ignore[no-untyped-def]
    test_db_dsn: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with respx.mock:
        respx.get(_NBB_RE).mock(side_effect=nbb_side_effect)
        await cli_module._run(
            kbos=["0439401387"],
            database_url=test_db_dsn,
            subscription_key="dummy-key",
            skip_recent_hours=0,
            years_back=None,
        )

    out = capsys.readouterr().out
    # structlog also writes to stdout; the JSON report is always the last non-empty line
    last_line = [ln for ln in out.splitlines() if ln.strip()][-1]
    data = json.loads(last_line)
    assert data["kbos_processed"] == 1
    # MICRO PDF: revenue (9900 proxy) + profit_loss per reference, no employees → 2 obs × 3 refs = 6
    assert data["observations_inserted"] == 6
    assert data["references_total"] == 3
    assert "duration_s" in data
