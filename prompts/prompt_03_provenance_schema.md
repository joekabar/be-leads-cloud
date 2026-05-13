# Bootstrap Prompt 3 — Skill: `provenance-schema` + DB migrations

> **How to use:** in the `be-leads/` directory, Git Bash terminal in VS Code, run `claude` (fresh session). Make sure Postgres is up first: `docker compose up -d pg`. Paste everything below `=== PROMPT ===`.

---

=== PROMPT ===

You are adding the data-model foundation: the `provenance-schema` skill plus the asyncpg pool, the migrations runner, the canonical schema (observations + companies + jobs + run_log), Pydantic row models, repository classes, and full tests against a real Postgres in docker compose. After this prompt, every source can write observations and read current-best.

## Read first

- `CLAUDE.md`
- `agent_docs/architecture.md`
- `agent_docs/data-model.md` (currently a placeholder — you will replace its body)
- `docs/decisions/0001-postgres-only.md`
- `.claude/skills/polite-scraping/SKILL.md` (to mirror its style)
- `.env.example`
- The three memory files in `~/.claude/projects/C--Users-Oxfam-Documents-Saivy-Programs-be-leads/memory/`

## Plan first

Create `.claude/plans/2026-05-10-provenance-schema.md` from the template with:
- Status: `approved`
- Goal: "Ship the `provenance-schema` skill and the DB layer (asyncpg pool, migrations, observations + companies + jobs + run_log + schema_version, repositories, Pydantic row models) with full integration tests against a real Postgres in docker compose."
- Scope in: skill + DB module + migrations + repositories + Pydantic models + tests; updates to `agent_docs/data-model.md` and `agent_docs/runbook.md`.
- Out of scope: any specific source ingestion; the materialised-view rebuild scheduler (deferred to pipeline prompt); any pruning / retention logic; Streamlit views.
- Acceptance: skill has valid frontmatter; migrations apply idempotently against the docker compose Postgres; observations table is append-only (a regression test asserts there is NO trigger or app code path that issues UPDATE on observations); the `companies_current` materialised view returns the highest-confidence-then-newest observation per (kbo_number, field); coverage on `src/scraper/db/` ≥ 90%; mypy --strict clean.

## Pre-flight

Before doing any work, verify Postgres is reachable:

```bash
docker compose up -d pg
docker compose ps
```

If `pg` is not healthy, stop and tell the user — do not continue. Set `DATABASE_URL=postgresql://leads:leads@localhost:5432/leads` for the session (or read from `.env` if `python-dotenv` is wired). Add `python-dotenv` loading to `src/scraper/lib/config.py` in this prompt (see below).

## What to produce

### A. The skill: `.claude/skills/provenance-schema/`

Layout:
```
.claude/skills/provenance-schema/
├── SKILL.md
├── references/
│   ├── schema.sql
│   ├── current-view.sql
│   └── confidence.md
└── scripts/
    └── verify_no_updates.sh
```

**`SKILL.md` frontmatter:**

```yaml
---
name: provenance-schema
description: Apply the project's append-only multi-source provenance schema. Every field value carries source, observed_at, confidence, raw_value, and run_id; canonical fact rows are NEVER UPDATEd — new values become new observations. Use whenever the user adds a data field, modifies the data model, writes an UPDATE statement, joins tables, or computes a "current best" value. Always use this skill instead of writing UPDATE statements on companies or observations — there must never be UPDATEs on canonical fact rows.
allowed-tools: Read, Edit, Bash(uv run python:*), Bash(uv run pytest:*), Bash(psql:*), mcp__postgres__query, mcp__postgres__list_tables, mcp__postgres__describe_table
---
```

**`SKILL.md` body** — eight sections, each ≤15 lines:

