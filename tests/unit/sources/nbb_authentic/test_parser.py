from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from scraper.sources.nbb_authentic.parser import (
    FilingData,
    ReferenceRow,
    parse_accounting_data,
    parse_accounting_pdf,
    parse_references,
)

_GOLDEN = Path("tests/golden/nbb_authentic")


def _load(filename: str) -> dict:  # type: ignore[type-arg]
    return json.loads((_GOLDEN / filename).read_text())


# ---------------------------------------------------------------------------
# parse_references
# ---------------------------------------------------------------------------


def test_parse_references_three_filings() -> None:
    refs = parse_references(_load("0439401387_references.json"))
    assert len(refs) == 3


def test_parse_references_types() -> None:
    refs = parse_references(_load("0439401387_references.json"))
    for r in refs:
        assert isinstance(r, ReferenceRow)
        assert isinstance(r.deposit_date, date)
        assert isinstance(r.exercise_start, date)
        assert isinstance(r.exercise_end, date)
        assert r.model_type == "ABBREVIATED"


def test_parse_references_reference_numbers() -> None:
    refs = parse_references(_load("0439401387_references.json"))
    ref_nums = {r.reference_number for r in refs}
    assert ref_nums == {"2024-00000148", "2023-00000119", "2022-00000091"}


def test_parse_references_exercise_years() -> None:
    refs = parse_references(_load("0439401387_references.json"))
    years = {r.exercise_end.year for r in refs}
    assert years == {2021, 2022, 2023}


def test_parse_references_empty_returns_empty_list() -> None:
    refs = parse_references(_load("9999999991_references_empty.json"))
    assert refs == []


def test_parse_references_missing_references_key() -> None:
    refs = parse_references({})
    assert refs == []


# ---------------------------------------------------------------------------
# parse_accounting_data — all fields present
# ---------------------------------------------------------------------------

_REF_2024 = ReferenceRow(
    reference_number="2024-00000148",
    deposit_date=date(2024, 9, 12),
    exercise_start=date(2023, 1, 1),
    exercise_end=date(2023, 12, 31),
    model_type="ABBREVIATED",
    language="NL",
    deposit_type="DEPOSIT",
    filing_method="STRUCTURED",
)

_REF_MICRO = ReferenceRow(
    reference_number="2024-00012345",
    deposit_date=date(2024, 6, 15),
    exercise_start=date(2023, 1, 1),
    exercise_end=date(2023, 12, 31),
    model_type="MICRO",
    language="NL",
    deposit_type="DEPOSIT",
    filing_method="STRUCTURED",
)

_REF_NO_EMP = ReferenceRow(
    reference_number="2024-00099999",
    deposit_date=date(2024, 6, 30),
    exercise_start=date(2023, 1, 1),
    exercise_end=date(2023, 12, 31),
    model_type="ABBREVIATED",
    language="NL",
    deposit_type="DEPOSIT",
    filing_method="STRUCTURED",
)


def test_parse_accounting_data_all_fields() -> None:
    filing = parse_accounting_data(_REF_2024, _load("0439401387_accounting_2024-00000148.json"))
    assert isinstance(filing, FilingData)
    assert filing.revenue == 340000
    assert filing.profit_loss == 30326
    assert filing.employees_fte == 4.0


def test_parse_accounting_data_exercise_year() -> None:
    filing = parse_accounting_data(_REF_2024, _load("0439401387_accounting_2024-00000148.json"))
    assert filing.exercise_year == 2023


def test_parse_accounting_data_null_revenue() -> None:
    filing = parse_accounting_data(_REF_MICRO, _load("0502699332_accounting_2024-00012345.json"))
    assert filing.revenue is None
    assert filing.profit_loss == 8500
    assert filing.employees_fte == 1.5


def test_parse_accounting_data_null_employees() -> None:
    filing = parse_accounting_data(_REF_NO_EMP, _load("0212037309_accounting_no_employees.json"))
    assert filing.employees_fte is None
    assert filing.revenue == 45000
    assert filing.profit_loss == 12000


