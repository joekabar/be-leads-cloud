"""DB queries for the KBO Data Management page."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from datetime import date

    import asyncpg


async def list_staged_snapshots(
    pool: asyncpg.Pool,
) -> list[dict[str, Any]]:
    """Return [{snapshot_date, enterprise_count}] sorted most-recent first."""
    rows = await pool.fetch(
        """
        SELECT snapshot_date, COUNT(*) AS n
        FROM kbo_stage_enterprise
        GROUP BY snapshot_date
        ORDER BY snapshot_date DESC
        """
    )
    return [{"snapshot_date": r["snapshot_date"], "enterprise_count": int(r["n"])} for r in rows]


async def count_new_kbos_between(
    pool: asyncpg.Pool,
    prior_date: date,
    latest_date: date,
) -> int:
    """Count entity numbers in latest_date snapshot that are absent from prior_date snapshot."""
    n = await pool.fetchval(
        """
        SELECT COUNT(*) FROM (
            SELECT entity_number FROM kbo_stage_enterprise WHERE snapshot_date = $1
            EXCEPT
            SELECT entity_number FROM kbo_stage_enterprise WHERE snapshot_date = $2
        ) sub
        """,
        latest_date,
        prior_date,
    )
    return int(n or 0)


async def count_new_kbos_since(
    pool: asyncpg.Pool,
    since_date: date,
) -> int:
    """Count entity numbers first appearing in any snapshot after since_date."""
    n = await pool.fetchval(
        """
        SELECT COUNT(*) FROM (
            SELECT DISTINCT entity_number FROM kbo_stage_enterprise WHERE snapshot_date > $1
            EXCEPT
            SELECT DISTINCT entity_number FROM kbo_stage_enterprise WHERE snapshot_date <= $1
        ) sub
        """,
        since_date,
    )
    return int(n or 0)


async def fetch_new_kbo_details_between(
    pool: asyncpg.Pool,
    prior_date: date,
    latest_date: date,
    *,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    """Top N new entities (by prospect_score DESC) for between-snapshots diff.

    Joins staging tables for name/city/NACE and prospect_scores for ranking.
    """
    rows = await pool.fetch(
        """
        SELECT *
        FROM (
            SELECT DISTINCT ON (e.entity_number)
                e.entity_number,
                e.start_date,
                a.zipcode,
                a.municipality_nl                        AS city,
                d.denomination                           AS name,
                act.nace_code,
                COALESCE(ps.overall_prospect, 0.0)       AS overall_prospect,
                COALESCE(ps.hv_probability,   0.0)       AS hv_probability
            FROM kbo_stage_enterprise e
            JOIN (
                SELECT entity_number
                FROM kbo_stage_enterprise WHERE snapshot_date = $1
                EXCEPT
                SELECT entity_number
                FROM kbo_stage_enterprise WHERE snapshot_date = $2
            ) new_ents ON new_ents.entity_number = e.entity_number
            LEFT JOIN kbo_stage_address a
                ON  a.entity_number = e.entity_number
                AND a.snapshot_date = e.snapshot_date
            LEFT JOIN LATERAL (
                SELECT denomination
                FROM kbo_stage_denomination
                WHERE entity_number = e.entity_number
                  AND snapshot_date  = e.snapshot_date
                LIMIT 1
            ) d ON TRUE
            LEFT JOIN LATERAL (
                SELECT nace_code
                FROM kbo_stage_activity
                WHERE entity_number = e.entity_number
                  AND snapshot_date  = e.snapshot_date
                LIMIT 1
            ) act ON TRUE
            LEFT JOIN prospect_scores ps ON ps.kbo_number::text = e.entity_number
            WHERE e.snapshot_date = $1
            ORDER BY e.entity_number
        ) sub
        ORDER BY overall_prospect DESC NULLS LAST
        LIMIT $3
        """,
        latest_date,
        prior_date,
        limit,
    )
    return [dict(r) for r in rows]


async def fetch_new_kbo_details_since(
    pool: asyncpg.Pool,
    since_date: date,
    *,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    """Top N entities first appearing after since_date, joined with most-recent staging data."""
    latest = await pool.fetchval(
        "SELECT MAX(snapshot_date) FROM kbo_stage_enterprise WHERE snapshot_date > $1",
        since_date,
    )
    if latest is None:
        return []

    rows = await pool.fetch(
        """
        SELECT *
        FROM (
            SELECT DISTINCT ON (e.entity_number)
                e.entity_number,
                e.start_date,
                a.zipcode,
                a.municipality_nl                        AS city,
                d.denomination                           AS name,
                act.nace_code,
                COALESCE(ps.overall_prospect, 0.0)       AS overall_prospect,
                COALESCE(ps.hv_probability,   0.0)       AS hv_probability
            FROM kbo_stage_enterprise e
            JOIN (
                SELECT DISTINCT entity_number
                FROM kbo_stage_enterprise WHERE snapshot_date > $1
                EXCEPT
                SELECT DISTINCT entity_number
                FROM kbo_stage_enterprise WHERE snapshot_date <= $1
            ) new_ents ON new_ents.entity_number = e.entity_number
            LEFT JOIN kbo_stage_address a
                ON  a.entity_number = e.entity_number
                AND a.snapshot_date = e.snapshot_date
            LEFT JOIN LATERAL (
                SELECT denomination
                FROM kbo_stage_denomination
                WHERE entity_number = e.entity_number
                  AND snapshot_date  = e.snapshot_date
                LIMIT 1
            ) d ON TRUE
            LEFT JOIN LATERAL (
                SELECT nace_code
                FROM kbo_stage_activity
                WHERE entity_number = e.entity_number
                  AND snapshot_date  = e.snapshot_date
                LIMIT 1
            ) act ON TRUE
            LEFT JOIN prospect_scores ps ON ps.kbo_number::text = e.entity_number
            WHERE e.snapshot_date = $2
            ORDER BY e.entity_number
        ) sub
        ORDER BY overall_prospect DESC NULLS LAST
        LIMIT $3
        """,
        since_date,
        latest,
        limit,
    )
    return [dict(r) for r in rows]


async def get_latest_progress(
    pool: asyncpg.Pool,
) -> dict[str, Any] | None:
    """Most recent pipeline_progress row within the last 30 minutes."""
    row = await pool.fetchrow(
        """
        SELECT pp.run_id, pp.phase, pp.stage,
               pp.current_val, pp.total_val, pp.message, pp.updated_at,
               rl.source, rl.started_at
        FROM pipeline_progress pp
        JOIN run_log rl ON rl.run_id = pp.run_id
        WHERE pp.updated_at > NOW() - INTERVAL '30 minutes'
        ORDER BY pp.updated_at DESC
        LIMIT 1
        """
    )
    return dict(row) if row else None
