from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from scraper.db.models import Job

if TYPE_CHECKING:
    import asyncpg


class JobsRepo:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def enqueue(
        self,
        type: str,
        payload: dict[str, Any] | None = None,
        *,
        priority: int = 5,
        parent_job_id: int | None = None,
    ) -> int:
        """Insert a pending job and return its id."""
        row = await self._pool.fetchrow(
            """
            INSERT INTO jobs (type, payload, priority, parent_job_id)
            VALUES ($1, $2, $3, $4)
            RETURNING id
            """,
            type,
            payload or {},
            priority,
            parent_job_id,
        )
        if row is None:
            raise RuntimeError("INSERT INTO jobs returned no row")
        return int(row["id"])

    async def pop_pending(self) -> Job | None:
        """Atomically claim one pending job (SKIP LOCKED). Returns None if queue is empty."""
        row = await self._pool.fetchrow(
            """
            WITH next AS (
                SELECT id FROM jobs
                WHERE status = 'pending' AND next_retry_at <= NOW()
                ORDER BY priority DESC, next_retry_at, id
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            )
            UPDATE jobs
            SET status = 'running',
                attempts = attempts + 1,
                updated_at = NOW()
            FROM next
            WHERE jobs.id = next.id
            RETURNING jobs.id, jobs.type, jobs.payload, jobs.status, jobs.attempts,
                      jobs.priority, jobs.last_error, jobs.parent_job_id
            """
        )
        if row is None:
            return None
        return _row_to_job(row)

    async def mark_done(self, job_id: int) -> None:
        await self._pool.execute(
            "UPDATE jobs SET status = 'done', updated_at = $2 WHERE id = $1",
            job_id,
            datetime.now(tz=UTC),
        )

    async def mark_failed(self, job_id: int, error: str, next_retry_at: datetime) -> None:
        await self._pool.execute(
            """
            UPDATE jobs
            SET status = 'pending', last_error = $2, next_retry_at = $3, updated_at = $4
            WHERE id = $1
            """,
            job_id,
            error,
            next_retry_at,
            datetime.now(tz=UTC),
        )

    async def mark_dead(self, job_id: int, error: str) -> None:
        await self._pool.execute(
            """
            UPDATE jobs
            SET status = 'dead', last_error = $2, updated_at = $3
            WHERE id = $1
            """,
            job_id,
            error,
            datetime.now(tz=UTC),
        )


def _row_to_job(row: asyncpg.Record) -> Job:
    return Job(
        id=row["id"],
        type=row["type"],
        payload=dict(row["payload"]),
        status=row["status"],
        attempts=row["attempts"],
        priority=row["priority"],
        last_error=row["last_error"],
        parent_job_id=row["parent_job_id"],
    )
