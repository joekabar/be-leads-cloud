-- Migration 001: initial schema (schema_version, run_log, observations, jobs).
-- companies_current materialised view is created in migration 002.

CREATE TABLE IF NOT EXISTS schema_version (
    version    INTEGER     PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS run_log (
    run_id      UUID         PRIMARY KEY,
    started_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    ended_at    TIMESTAMPTZ,
    sector_slug TEXT,
    city_slug   TEXT,
    source      TEXT,
    notes       TEXT,
    jobs_done   INTEGER      NOT NULL DEFAULT 0,
    jobs_failed INTEGER      NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_run_log_started_at ON run_log (started_at DESC);

CREATE TABLE IF NOT EXISTS observations (
    id           BIGSERIAL    PRIMARY KEY,
    kbo_number   CHAR(10)     NOT NULL,
    field        TEXT         NOT NULL,
    value        JSONB        NOT NULL,
    raw_value    TEXT,
    source       TEXT         NOT NULL,
    source_url   TEXT,
    observed_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    confidence   NUMERIC(3,2) NOT NULL DEFAULT 0.50,
    run_id       UUID         NOT NULL REFERENCES run_log(run_id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_obs_kbo_field_observed
    ON observations (kbo_number, field, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_obs_source_observed
    ON observations (source, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_obs_value_gin
    ON observations USING gin (value);
CREATE INDEX IF NOT EXISTS idx_obs_run_id
    ON observations (run_id);

CREATE TABLE IF NOT EXISTS jobs (
    id              BIGSERIAL   PRIMARY KEY,
    type            TEXT        NOT NULL,
    payload         JSONB       NOT NULL DEFAULT '{}'::jsonb,
    status          TEXT        NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','running','done','failed','dead')),
    attempts        INTEGER     NOT NULL DEFAULT 0,
    priority        INTEGER     NOT NULL DEFAULT 5,
    next_retry_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_error      TEXT,
    parent_job_id   BIGINT      REFERENCES jobs(id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_jobs_pending
    ON jobs (priority DESC, next_retry_at, id)
    WHERE status = 'pending';
CREATE UNIQUE INDEX IF NOT EXISTS uniq_jobs_active_dedup
    ON jobs (type, (payload->>'dedup_key'))
    WHERE status IN ('pending','running') AND payload ? 'dedup_key';
