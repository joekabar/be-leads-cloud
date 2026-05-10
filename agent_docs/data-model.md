# Data Model

> TODO: Full DDL and migration ship in prompt 3. This document captures the design intent.

## Core tables

### `companies` — materialised current-best

Never directly `UPDATE`d. Rebuilt via `REFRESH MATERIALISED VIEW CONCURRENTLY` after each
pipeline run.

| column         | type    | notes                                      |
|----------------|---------|--------------------------------------------|
| kbo_number     | TEXT PK | Belgian enterprise number (BE 0xxx.xxx.xxx)|
| name           | TEXT    | current best name                          |
| legal_form     | TEXT    | SA, SRL, etc.                              |
| status         | TEXT    | active / stopped / bankrupt                |
| nace_codes     | TEXT[]  | primary + secondary NACE-BEL codes         |
| address_street | TEXT    |                                            |
| address_zip    | TEXT    |                                            |
| address_city   | TEXT    |                                            |
| phone          | TEXT    | E.164 normalised via phonenumbers          |
| email          | TEXT    |                                            |
| website        | TEXT    |                                            |
| updated_at     | TIMESTAMPTZ | last view refresh                      |

### `observations` — append-only provenance log

Every scraped fact lands here as a single row. No deletes, no updates.

| column      | type        | notes                                               |
|-------------|-------------|-----------------------------------------------------|
| id          | BIGSERIAL   | surrogate PK                                        |
| kbo_number  | TEXT        | FK → companies                                      |
| field       | TEXT        | e.g. "name", "phone", "address_street", "nace_code" |
| value       | JSONB       | scalar or structured value                          |
| source      | TEXT        | e.g. "kbo_open_data", "goudengids", "nbb_cbso"      |
| observed_at | TIMESTAMPTZ | when the scraper fetched this fact                  |
| confidence  | NUMERIC     | 0.0–1.0 score from the scoring module               |
| run_id      | UUID        | ties back to a pipeline_runs record                 |
| raw_ref     | TEXT        | URL, file path, or object key of the raw source     |

### `pipeline_runs` — job audit

| column     | type        | notes                          |
|------------|-------------|--------------------------------|
| run_id     | UUID PK     | generated at pipeline start    |
| source     | TEXT        | which source was run           |
| started_at | TIMESTAMPTZ |                                |
| finished_at| TIMESTAMPTZ | NULL while running             |
| status     | TEXT        | running / ok / failed          |
| stats      | JSONB       | counts: fetched, parsed, saved |

### `jobs` — worker queue (SELECT ... FOR UPDATE SKIP LOCKED)

| column      | type        | notes                                   |
|-------------|-------------|-----------------------------------------|
| id          | BIGSERIAL   | surrogate PK                            |
| kind        | TEXT        | "fetch_company", "enrich_website", etc. |
| payload     | JSONB       | job-specific parameters                 |
| status      | TEXT        | pending / running / done / failed       |
| priority    | INT         | lower = higher priority                 |
| created_at  | TIMESTAMPTZ |                                         |
| claimed_at  | TIMESTAMPTZ | set when a worker pops the job          |
| run_id      | UUID        | FK → pipeline_runs                      |

## Materialised view strategy

`companies_current` selects the highest-confidence observation per `(kbo_number, field)`:

```sql
SELECT DISTINCT ON (kbo_number, field)
    kbo_number, field, value, source, observed_at, confidence
FROM observations
ORDER BY kbo_number, field, confidence DESC, observed_at DESC;
```

Rebuilt with `REFRESH MATERIALISED VIEW CONCURRENTLY companies_current` after each pipeline run.
Concurrent refresh requires a unique index on `(kbo_number, field)`.

## Worker queue semantics

```sql
WITH next AS (
    SELECT id FROM jobs
    WHERE status = 'pending'
    ORDER BY priority, id
    LIMIT 1
    FOR UPDATE SKIP LOCKED
)
UPDATE jobs SET status = 'running', claimed_at = NOW()
FROM next
WHERE jobs.id = next.id
RETURNING jobs.*;
```

This gives correct at-most-once delivery under concurrent workers without a separate broker.
