"""Live progress reporting for long-running pipeline phases.

ProgressReporter upserts a single row per run_id into pipeline_progress.
Both the CLI (via structlog) and the Streamlit UI (via pipeline_progress) consume this.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from uuid import UUID

    import asyncpg

logger = structlog.get_logger()


@dataclass
class ProgressReporter:
    pool: asyncpg.Pool
    run_id: UUID

    async def report(
        self,
        phase: str,
        stage: str,
        *,
        current: int | None = None,
        total: int | None = None,
        message: str | None = None,
    ) -> None:
        """Upsert progress into pipeline_progress and emit a structlog event."""
        try:
            await self.pool.execute(
                """
                INSERT INTO pipeline_progress
                    (run_id, phase, stage, current_val, total_val, message, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, NOW())
                ON CONFLICT (run_id) DO UPDATE SET
                    phase       = EXCLUDED.phase,
                    stage       = EXCLUDED.stage,
                    current_val = EXCLUDED.current_val,
                    total_val   = EXCLUDED.total_val,
                    message     = EXCLUDED.message,
                    updated_at  = EXCLUDED.updated_at
                """,
                self.run_id,
                phase,
                stage,
                current,
                total,
                message,
            )
        except Exception as exc:
            logger.warning("progress_report_failed", error=str(exc))

        logger.info(
            "pipeline_progress",
            run_id=str(self.run_id),
            phase=phase,
            stage=stage,
            current=current,
            total=total,
            message=message,
        )
