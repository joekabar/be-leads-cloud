from __future__ import annotations

from typing import TYPE_CHECKING, Any

from scraper.db.models import Observation

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from scraper.sources.kbopub_html.parser import FunctionHolderRow

# kbopub persons confidence prior (see .claude/skills/provenance-schema/references/confidence.md)
_CONFIDENCE = 0.95


def function_holder_to_observation(
    kbo_number: str,
    row: FunctionHolderRow,
    run_id: UUID,
    snapshot_at: datetime,
    *,
    source_url: str | None = None,
) -> Observation:
    """Produce a function_holder observation matching the JSONB contract.

    JSONB shape:
      {"name": "Boonen, Jan", "role": "bestuurder", "role_canonical": "director",
       "since": "2024-03-27", "is_legal_person": false, "linked_kbo": null}
    """
    value: dict[str, Any] = {
        "name": row.name,
        "role": row.role.lower(),
        "role_canonical": row.role_canonical,
        "since": row.since.isoformat() if row.since is not None else None,
        "is_legal_person": row.is_legal_person,
        "linked_kbo": row.linked_kbo,
    }
    return Observation(
        kbo_number=kbo_number,
        field="function_holder",
        value=value,
        raw_value=row.raw_html,
        source="kbopub",
        source_url=source_url,
        observed_at=snapshot_at,
        confidence=_CONFIDENCE,
        run_id=run_id,
    )
