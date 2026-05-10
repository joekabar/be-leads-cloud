from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator


class Observation(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int | None = None
    kbo_number: str
    field: str
    value: dict[str, Any]
    raw_value: str | None = None
    source: str
    source_url: str | None = None
    observed_at: datetime | None = None
    confidence: float
    run_id: UUID

    @field_validator("kbo_number")
    @classmethod
    def _validate_kbo(cls, v: str) -> str:
        from stdnum.be import vat

        try:
            return str(vat.validate(v))
        except Exception as exc:
            raise ValueError(f"Invalid KBO number: {v!r}") from exc

    @field_validator("field")
    @classmethod
    def _validate_field(cls, v: str) -> str:
        from scraper.db.fields import validate_field
        from scraper.lib.errors import InvalidFieldError

        try:
            validate_field(v)
        except InvalidFieldError as exc:
            raise ValueError(str(exc)) from exc
        return v

    @field_validator("source")
    @classmethod
    def _validate_source(cls, v: str) -> str:
        from scraper.db.sources import validate_source
        from scraper.lib.errors import InvalidSourceError

        try:
            validate_source(v)
        except InvalidSourceError as exc:
            raise ValueError(str(exc)) from exc
        return v


class Run(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: UUID
    started_at: datetime | None = None
    ended_at: datetime | None = None
    sector_slug: str | None = None
    city_slug: str | None = None
    source: str | None = None
    notes: str | None = None
    jobs_done: int = 0
    jobs_failed: int = 0


class Job(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int | None = None
    type: str
    payload: dict[str, Any] = {}
    status: str = "pending"
    attempts: int = 0
    priority: int = 5
    last_error: str | None = None
    parent_job_id: int | None = None
