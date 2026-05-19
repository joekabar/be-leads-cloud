-- Migration 003: prospect_scores table for Saive commercial prospect scoring.
-- Plain table (not a matview) — HV prior lookup is Python-only, not expressible as SQL.

CREATE TABLE IF NOT EXISTS prospect_scores (
    kbo_number        CHAR(10)      PRIMARY KEY,
    hv_probability    NUMERIC(7,6)  NOT NULL DEFAULT 0,
    business_activity NUMERIC(7,6)  NOT NULL DEFAULT 0,
    contact_quality   NUMERIC(7,6)  NOT NULL DEFAULT 0,
    growth_signal     NUMERIC(7,6)  NOT NULL DEFAULT 0,
    overall_prospect  NUMERIC(7,6)  NOT NULL DEFAULT 0,
    computed_at       TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);
