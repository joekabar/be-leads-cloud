from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from io import BytesIO
from typing import Any, Literal

import structlog

logger = structlog.get_logger()

# Belgian number format: dots = thousands separator, comma = decimal.
# Examples: "65.828" → 65828, "-25.390" → -25390, "4,0" → 4.0
_BE_NUM_RE = re.compile(r"^-?[0-9]{1,3}(?:\.[0-9]{3})*(?:,[0-9]+)?$")


def _parse_belgian_number(s: str) -> float | None:
    s = s.strip()
    if not _BE_NUM_RE.match(s):
        return None
    if "," in s:
        cleaned = s.replace(".", "").replace(",", ".")
    else:
        cleaned = s.replace(".", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _to_model_type(raw: str) -> Literal["MICRO", "ABBREVIATED", "FULL", "CONSOLIDATED", "OTHER"]:
    if raw == "MICRO":
        return "MICRO"
    if raw == "ABBREVIATED":
        return "ABBREVIATED"
    if raw == "FULL":
        return "FULL"
    if raw == "CONSOLIDATED":
        return "CONSOLIDATED"
    return "OTHER"


@dataclass(frozen=True, slots=True)
class ReferenceRow:
    reference_number: str
    deposit_date: date
    exercise_start: date
    exercise_end: date
    model_type: Literal["MICRO", "ABBREVIATED", "FULL", "CONSOLIDATED", "OTHER"]
    language: str
    deposit_type: str
    filing_method: str
    accounting_data_url: str = field(default="")


@dataclass(frozen=True, slots=True)
class FilingData:
    reference_number: str
    exercise_year: int
    revenue: int | None
    profit_loss: int | None
    employees_fte: float | None
    model_type: str


def parse_references(payload: list[Any] | dict[str, Any]) -> list[ReferenceRow]:
    """Parse /references JSON response into a list of ReferenceRow objects.

    The live API returns a list directly with PascalCase keys and a nested
    ExerciseDates object.  Older golden fixtures use a {"references": [...]}
    wrapper with camelCase keys — both formats are accepted.
    """
    if isinstance(payload, list):
        items: list[Any] = payload
    else:
        items = payload.get("references", [])

    rows: list[ReferenceRow] = []
    for raw in items:
        try:
            ref_num = raw.get("ReferenceNumber") or raw["referenceNumber"]
            deposit_raw = raw.get("DepositDate") or raw["depositDate"]
            ex_dates = raw.get("ExerciseDates")
            if ex_dates:
                start_raw = ex_dates["startDate"]
                end_raw = ex_dates["endDate"]
            else:
                start_raw = raw["exerciseStart"]
                end_raw = raw["exerciseEnd"]
            model_raw = raw.get("ModelType") or raw.get("modelType", "")
            lang = raw.get("Language") or raw.get("language", "")
            dep_type = raw.get("DepositType") or raw.get("depositType", "")
            filing_m = raw.get("FilingMethod") or raw.get("filingMethod", "")
            acct_url = raw.get("AccountingDataURL") or raw.get("accountingDataURL") or ""
            rows.append(
                ReferenceRow(
                    reference_number=ref_num,
                    deposit_date=date.fromisoformat(deposit_raw),
                    exercise_start=date.fromisoformat(start_raw),
                    exercise_end=date.fromisoformat(end_raw),
                    model_type=_to_model_type(model_raw),
                    language=lang,
                    deposit_type=dep_type,
                    filing_method=filing_m,
                    accounting_data_url=acct_url or "",
                )
            )
        except (KeyError, ValueError, TypeError):
            logger.warning("nbb_reference_parse_failed", raw=raw)
    return rows


# ---------------------------------------------------------------------------
# PDF-based accounting data extraction
# ---------------------------------------------------------------------------

# Codes we want to extract from the PDF.
# Priority order for revenue: 700 (full), 70 (abbreviated), 9900 (Brutomarge proxy).
_REVENUE_CODES = ("700", "70", "9900")
_PROFIT_CODES = ("9904",)
_EMPLOYEE_CODES = ("9087", "9086")

# All codes we scan for — we stop scanning each code once found.
_ALL_TARGET_CODES = frozenset((*_REVENUE_CODES, *_PROFIT_CODES, *_EMPLOYEE_CODES))


def _extract_code_values(pdf_bytes: bytes) -> dict[str, float]:
    """Return {code: current_year_value} for Belgian GAAP codes found in the PDF.

    Strategy (using pdfminer LTTextLine for per-line Y positions):
    1. Collect all text lines with (x, y, text).
    2. Lines in the code column (x < 380) that match a target code string.
    3. For each code line, find the nearest numeric value at the same Y (within
       6 pt) in the value columns (x > 380).  The leftmost such value is the
       current-year column; the second (larger x) is prior year — we want only
       the first.
    """
    from pdfminer.high_level import extract_pages
    from pdfminer.layout import LAParams, LTTextBox, LTTextLine

    params = LAParams(boxes_flow=None)
    lines: list[tuple[int, float, float, str]] = []  # (page, x, y, text)

    try:
        for pg, page in enumerate(extract_pages(BytesIO(pdf_bytes), laparams=params)):
            for el in page:
                if isinstance(el, LTTextBox):
                    for ln in el:
                        if isinstance(ln, LTTextLine):
                            txt = ln.get_text().strip()
                            if txt:
                                lines.append((pg, el.x0, ln.y0, txt))
    except Exception:
        logger.warning("nbb_pdf_extraction_failed")
        return {}

    result: dict[str, float] = {}

    for pg, cx, cy, ct in lines:
        if cx >= 380:
            continue  # skip value/description columns at code scan step
        # A line may contain multiple whitespace-separated tokens; check each.
        for token in ct.split():
            if token not in _ALL_TARGET_CODES:
                continue
            if token in result:
                continue  # already found this code on an earlier page
            # Find numeric values at the same Y on the right side.
            candidates: list[tuple[float, float]] = []  # (x, value)
            for vpg, vx, vy, vt in lines:
                if vpg != pg or vx <= 380:
                    continue
                if abs(vy - cy) > 6:
                    continue
                val = _parse_belgian_number(vt)
                if val is not None:
                    candidates.append((vx, val))
            if candidates:
                candidates.sort()  # leftmost = current year
                result[token] = candidates[0][1]

    return result


def parse_accounting_pdf(reference: ReferenceRow, pdf_bytes: bytes) -> FilingData:
    """Extract key financial figures from an NBB annual accounts PDF.

    The live NBB /accountingData endpoint returns PDF, not JSON. This function
    uses positional text extraction to recover Belgian GAAP codes and map them
    to their current-year values.

    Revenue priority: code 700 (full model) > 70 (abbreviated) > 9900 (Brutomarge
    proxy — gross margin, used when turnover is not individually disclosed, e.g.
    some MICRO filings).
    """
    code_values = _extract_code_values(pdf_bytes)

    revenue: int | None = None
    for rc in _REVENUE_CODES:
        if rc in code_values:
            revenue = int(code_values[rc])
            break

    profit_loss: int | None = None
    for pc in _PROFIT_CODES:
        if pc in code_values:
            profit_loss = int(code_values[pc])
            break

    employees_fte: float | None = None
    for ec in _EMPLOYEE_CODES:
        if ec in code_values:
            employees_fte = code_values[ec]
            break

    return FilingData(
        reference_number=reference.reference_number,
        exercise_year=reference.exercise_end.year,
        revenue=revenue,
        profit_loss=profit_loss,
        employees_fte=employees_fte,
        model_type=reference.model_type,
    )


def parse_accounting_data(reference: ReferenceRow, payload: dict[str, Any]) -> FilingData:
    """Parse a JSON /accountingData response into FilingData (legacy path).

    The live NBB API does not serve JSON for this endpoint; use parse_accounting_pdf
    instead. This function is retained for unit tests and future compatibility.
    """
    revenue: int | None = None
    if payload.get("code_700") is not None:
        revenue = int(payload["code_700"])
    elif payload.get("code_70") is not None:
        revenue = int(payload["code_70"])

    profit_loss: int | None = None
    raw_profit = payload.get("code_9904")
    if raw_profit is not None:
        profit_loss = int(raw_profit)

    employees_fte: float | None = None
    raw_emp = payload.get("code_9087")
    if raw_emp is not None:
        employees_fte = float(raw_emp)

    return FilingData(
        reference_number=reference.reference_number,
        exercise_year=reference.exercise_end.year,
        revenue=revenue,
        profit_loss=profit_loss,
        employees_fte=employees_fte,
        model_type=reference.model_type,
    )