def test_parse_accounting_data_missing_employees_key() -> None:
    payload = {"code_70": 50000, "code_9904": 5000}
    filing = parse_accounting_data(_REF_2024, payload)
    assert filing.employees_fte is None


def test_parse_accounting_data_prefers_code_700_over_code_70() -> None:
    payload = {"code_700": 999999, "code_70": 111111, "code_9904": 5000, "code_9087": 2.0}
    filing = parse_accounting_data(_REF_2024, payload)
    assert filing.revenue == 999999


def test_parse_accounting_data_falls_back_to_code_70_when_no_700() -> None:
    payload = {"code_70": 111111, "code_9904": 5000}
    filing = parse_accounting_data(_REF_2024, payload)
    assert filing.revenue == 111111


def test_parse_accounting_data_empty_payload_all_none() -> None:
    filing = parse_accounting_data(_REF_2024, {})
    assert filing.revenue is None
    assert filing.profit_loss is None
    assert filing.employees_fte is None


def test_parse_accounting_data_model_type_propagated() -> None:
    filing = parse_accounting_data(_REF_MICRO, _load("0502699332_accounting_2024-00012345.json"))
    assert filing.model_type == "MICRO"


# ---------------------------------------------------------------------------
# Additional model_type coverage: FULL, CONSOLIDATED, OTHER
# ---------------------------------------------------------------------------

_REF_TEMPLATE = {
    "depositDate": "2024-01-01",
    "exerciseStart": "2023-01-01",
    "exerciseEnd": "2023-12-31",
    "language": "NL",
    "depositType": "DEPOSIT",
    "filingMethod": "STRUCTURED",
}


def test_parse_references_full_model_type() -> None:
    payload = {
        "references": [{**_REF_TEMPLATE, "referenceNumber": "2024-00000001", "modelType": "FULL"}]
    }
    refs = parse_references(payload)
    assert refs[0].model_type == "FULL"


def test_parse_references_consolidated_model_type() -> None:
    payload = {
        "references": [
            {**_REF_TEMPLATE, "referenceNumber": "2024-00000002", "modelType": "CONSOLIDATED"}
        ]
    }
    refs = parse_references(payload)
    assert refs[0].model_type == "CONSOLIDATED"


def test_parse_references_unknown_model_type_becomes_other() -> None:
    payload = {
        "references": [
            {**_REF_TEMPLATE, "referenceNumber": "2024-00000003", "modelType": "XBRL_LEGACY"}
        ]
    }
    refs = parse_references(payload)
    assert refs[0].model_type == "OTHER"


def test_parse_references_skips_malformed_entry_and_keeps_valid() -> None:
    valid = {**_REF_TEMPLATE, "referenceNumber": "2024-00000148", "modelType": "ABBREVIATED"}
    malformed = {"badKey": "missingRequiredFields"}
    refs = parse_references({"references": [valid, malformed]})
    assert len(refs) == 1
    assert refs[0].reference_number == "2024-00000148"


# ---------------------------------------------------------------------------
# Actual live API format: list with PascalCase keys + nested ExerciseDates
# ---------------------------------------------------------------------------

_LIVE_ITEM = {
    "ReferenceNumber": "2024-00290653",
    "DepositDate": "2024-07-26",
    "ExerciseDates": {"startDate": "2023-01-01", "endDate": "2023-12-31"},
    "ModelType": "m02-f",
    "DepositType": "Initial",
    "Language": "NL",
    "Currency": "EUR",
    "AccountingDataURL": "https://ws.cbso.nbb.be/authentic/deposit/2024-00290653/accountingData",
}


def test_parse_references_accepts_live_list_format() -> None:
    refs = parse_references([_LIVE_ITEM])
    assert len(refs) == 1
    r = refs[0]
    assert r.reference_number == "2024-00290653"
    assert r.deposit_date.isoformat() == "2024-07-26"
    assert r.exercise_start.isoformat() == "2023-01-01"
    assert r.exercise_end.isoformat() == "2023-12-31"
    assert r.language == "NL"
    assert r.deposit_type == "Initial"


def test_parse_references_live_unknown_model_type_becomes_other() -> None:
    refs = parse_references([_LIVE_ITEM])
    assert refs[0].model_type == "OTHER"


