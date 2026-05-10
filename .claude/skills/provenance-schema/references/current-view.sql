-- companies_current: materialised view, one row per (kbo_number, field) with highest-confidence,
-- newest-first tie-breaking.

CREATE MATERIALIZED VIEW IF NOT EXISTS companies_current AS
SELECT DISTINCT ON (kbo_number, field)
       kbo_number,
       field,
       value,
       source,
       observed_at,
       confidence
FROM observations
ORDER BY kbo_number, field, confidence DESC, observed_at DESC;

CREATE UNIQUE INDEX IF NOT EXISTS uniq_companies_current
    ON companies_current (kbo_number, field);

-- Concurrent refresh function for the pipeline to call.
CREATE OR REPLACE FUNCTION refresh_companies_current()
RETURNS void AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY companies_current;
END;
$$ LANGUAGE plpgsql;


-- Ad-hoc real-time read pattern (no matview refresh needed):
-- Get current-best for ALL fields of one company:
--
-- SELECT DISTINCT ON (field)
--        field, value, source, confidence, observed_at
-- FROM observations
-- WHERE kbo_number = $1
-- ORDER BY field, confidence DESC, observed_at DESC;
--
-- Get current-best for a SINGLE field:
--
-- SELECT DISTINCT ON (field)
--        field, value, source, confidence, observed_at
-- FROM observations
-- WHERE kbo_number = $1 AND field = $2
-- ORDER BY field, confidence DESC, observed_at DESC;