1. **Cardinal rule.** No UPDATE on `observations` or `companies_current`. Only INSERT into `observations`. The `companies_current` materialised view is rebuilt by `src/scraper/pipeline/consolidate.py` (added in a later prompt) — it's read-only at the application level. If you find yourself writing UPDATE on either, stop and write an INSERT into observations instead.
2. **Schema sketch.** Point to `references/schema.sql`.
3. **Current-best read pattern.** SELECT from `companies_current` (materialised). For ad-hoc real-time reads, use the `LATERAL` query in `references/current-view.sql`.
4. **Confidence scoring.** Per-source priors table in `references/confidence.md`. Recency decay: `confidence * (0.99 ** days_since_observation)` clamped to `[0.30, 1.00]`. Cross-source consensus boost: `min(1.0, base * 1.1)` per matching observation from a *different* source for the same `(kbo_number, field, value)`.
5. **What "field" means.** Allowed values: `phone | email | website | address | name | founding_date | nace_code | function_holder | revenue_<year> | profit_<year> | employees_<year> | activity_summary | website_age | postal_code | status`. Discriminate financial fields by year. New fields require a constant added to `src/scraper/db/fields.py`.
6. **Source taxonomy.** Allowed values: `kbo_dump | kbopub | nbb_authentic | goudengids | pagesdor | website | ddg | brave | wayback | manual`. New sources require a constant added to `src/scraper/db/sources.py`.
7. **JSONB value shape.** Each field has a known shape; document patterns:
   - `phone`: `{"e164": "+3232361306", "raw": "03 236 13 06", "type": "fixed_line", "region": "Antwerp"}`
   - `email`: `{"address": "info@bellock.be", "is_role_account": true}`
   - `website`: `{"url": "https://bellock.be", "tld": "be"}`
   - `address`: `{"street": "Lange Van Bloerstraat 116", "postal_code": "2060", "city": "Antwerpen", "country": "BE"}`
   - `name`: `{"text": "Bellock", "lang": "nl"}`
   - `founding_date`: `{"iso": "1989-12-28"}`
   - `nace_code`: `{"code": "43.211", "version": "2008"}`
   - `function_holder`: `{"name": "Boonen, Jan", "role": "bestuurder", "since": "2024-03-27"}`
   - `revenue_2023` / `profit_2023` / `employees_2023`: `{"value": 30326, "currency": "EUR", "filing_ref": "2024-00000148"}`
8. **Append-only enforcement.** A pre-commit grep guard at `scripts/verify_no_updates.sh` blocks PRs containing `UPDATE observations` or `UPDATE companies_current`. The TDD hook does not enforce this — the pre-commit one does.

**`references/schema.sql`** — exact DDL:

```sql
-- be-leads canonical schema. All tables in 'public'.
-- Migrations applied via src/scraper/db/migrations/.

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

-- companies_current is created in a separate migration so the view can reference observations.
```

**`references/current-view.sql`** — the materialised view definition + refresh function. Recompute strategy: `REFRESH MATERIALIZED VIEW CONCURRENTLY companies_current;` (requires a unique index on the matview, which the migration creates).

```sql
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
```

For real-time / ad-hoc reads (without refresh), the LATERAL query pattern:

```sql
-- Get current-best phone for one company:
SELECT DISTINCT ON (field)
       field, value, source, confidence, observed_at
FROM observations
WHERE kbo_number = $1 AND field = 'phone'
ORDER BY field, confidence DESC, observed_at DESC;
```

**`references/confidence.md`** — per-source priors table (start values, tune later):

| Source | phone | KBO# | address | founding | website | financials | persons |
|---|---|---|---|---|---|---|---|
| `kbo_dump` | 0.95 | 1.00 | 0.95 | 1.00 | 0.85 | — | — |
| `kbopub` | 0.85 | 1.00 | 0.95 | 1.00 | 0.80 | — | 0.95 |
| `nbb_authentic` | — | 1.00 | — | — | — | 1.00 | — |
| `goudengids` | 0.85 | 0.85 | 0.80 | 0.85 | 0.85 | — | — |
| `pagesdor` | 0.85 | 0.85 | 0.80 | 0.85 | 0.85 | — | — |
| `website` | 0.75 | 0.50 | 0.70 | — | 1.00 | — | 0.65 |
| `ddg` / `brave` | 0.50 | — | 0.50 | — | 0.55 | — | — |
| `wayback` | — | — | — | — | — | — | — |
| `manual` | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |

Document the formulas: recency decay clamp, consensus boost, and worked example.

