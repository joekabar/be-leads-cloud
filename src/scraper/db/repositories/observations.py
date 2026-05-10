# This repository is intentionally append-only. No UPDATE or DELETE methods.
# See .claude/skills/provenance-schema/SKILL.md for the cardinal rule.
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from scraper.db.models import Observation

if TYPE_CHECKING:
    import asyncpg

_INSERT_SQL = """
    INSERT INTO observations
        (kbo_number, field, value, raw_value, source, source_url,
         observed_at, confidence, run_id)
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
    RETURNING id
"""


class ObservationsRepo:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def insert(self, obs: Observation) -> int:
        """Insert one observation and return its new id."""
        row = await self._pool.fetchrow(
            _INSERT_SQL,
            obs.kbo_number,
            obs.field,
            obs.value,
            obs.raw_value,
            obs.source,
            obs.source_url,
            obs.observed_at or datetime.now(tz=UTC),
            obs.confidence,
            obs.run_id,
        )
        if row is None:
            raise RuntimeError("INSERT INTO observations returned no row")
        return int(row["id"])

    async def insert_many(self, obs_list: list[Observation]) -> list[int]:
        """Bulk-insert observations in a single transaction. Returns new ids in order."""
        if not obs_list:
            return []
        now = datetime.now(tz=UTC)
        ids: list[int] = []
        async with self._pool.acquire() as conn, conn.transaction():
            for obs in obs_list:
                row = await conn.fetchrow(
                    _INSERT_SQL,
                    obs.kbo_number,
                    obs.field,
                    obs.value,
                    obs.raw_value,
                    obs.source,
                    obs.source_url,
                    obs.observed_at or now,
                    obs.confidence,
                    obs.run_id,
                )
                if row is None:
                    raise RuntimeError("INSERT INTO observations returned no row")
                ids.append(int(row["id"]))
        return ids

    async def current_best(self, kbo_number: str, field: str) -> Observation | None:
        """Return the highest-confidence (then newest) observation for (kbo, field)."""
        row = await self._pool.fetchrow(
            """
            SELECT id, kbo_number, field, value, raw_value, source, source_url,
                   observed_at, confidence, run_id
            FROM observations
            WHERE kbo_number = $1 AND field = $2
            ORDER BY confidence DESC, observed_at DESC
            LIMIT 1
            """,
            kbo_number,
            field,
        )
        if row is None:
            return None
        return _row_to_obs(row)

    async def current_all(self, kbo_number: str) -> list[Observation]:
        """Return current-best observation for every field of one company."""
        rows = await self._pool.fetch(
            """
            SELECT DISTINCT ON (field)
                   id, kbo_number, field, value, raw_value, source, source_url,
                   observed_at, confidence, run_id
            FROM observations
            WHERE kbo_number = $1
            ORDER BY field, confidence DESC, observed_at DESC
            """,
            kbo_number,
        )
        return [_row_to_obs(r) for r in rows]

    async def history(self, kbo_number: str, field: str) -> list[Observation]:
        """All observations for (kbo, field), newest first."""
        rows = await self._pool.fetch(
            """
            SELECT id, kbo_number, field, value, raw_value, source, source_url,
                   observed_at, confidence, run_id
            FROM observations
            WHERE kbo_number = $1 AND field = $2
            ORDER BY observed_at DESC
            """,
            kbo_number,
            field,
        )
        return [_row_to_obs(r) for r in rows]


def _row_to_obs(row: asyncpg.Record) -> Observation:
    return Observation(
        id=row["id"],
        kbo_number=row["kbo_number"],
        field=row["field"],
        value=dict(row["value"]),
        raw_value=row["raw_value"],
        source=row["source"],
        source_url=row["source_url"],
        observed_at=row["observed_at"],
        confidence=float(row["confidence"]),
        run_id=row["run_id"],
    )
