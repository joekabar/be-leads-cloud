-- Migration 006: optimize KBO staging tables for fast bulk load.
--
-- 1) UNLOGGED: staging data is transient and idempotently re-stageable, so it does
--    not need crash-safety. Skipping WAL gives a large COPY speedup. Trade-off: the
--    tables are TRUNCATEd if Postgres restarts uncleanly — just re-run be-leads-kbo-stage.
--
-- 2) Drop raw_row: it stored a full JSON copy of every row (a json.dumps per row, ~14M
--    times per full ZIP) for "schema-drift forward compatibility". It duplicated the typed
--    columns and roughly doubled COPY volume, while the drift detector that justified it
--    never actually fired. Drift is now detected by comparing CSV headers at stage time
--    (logged as kbo_schema_drift_detected); if a new column ever appears, re-stage from the
--    archived ZIP — we keep KBO_zip/KboOpenData_*.zip anyway.

ALTER TABLE kbo_stage_enterprise   SET UNLOGGED;
ALTER TABLE kbo_stage_address      SET UNLOGGED;
ALTER TABLE kbo_stage_denomination SET UNLOGGED;
ALTER TABLE kbo_stage_contact      SET UNLOGGED;
ALTER TABLE kbo_stage_activity     SET UNLOGGED;

ALTER TABLE kbo_stage_enterprise   DROP COLUMN IF EXISTS raw_row;
ALTER TABLE kbo_stage_address      DROP COLUMN IF EXISTS raw_row;
ALTER TABLE kbo_stage_denomination DROP COLUMN IF EXISTS raw_row;
ALTER TABLE kbo_stage_contact      DROP COLUMN IF EXISTS raw_row;
ALTER TABLE kbo_stage_activity     DROP COLUMN IF EXISTS raw_row;
