-- Migration 004: KBO Open Data staging tables.
-- Stage the full ZIP once; batch pipeline reads from these tables instead of re-parsing the ZIP.
-- Each table has a BIGSERIAL id so COPY works without conflict handling.
-- raw_row stores the full CSV row as JSONB for schema-drift forward compatibility.

CREATE TABLE IF NOT EXISTS kbo_stage_enterprise (
    id                   BIGSERIAL    PRIMARY KEY,
    entity_number        TEXT         NOT NULL,
    snapshot_date        DATE         NOT NULL,
    status               TEXT,
    juridical_situation  TEXT,
    type_of_enterprise   TEXT,
    juridical_form       TEXT,
    juridical_form_cac   TEXT,
    start_date           DATE,
    raw_row              JSONB        NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_kbo_stage_enterprise_snapshot
    ON kbo_stage_enterprise (snapshot_date);
CREATE INDEX IF NOT EXISTS idx_kbo_stage_enterprise_entity
    ON kbo_stage_enterprise (entity_number, snapshot_date);

CREATE TABLE IF NOT EXISTS kbo_stage_address (
    id                BIGSERIAL    PRIMARY KEY,
    entity_number     TEXT         NOT NULL,
    snapshot_date     DATE         NOT NULL,
    type_of_address   TEXT,
    zipcode           TEXT,
    municipality_nl   TEXT,
    municipality_fr   TEXT,
    street_nl         TEXT,
    street_fr         TEXT,
    house_number      TEXT,
    box               TEXT,
    raw_row           JSONB        NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_kbo_stage_address_snapshot
    ON kbo_stage_address (snapshot_date);
CREATE INDEX IF NOT EXISTS idx_kbo_stage_address_entity
    ON kbo_stage_address (entity_number, snapshot_date);
CREATE INDEX IF NOT EXISTS idx_kbo_stage_address_muni_nl
    ON kbo_stage_address (snapshot_date, lower(municipality_nl));
CREATE INDEX IF NOT EXISTS idx_kbo_stage_address_muni_fr
    ON kbo_stage_address (snapshot_date, lower(municipality_fr));

CREATE TABLE IF NOT EXISTS kbo_stage_denomination (
    id                    BIGSERIAL    PRIMARY KEY,
    entity_number         TEXT         NOT NULL,
    snapshot_date         DATE         NOT NULL,
    language              TEXT,
    type_of_denomination  TEXT,
    denomination          TEXT,
    raw_row               JSONB        NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_kbo_stage_denomination_snapshot
    ON kbo_stage_denomination (snapshot_date);
CREATE INDEX IF NOT EXISTS idx_kbo_stage_denomination_entity
    ON kbo_stage_denomination (entity_number, snapshot_date);

CREATE TABLE IF NOT EXISTS kbo_stage_contact (
    id               BIGSERIAL    PRIMARY KEY,
    entity_number    TEXT         NOT NULL,
    snapshot_date    DATE         NOT NULL,
    contact_type     TEXT,
    value            TEXT,
    raw_row          JSONB        NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_kbo_stage_contact_snapshot
    ON kbo_stage_contact (snapshot_date);
CREATE INDEX IF NOT EXISTS idx_kbo_stage_contact_entity
    ON kbo_stage_contact (entity_number, snapshot_date);

CREATE TABLE IF NOT EXISTS kbo_stage_activity (
    id               BIGSERIAL    PRIMARY KEY,
    entity_number    TEXT         NOT NULL,
    snapshot_date    DATE         NOT NULL,
    activity_group   TEXT,
    nace_version     TEXT,
    nace_code        TEXT,
    classification   TEXT,
    raw_row          JSONB        NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_kbo_stage_activity_snapshot
    ON kbo_stage_activity (snapshot_date);
CREATE INDEX IF NOT EXISTS idx_kbo_stage_activity_entity
    ON kbo_stage_activity (entity_number, snapshot_date);
CREATE INDEX IF NOT EXISTS idx_kbo_stage_activity_nace
    ON kbo_stage_activity (snapshot_date, nace_code text_pattern_ops);
