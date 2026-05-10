from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scraper.lib.validators import InvalidPhoneError, validate_phone
from scraper.lib.validators.phone import PhoneType, PhoneValidation

_PROJECT_ROOT = Path(__file__).parents[4]


# ---------------------------------------------------------------------------
# Antwerp landline — canonical format and format variants
# ---------------------------------------------------------------------------


def test_antwerp_landline_canonical() -> None:
    result = validate_phone("03 236 13 06")
    assert result.e164 == "+3232361306"
    assert result.type == PhoneType.FIXED_LINE
    assert result.region == "Antwerp-Sint-Niklaas"
    assert result.original_carrier is None
    assert result.raw == "03 236 13 06"


def test_antwerp_landline_e164_format() -> None:
    result = validate_phone("+3232361306")
    assert result.e164 == "+3232361306"
    assert result.type == PhoneType.FIXED_LINE
    assert result.region == "Antwerp-Sint-Niklaas"


def test_antwerp_landline_international_format() -> None:
    result = validate_phone("+32 3 236 13 06")
    assert result.e164 == "+3232361306"
    assert result.type == PhoneType.FIXED_LINE
    assert result.region == "Antwerp-Sint-Niklaas"


def test_antwerp_landline_00_prefix() -> None:
    result = validate_phone("0032 3 236 13 06")
    assert result.e164 == "+3232361306"
    assert result.type == PhoneType.FIXED_LINE
    assert result.region == "Antwerp-Sint-Niklaas"


def test_antwerp_landline_dot_format() -> None:
    result = validate_phone("03.236.13.06")
    assert result.e164 == "+3232361306"
    assert result.type == PhoneType.FIXED_LINE
    assert result.region == "Antwerp-Sint-Niklaas"


# ---------------------------------------------------------------------------
# Mobile numbers — carrier allocation
# ---------------------------------------------------------------------------


def test_mobile_proximus_047x() -> None:
    result = validate_phone("0474 12 34 56")
    assert result.type == PhoneType.MOBILE
    assert result.region is None
    assert result.original_carrier == "Proximus"


def test_mobile_telenet_0467() -> None:
    result = validate_phone("0467 12 34 56")
    assert result.type == PhoneType.MOBILE
    assert result.original_carrier == "Telenet"


def test_mobile_lycamobile_0465() -> None:
    result = validate_phone("0465 12 34 56")
    assert result.type == PhoneType.MOBILE
    assert result.original_carrier == "Lycamobile"


# ---------------------------------------------------------------------------
# Liège trap
# ---------------------------------------------------------------------------


def test_liege_landline_is_fixed_not_mobile() -> None:
    result = validate_phone("04 220 11 22")
    assert result.e164 == "+3242201122"
    assert result.type == PhoneType.FIXED_LINE
    assert result.region == "Liège-Voeren"
    assert result.original_carrier is None


def test_liege_mobile_boundary_is_mobile_not_fixed() -> None:
    result = validate_phone("0471 22 33 44")
    assert result.type == PhoneType.MOBILE
    assert result.region is None


# ---------------------------------------------------------------------------
# Other cities
# ---------------------------------------------------------------------------


def test_ghent_landline() -> None:
    result = validate_phone("09 234 56 78")
    assert result.type == PhoneType.FIXED_LINE
    assert result.region == "Ghent"


def test_brussels_landline() -> None:
    result = validate_phone("02 555 12 12")
    assert result.type == PhoneType.FIXED_LINE
    assert result.region == "Brussels"


# ---------------------------------------------------------------------------
# Special services
# ---------------------------------------------------------------------------


def test_premium_rate() -> None:
    result = validate_phone("0902 12 345")
    assert result.type == PhoneType.PREMIUM_RATE


def test_toll_free() -> None:
    result = validate_phone("0800 12 345")
    assert result.type == PhoneType.TOLL_FREE


def test_m2m() -> None:
    result = validate_phone("077 12 34 56")
    assert result.type == PhoneType.M2M
    assert result.region is None
    assert result.original_carrier is None