**`scripts/verify_no_updates.sh`** — bash, ≤25 lines. Greps `src/` for `UPDATE observations` and `UPDATE companies_current` (case-insensitive, allow whitespace variations). Exits 0 if none found, 2 with stderr message otherwise. Designed to be added to `.pre-commit-config.yaml` in a later step (do not modify pre-commit config in this prompt).

### B. Python module: `src/scraper/db/` and `src/scraper/lib/config.py`

Layout:
```
src/scraper/
├── lib/
│   └── config.py              # NEW
└── db/
    ├── __init__.py
    ├── pool.py
    ├── fields.py
    ├── sources.py
    ├── models.py
    ├── repositories/
    │   ├── __init__.py
    │   ├── observations.py
    │   ├── runs.py
    │   └── jobs.py
    └── migrations/
        ├── __init__.py
        ├── runner.py
        ├── 001_initial.sql
        └── 002_companies_current.sql
```

**`src/scraper/lib/config.py`** — small, type-hinted:

```python
@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str
    log_level: str = "INFO"
    run_env: str = "dev"

def load_settings(env_file: Path | None = None) -> Settings:
    """Load .env via python-dotenv if present, then read from os.environ."""
```

Reads `DATABASE_URL` (required), `LOG_LEVEL`, `RUN_ENV` from env. Calls `dotenv.load_dotenv(env_file)` at the start if the file exists. Raises a typed `ConfigError` (add to `src/scraper/lib/errors.py`) if `DATABASE_URL` missing.

**`src/scraper/db/pool.py`** — async pool singleton with explicit init/close:

```python
async def init_pool(dsn: str, *, min_size: int = 1, max_size: int = 10) -> asyncpg.Pool: ...
async def close_pool() -> None: ...
async def get_pool() -> asyncpg.Pool: ...     # raises if not initialised
@asynccontextmanager
async def acquire_conn() -> AsyncIterator[asyncpg.Connection]: ...
```

Type codecs: register `jsonb` ↔ Python `dict` codec at pool init using `await conn.set_type_codec('jsonb', encoder=json.dumps, decoder=json.loads, schema='pg_catalog')`. UUIDs are native via asyncpg.

**`src/scraper/db/fields.py`** — frozen set of allowed field names + helpers:

```python
ALLOWED_FIELDS: frozenset[str] = frozenset({
    "phone", "email", "website", "address", "name", "founding_date",
    "nace_code", "function_holder", "activity_summary", "website_age",
    "postal_code", "status",
})

def is_financial_field(name: str) -> bool:
    """revenue_<YYYY> / profit_<YYYY> / employees_<YYYY>."""

def validate_field(name: str) -> None:
    """Raise InvalidFieldError if not allowed and not a valid financial field."""
```

**`src/scraper/db/sources.py`** — frozen set:

```python
ALLOWED_SOURCES: frozenset[str] = frozenset({
    "kbo_dump", "kbopub", "nbb_authentic", "goudengids", "pagesdor",
    "website", "ddg", "brave", "wayback", "manual",
})

def validate_source(name: str) -> None: ...
```

**`src/scraper/db/models.py`** — Pydantic v2 row models (boundary types):

```python
class Observation(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: int | None = None
    kbo_number: str         # validated 10 digits via stdnum
    field: str              # validated against ALLOWED_FIELDS / financial pattern
    value: dict[str, Any]
    raw_value: str | None = None
    source: str             # validated against ALLOWED_SOURCES
    source_url: str | None = None
    observed_at: datetime | None = None
    confidence: float       # [0.0, 1.0]
    run_id: UUID

    @field_validator("kbo_number")
    @classmethod
    def _validate_kbo(cls, v: str) -> str:
        from stdnum.be import vat
        return vat.compact(v)

    @field_validator("field")
    @classmethod
    def _validate_field(cls, v: str) -> str:
        from scraper.db.fields import validate_field
        validate_field(v); return v

    @field_validator("source")
    @classmethod
    def _validate_source(cls, v: str) -> str:
        from scraper.db.sources import validate_source
        validate_source(v); return v
```

Add `Run`, `Job` models analogously. Use `model_config = ConfigDict(frozen=True)` for immutability.

**`src/scraper/db/repositories/observations.py`** — async CRUD wrapper:

