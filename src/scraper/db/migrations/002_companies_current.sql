-- Migration 002: companies_current materialised view + refresh function.

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

CREATE OR REPLACE FUNCTION refresh_companies_current()
RETURNS void AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY companies_current;
END;
$$ LANGUAGE plpgsql;
