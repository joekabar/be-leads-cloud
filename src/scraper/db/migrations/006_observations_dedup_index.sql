-- Migration 006: covering index for skip_recent_hours queries on the observations table.
-- The batch pipeline checks whether a source already scraped a KBO recently
-- (skip_recent_hours > 0). At scale (~10M rows after a year of monthly runs)
-- this query needs a fast path. The index covers (source, kbo_number, observed_at DESC).
-- No UNIQUE constraint: observations remains append-only by design.

CREATE INDEX IF NOT EXISTS ix_observations_source_kbo_recent
    ON observations (source, kbo_number, observed_at DESC);
