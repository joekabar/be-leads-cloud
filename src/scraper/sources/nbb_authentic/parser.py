from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

import structlog

logger = structlog.get_logger()


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


@dataclass(frozen=True, slots=True)
class FilingData:
    reference_number: str
    exercise_year: int
    revenue: int | None
    profit_loss: int | None
    employees_fte: float | None
    model_type: str


def parse_references(payload: dict[str, Any]) -> list[ReferenceRow]:
    """Parse /references JSON response into a list of ReferenceRow objects."""
    rows: list[ReferenceRow] = []
    for raw in payload.get("references", []):
        try:
            rows.append(
                ReferenceRow(
                    reference_number=raw["referenceNumber"],
                    deposit_date=date.fromisoformat(raw["depositDate"]),
                    exercise_start=date.fromisoformat(raw["exerciseStart"]),
                    exercise_end=date.fromisoformat(raw["exerciseEnd"]),
                    model_type=_to_model_type(raw.get("modelType", "")),
                    language=raw.get("language", ""),
                    deposit_type=raw.get("depositType", ""),
                    filing_method=raw.get("filingMethod", ""),
                )
            )
        except (KeyError, ValueError):
            logger.warning("nbb_reference_parse_failed", raw=raw)
    return rows


def parse_accounting_data(reference: ReferenceRow, payload: dict[str, Any]) -> FilingData:
    """Parse /accountingData JSON response into a FilingData.

    Revenue: code_700 (full schema) takes precedence over code_70 (abbreviated).
    All values default to None if missing or explicitly null — do NOT emit null observations.
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