# ---------------------------------------------------------------------------
# Invalid inputs
# ---------------------------------------------------------------------------


def test_invalid_too_short() -> None:
    with pytest.raises(InvalidPhoneError):
        validate_phone("1234")


def test_invalid_letters() -> None:
    with pytest.raises(InvalidPhoneError):
        validate_phone("03 abc def gh")


def test_invalid_empty() -> None:
    with pytest.raises(InvalidPhoneError):
        validate_phone("")


def test_invalid_none() -> None:
    with pytest.raises(InvalidPhoneError):
        validate_phone(None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Pydantic model contract
# ---------------------------------------------------------------------------


def test_pydantic_model_round_trip() -> None:
    result = validate_phone("03 236 13 06")
    assert isinstance(result, PhoneValidation)
    d = result.model_dump()
    assert set(d.keys()) == {"e164", "raw", "type", "region", "original_carrier"}
    assert d["e164"] == "+3232361306"
    assert d["type"] == "fixed_line"
    assert d["region"] == "Antwerp-Sint-Niklaas"
    assert d["original_carrier"] is None


# ---------------------------------------------------------------------------
# TSV cache
# ---------------------------------------------------------------------------


def test_tsv_loader_cache() -> None:
    import scraper.lib.validators.phone as phone_module

    # Call _load_prefixes() twice to verify the TSV produces stable, identical output.
    # importlib.reload is intentionally avoided here: reload replaces class objects,
    # which breaks isinstance checks for classes imported at module level in other tests.
    first = phone_module._load_prefixes()
    second = phone_module._load_prefixes()
    assert first == second == dict(phone_module._PREFIXES)
    assert len(phone_module._PREFIXES) > 0


# ---------------------------------------------------------------------------
# CLI smoke (subprocess — no network, no DB)
# ---------------------------------------------------------------------------


def test_cli_smoke() -> None:
    proc = subprocess.run(
        ["uv", "run", "be-leads-validate-phone", "03 236 13 06"],
        capture_output=True,
        text=True,
        cwd=_PROJECT_ROOT,
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["e164"] == "+3232361306"
    assert data["type"] == "fixed_line"


# ---------------------------------------------------------------------------
# cli_main direct calls (covers the function body for coverage)
# ---------------------------------------------------------------------------


def test_cli_main_success(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.argv", ["be-leads-validate-phone", "03 236 13 06"])
    from scraper.lib.validators.phone import cli_main

    cli_main()
    data = json.loads(capsys.readouterr().out)
    assert data["e164"] == "+3232361306"
    assert data["type"] == "fixed_line"


def test_cli_main_invalid_exits(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.argv", ["be-leads-validate-phone", "1234"])
    from scraper.lib.validators.phone import cli_main

    with pytest.raises(SystemExit) as exc_info:
        cli_main()
    assert exc_info.value.code == 1
    assert "Error" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# phonenumbers fallback path and UNKNOWN rejection (covers lines 111-113, 135)
# ---------------------------------------------------------------------------


def test_phonenumbers_fallback_used_when_no_tsv_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scraper.lib.validators.phone as m

    monkeypatch.setattr(m, "_PREFIXES", {})
    result = validate_phone("03 236 13 06")
    assert result.type == PhoneType.FIXED_LINE


def test_unknown_type_rejected_when_no_tsv_match(monkeypatch: pytest.MonkeyPatch) -> None:
    import scraper.lib.validators.phone as m

    monkeypatch.setattr(m, "_PREFIXES", {})
    with pytest.raises(InvalidPhoneError):
        validate_phone("077 12 34 56")


# ---------------------------------------------------------------------------
# TSV missing at import (covers line 58)
# ---------------------------------------------------------------------------


def test_load_prefixes_raises_if_tsv_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import scraper.lib.validators.phone as m

    monkeypatch.setattr(m, "_TSV_PATH", tmp_path / "nonexistent.tsv")
    with pytest.raises(RuntimeError, match="not found"):
        m._load_prefixes()