```python
class ObservationsRepo:
    def __init__(self, pool: asyncpg.Pool) -> None: ...

    async def insert(self, obs: Observation) -> int:
        """Returns the new observation id."""

    async def insert_many(self, obs_list: list[Observation]) -> list[int]:
        """Bulk insert via executemany; one transaction."""

    async def current_best(self, kbo_number: str, field: str) -> Observation | None:
        """LATERAL query, no matview dependency."""

    async def current_all(self, kbo_number: str) -> list[Observation]:
        """All current-best fields for one company."""

    async def history(self, kbo_number: str, field: str) -> list[Observation]:
        """All observations for one (kbo, field), newest first."""
```

**Repo MUST NOT expose any `update` or `delete` method.** This is the load-bearing rule. Add a comment at the top: `# This repository is intentionally append-only. No UPDATE or DELETE methods. See provenance-schema skill.`

**`src/scraper/db/repositories/runs.py`** — `start_run`, `finish_run`, `record_failure`. Returns the run_id (UUID).

**`src/scraper/db/repositories/jobs.py`** — `enqueue`, `pop_pending` (using `SELECT ... FOR UPDATE SKIP LOCKED`), `mark_done`, `mark_failed`, `mark_dead`. Standard worker queue patterns.

**`src/scraper/db/migrations/runner.py`** — minimal SQL-file migration runner:

```python
async def apply_pending(pool: asyncpg.Pool, migrations_dir: Path) -> int:
    """Apply NNN_*.sql files in order whose version exceeds schema_version max.
    Each file runs in its own transaction. Returns the new max version."""
```

Files are matched by leading `^(\d+)_.*\.sql$`. Each insert into `schema_version (version)` happens in the same transaction as the SQL file's contents.

**`001_initial.sql`** — copy of `references/schema.sql` minus the materialised view (which lives in 002).

**`002_companies_current.sql`** — the matview + unique index + `refresh_companies_current()` function.

### C. Tests

Layout:
```
tests/
├── unit/
│   └── db/
│       ├── __init__.py
│       ├── test_models.py
│       ├── test_fields.py
│       └── test_sources.py
└── integration/
    └── db/
        ├── __init__.py
        ├── conftest.py
        ├── test_migrations.py
        ├── test_observations_repo.py
        ├── test_runs_repo.py
        ├── test_jobs_repo.py
        └── test_no_updates_guard.py
```

`tests/integration/db/conftest.py` provides session-scoped fixtures:
- `pg_pool` — connects to `DATABASE_URL`, runs migrations on a **disposable test database** named `leads_test_<timestamp>` (CREATE DATABASE in `postgres` system DB then connect to the new one). Drops the database at session teardown. **Never run integration tests against the dev `leads` DB** — must be a fresh disposable DB.
- `clean_pool` — function-scoped wrapper that TRUNCATES observations, run_log, jobs between tests.

Coverage targets:
- `test_models.py` — Pydantic validators: KBO compaction (`'BE0439401387'` → `'0439401387'`), invalid KBO raises, unknown field raises, financial field accepted (`revenue_2023`), unknown source raises.
- `test_fields.py` — `is_financial_field` true for `revenue_2023`, false for `phone`, false for `revenue_99` (year too short), false for `xxx_2023`.
- `test_sources.py` — round-trip of allowed sources.
- `test_migrations.py` — apply twice → same version, no errors (idempotent). After apply, `\dt` shows the four tables. Asserts the matview exists and its unique index exists.
- `test_observations_repo.py` — `insert` returns id; `insert_many` of 100 obs returns 100 ids; `current_best` returns highest-confidence; `current_best` ties broken by newest `observed_at`; `history` returns newest-first; **assert that the repository class does NOT expose `update` or `delete` methods** (`assert not hasattr(ObservationsRepo, 'update')`).
- `test_runs_repo.py` — start/finish round-trip; UUIDs returned correctly.
- `test_jobs_repo.py` — enqueue → pop_pending returns it; concurrent pops with FOR UPDATE SKIP LOCKED don't double-deliver (start two tasks, assert each gets a different job).
- `test_no_updates_guard.py` — runs `scripts/verify_no_updates.sh`. Asserts exit 0 on a clean tree. Then injects a temp file under `src/scraper/foo_temp.py` containing `UPDATE observations SET ...`, asserts exit 2, deletes the temp file.

