from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from scraper.db.models import Run

if TYPE_CHECKING:
    import asyncpg


class RunsRepo:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def start_run(
        self,
        *,
        source: str | None = None,
        sector_slug: str | None = None,
        city_slug: str | None = None,
        notes: str | None = None,
    ) -> UUID:
        """Insert a new run_log row and return its run_id."""
        run_id = uuid4()
        await self._pool.execute(
            """
            INSERT INTO run_log (run_id, started_at, source, sector_slug, city_slug, notes)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            run_id,
            datetime.now(tz=UTC),
            source,
            sector_slug,
            city_slug,
            notes,
        )
        return run_id

    async def finish_run(
        self,
        run_id: UUID,
        *,
        jobs_done: int = 0,
        jobs_failed: int = 0,
    ) -> None:
        """Mark a run as finished and record job counts."""
        await self._pool.execute(
            """
            UPDATE run_log
            SET ended_at = $2, jobs_done = $3, jobs_failed = $4
            WHERE run_id = $1
            """,
            run_id,
            datetime.now(tz=UTC),
            jobs_done,
            jobs_failed,
        )

    async def get(self, run_id: UUID) -> Run | None:
        """Fetch a single run by id."""
        row = await self._pool.fetchrow(
            """
            SELECT run_id, started_at, ended_at, sector_slug, city_slug,
                   source, notes, jobs_done, jobs_failed
            FROM run_log WHERE run_id = $1
            """,
            run_id,
        )
        if row is None:
            return None
        return Run(
            run_id=row["run_id"],
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            sector_slug=row["sector_slug"],
            city_slug=row["city_slug"],
            source=row["source"],
            notes=row["notes"],
            jobs_done=row["jobs_done"],
            jobs_failed=row["jobs_failed"],
        )
