-- Migration 005: pipeline_progress telemetry table.
-- Mutable (not append-only) — one upserted row per run_id tracks live phase progress.
-- Used by the Streamlit UI's "Live progress" auto-refresh panel.

CREATE TABLE IF NOT EXISTS pipeline_progress (
    run_id      UUID         PRIMARY KEY REFERENCES run_log(run_id) ON DELETE CASCADE,
    phase       TEXT         NOT NULL DEFAULT '',
    stage       TEXT         NOT NULL DEFAULT '',
    current_val INTEGER,
    total_val   INTEGER,
    message     TEXT,
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