Mark all integration tests with `@pytest.mark.integration`. Add `integration` to the `markers` config in `pyproject.toml` (alongside the existing `network` and `slow`). Update `Makefile` `test` target to run unit + integration; keep `test-fast` for unit only.

### D. Update `agent_docs/data-model.md`

Replace the placeholder body with: schema rationale (why append-only, why JSONB, why per-source confidence vs winner-takes-all), the four tables briefly described, the matview refresh strategy, the no-UPDATE rule, and the "what is a field" list. Cross-reference the skill.

### E. Update `agent_docs/runbook.md`

Append:

```
## Database operations
- Start dev Postgres: `docker compose up -d pg`
- Apply migrations: `uv run python -m scraper.db.migrations.runner`
- Refresh companies_current: `psql ... -c "SELECT refresh_companies_current();"` (the pipeline does this automatically; manual only for debugging)
- Wipe dev DB: `docker compose down -v` (destroys the volume)

## Test database
- Integration tests create a disposable `leads_test_<timestamp>` DB and drop it at teardown.
- Never point integration tests at the dev `leads` DB.
```

### F. Update CLAUDE.md

Under "## Per-source knowledge" add:
```
- Provenance schema rules: `.claude/skills/provenance-schema/SKILL.md` (active)
```

Under "## Anti-patterns" add: `Adding update/delete methods to ObservationsRepo. The repo is intentionally append-only.`

### G. Update CHANGELOG

Under `[Unreleased]` add:
```
### Added
- Skill: `provenance-schema` with schema.sql, current-view.sql, confidence.md.
- Module `src/scraper/db/`: pool, repositories (observations, runs, jobs), Pydantic models, migrations runner.
- Module `src/scraper/lib/config.py`: dotenv-aware settings loader.
- Migrations 001 (initial schema) and 002 (companies_current matview).
- Integration tests against disposable Postgres test database.
```

### H. Add a new convenience CLI entry point

In `pyproject.toml`, under `[project.scripts]`, add:
```
be-leads-migrate = "scraper.db.migrations.runner:cli_main"
```

Implement `cli_main()` in `runner.py` — parses `--database-url`/`--migrations-dir`, calls `apply_pending`, prints the new version. So users can `uv run be-leads-migrate` after this prompt lands.

## Verification — run before stopping

```bash
docker compose up -d pg
uv sync --locked --dev
uv run be-leads-migrate                               # applies migrations against leads
uv run pytest -q -m "not network and not slow"        # unit + integration
uv run pytest --cov=src/scraper --cov-fail-under=85 -q -m "not network and not slow"
uv run pytest tests/unit/db -q                        # unit only sanity
uv run mypy src/scraper
uv run ruff check src/scraper tests
uv run ruff format --check src/scraper tests
bash .claude/skills/provenance-schema/scripts/verify_no_updates.sh
psql postgresql://leads:leads@localhost:5432/leads -c "\\dt"
psql postgresql://leads:leads@localhost:5432/leads -c "\\dm"      # materialized views
```

If any step fails, fix it and stop. Don't proceed.

## Stop conditions

When all green:
1. Print one-line summary: number of new files, total tests, coverage % on `src/scraper/db/`.
2. Print verbatim: `Ready for prompt 4 (skill: belgian-phone-validation). Commit: git add . && git commit -m "skill: provenance-schema + DB layer (prompt 3)".`
3. End the turn. Do not start prompt 4.

## Things you must NOT do

- Do not implement source-specific code in `src/scraper/sources/`. Sources come in later prompts.
- Do not implement the materialised-view refresh scheduler. The pipeline owns that.
- Do not add data retention / pruning logic.
- Do not write any UI code.
- Do not modify `pyproject.toml` to add new runtime dependencies — `python-stdnum`, `pydantic`, `asyncpg`, `python-dotenv` are already in the lockfile. The only change to pyproject.toml is the `[project.scripts]` entry and the `markers = [..., "integration"]` line.
- Do not add UPDATE or DELETE methods anywhere on observations or companies_current. The pre-commit guard exists to catch this — write tests that prove the methods don't exist.
