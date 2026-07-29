-- Migration 008: remember which placeholder KBOs consolidation has already processed.
--
-- Consolidation previously re-matched *every* placeholder in the database on every run
-- and re-emitted the observations of every match again. Two consequences, both growing
-- with each goudengids discovery:
--
--   1) Wall time. 11,065 placeholders, most falling through to the name-only pass at
--      ~0.6 s each against 1.9M real names — ~40 min per run, single-threaded.
--   2) Duplicate rows. Two consecutive runs each logged
--      "matches=2797, observations_re_emitted=43466" — the same 2,797 placeholders,
--      the same ~43k observations, inserted again. observations is append-only, so
--      nothing overwrote them.
--
-- This table makes the pass incremental. A placeholder is processed once per KBO
-- snapshot: matched rows keep real_kbo, unmatched rows keep NULL. Matched placeholders
-- are never reprocessed (their observations are already re-emitted); unmatched ones are
-- retried when a newer snapshot is staged, since new real KBOs may now match.
--
-- No FK to observations: placeholder and real KBOs are values there, not keys.

CREATE TABLE IF NOT EXISTS consolidation_state (
    placeholder_kbo CHAR(10)    PRIMARY KEY,
    real_kbo        CHAR(10),   -- NULL: processed, no match found
    score           NUMERIC(5,2),
    matched_on      TEXT,       -- name+postal | name+city | name_only
    snapshot_date   DATE,       -- KBO snapshot the attempt was made against
    processed_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Retry scan: "unmatched, and older than the current snapshot".
CREATE INDEX IF NOT EXISTS ix_consolidation_state_retry
    ON consolidation_state (snapshot_date)
    WHERE real_kbo IS NULL;

-- Reverse lookup: which placeholders folded into a given real KBO.
CREATE INDEX IF NOT EXISTS ix_consolidation_state_real
    ON consolidation_state (real_kbo)
    WHERE real_kbo IS NOT NULL;