def test_parse_references_live_empty_list_returns_empty() -> None:
    assert parse_references([]) == []


def test_parse_references_live_accounting_data_url_captured() -> None:
    refs = parse_references([_LIVE_ITEM])
    assert refs[0].accounting_data_url == (
        "https://ws.cbso.nbb.be/authentic/deposit/2024-00290653/accountingData"
    )


def test_parse_references_camelcase_accounting_data_url_missing_gives_empty() -> None:
    refs = parse_references(_load("0439401387_references.json"))
    # Legacy camelCase fixtures have no accountingDataURL — default must be empty string
    assert all(r.accounting_data_url == "" for r in refs)


# ---------------------------------------------------------------------------
# parse_accounting_pdf — real PDF golden fixtures
# ---------------------------------------------------------------------------

_PDF_GOLDEN = Path("tests/golden/nbb_authentic")

_REF_MICRO_2024 = ReferenceRow(
    reference_number="2024-00290653",
    deposit_date=date(2024, 7, 26),
    exercise_start=date(2023, 1, 1),
    exercise_end=date(2023, 12, 31),
    model_type="OTHER",  # m87-f maps to OTHER
    language="NL",
    deposit_type="Initial",
    filing_method="",
    accounting_data_url="https://ws.cbso.nbb.be/authentic/deposit/2024-00290653/accountingData",
)

_REF_ABBREV_2019 = ReferenceRow(
    reference_number="2019-35100012",
    deposit_date=date(2019, 7, 19),
    exercise_start=date(2018, 1, 1),
    exercise_end=date(2018, 12, 31),
    model_type="OTHER",  # m07-f maps to OTHER
    language="NL",
    deposit_type="Initial",
    filing_method="",
    accounting_data_url="https://ws.cbso.nbb.be/authentic/deposit/2019-35100012/accountingData",
)


def test_parse_accounting_pdf_micro_profit_loss() -> None:
    pdf = (_PDF_GOLDEN / "0439401387_pdf_2024-00290653.pdf").read_bytes()
    filing = parse_accounting_pdf(_REF_MICRO_2024, pdf)
    assert filing.exercise_year == 2023
    # code 9904 = -25.390 in Belgian format → -25390
    assert filing.profit_loss == -25390


def test_parse_accounting_pdf_micro_revenue_uses_brutomarge_proxy() -> None:
    pdf = (_PDF_GOLDEN / "0439401387_pdf_2024-00290653.pdf").read_bytes()
    filing = parse_accounting_pdf(_REF_MICRO_2024, pdf)
    # MICRO model: code 70 present but no value; code 9900 (Brutomarge) used as proxy
    assert filing.revenue is not None
    assert filing.revenue > 0


def test_parse_accounting_pdf_micro_no_employees() -> None:
    pdf = (_PDF_GOLDEN / "0439401387_pdf_2024-00290653.pdf").read_bytes()
    filing = parse_accounting_pdf(_REF_MICRO_2024, pdf)
    assert filing.employees_fte is None


def test_parse_accounting_pdf_abbreviated_profit_loss() -> None:
    pdf = (_PDF_GOLDEN / "0439401387_pdf_2019-35100012.pdf").read_bytes()
    filing = parse_accounting_pdf(_REF_ABBREV_2019, pdf)
    assert filing.exercise_year == 2018
    # code 9904 = 2.021 → 2021
    assert filing.profit_loss == 2021


def test_parse_accounting_pdf_abbreviated_revenue() -> None:
    pdf = (_PDF_GOLDEN / "0439401387_pdf_2019-35100012.pdf").read_bytes()
    filing = parse_accounting_pdf(_REF_ABBREV_2019, pdf)
    # code 9900 (Brutomarge) = 77.137 → 77137
    assert filing.revenue == 77137


def test_parse_accounting_pdf_empty_bytes_returns_all_none() -> None:
    filing = parse_accounting_pdf(_REF_MICRO_2024, b"not a pdf")
    assert filing.revenue is None
    assert filing.profit_loss is None
    assert filing.employees_fte is None
