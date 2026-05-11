from __future__ import annotations

from typing import TYPE_CHECKING

from scraper.db.models import Observation

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from scraper.sources.nbb_authentic.parser import FilingData

_CONFIDENCE = 1.00
_BASE_URL = "https://ws.cbso.nbb.be"


def filing_to_observations(
    kbo_number: str,
    filing: FilingData,
    run_id: UUID,
    snapshot_at: datetime,
) -> list[Observation]:
    """Up to 3 observations per filing: revenue_YYYY, profit_YYYY, employees_YYYY.

    Skips fields whose value is None — 'not reported' must not be conflated with zero.
    """
    obs: list[Observation] = []
    year = filing.exercise_year
    source_url = (
        f"{_BASE_URL}/authentic/legalEntity/{kbo_number}"
        f"/references/{filing.reference_number}/accountingData"
    )

    if filing.revenue is not None:
        obs.append(
            Observation(
                kbo_number=kbo_number,
                field=f"revenue_{year}",
                value={
                    "value": filing.revenue,
                    "currency": "EUR",
                    "filing_ref": filing.reference_number,
                    "model_type": filing.model_type,
                },
                raw_value=str(filing.revenue),
                source="nbb_authentic",
                source_url=source_url,
                observed_at=snapshot_at,
                confidence=_CONFIDENCE,
                run_id=run_id,
            )
        )

    if filing.profit_loss is not None:
        obs.append(
            Observation(
                kbo_number=kbo_number,
                field=f"profit_{year}",
                value={
                    "value": filing.profit_loss,
                    "currency": "EUR",
                    "filing_ref": filing.reference_number,
                    "model_type": filing.model_type,
                },
                raw_value=str(filing.profit_loss),
                source="nbb_authentic",
                source_url=source_url,
                observed_at=snapshot_at,
                confidence=_CONFIDENCE,
                run_id=run_id,
            )
        )

    if filing.employees_fte is not None:
        obs.append(
            Observation(
                kbo_number=kbo_number,
                field=f"employees_{year}",
                value={
                    "value": filing.employees_fte,
                    "filing_ref": filing.reference_number,
                    "model_type": filing.model_type,
                },
                raw_value=str(filing.employees_fte),
                source="nbb_authentic",
                source_url=source_url,
                observed_at=snapshot_at,
                confidence=_CONFIDENCE,
                run_id=run_id,
            )
        )

    return obs
