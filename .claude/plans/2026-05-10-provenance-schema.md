# Plan: Ship the provenance-schema skill and DB layer
Date: 2026-05-10
Author: joekabar
Status: approved

## Goal
Ship the provenance-schema skill and the DB layer (asyncpg pool, migrations, observations +
companies + jobs + run_log + schema_version, repositories, Pydantic row models) with full
integration tests against a real Postgres in docker compose. After this prompt, every source
can write observations and read current-best.

## Scope (in)
- Skill: `.claude/skills/provenance-schema/` (SKILL.md, references/, scripts/)
- Module `src/scraper/db/`: pool, fields, sources, models, repositories (observations, runs, jobs), migrations runner
- Module `src/scraper/lib/config.py`: dotenv-aware settings loader
- Migrations: 001_initial.sql, 002_companies_current.sql
- Tests: unit (models, fields, sources) + integration (migrations, repos, no-update guard)
- Updates to agent_docs/data-model.md and agent_docs/runbook.md
- CLAUDE.md updates (anti-patterns, per-source knowledge)
- CHANGELOG entry
- CLI entry point `be-leads-migrate` in pyproject.toml

## Out of scope
- Any specific source ingestion (src/scraper/sources/)
- Materialised-view refresh scheduler (deferred to pipeline prompt)
- Data pruning / retention logic
- Streamlit views

## Files to be created or modified
- `.claude/skills/provenance-schema/SKILL.md` (new)
- `.claude/skills/provenance-schema/references/schema.sql` (new)
- `.claude/skills/provenance-schema/references/current-view.sql` (new)
- `.claude/skills/provenance-schema/references/confidence.md` (new)
- `.claude/skills/provenance-schema/scripts/verify_no_updates.sh` (new)
- `src/scraper/lib/config.py` (new)
- `src/scraper/lib/errors.py` (modified — add ConfigError, InvalidFieldError, InvalidSourceError)
- `src/scraper/db/__init__.py` (new)
- `src/scraper/db/pool.py` (new)
- `src/scraper/db/fields.py` (new)
- `src/scraper/db/sources.py` (new)
- `src/scraper/db/models.py` (new)
- `src/scraper/db/repositories/__init__.py` (new)
- `src/scraper/db/repositories/observations.py` (new)
- `src/scraper/db/repositories/runs.py` (new)
- `src/scraper/db/repositories/jobs.py` (new)
- `src/scraper/db/migrations/__init__.py` (new)
- `src/scraper/db/migrations/runner.py` (new)
- `src/scraper/db/migrations/001_initial.sql` (new)
- `src/scraper/db/migrations/002_companies_current.sql` (new)
- `tests/unit/db/__init__.py` (new)
- `tests/unit/db/test_models.py` (new)
- `tests/unit/db/test_fields.py` (new)
- `tests/unit/db/test_sources.py` (new)
- `tests/integration/db/__init__.py` (new)
- `tests/integration/db/conftest.py` (new)
- `tests/integration/db/test_migrations.py` (new)
- `tests/integration/db/test_observations_repo.py` (new)
- `tests/integration/db/test_runs_repo.py` (new)
- `tests/integration/db/test_jobs_repo.py` (new)
- `tests/integration/db/test_no_updates_guard.py` (new)
- `agent_docs/data-model.md` (replace placeholder body)
- `agent_docs/runbook.md` (append DB operations section)
- `CLAUDE.md` (add provenance-schema skill ref + anti-pattern)
- `CHANGELOG.md` (add Unreleased entries)
- `pyproject.toml` (add integration marker + be-leads-migrate script)
- `Makefile` (update test target to include integration)

## Tests required (red first)
- test_models.py: KBO compaction, invalid KBO, unknown field, financial field accepted, unknown source
- test_fields.py: is_financial_field true/false/edge cases
- test_sources.py: allowed sources round-trip
- test_migrations.py: idempotent apply, tables exist, matview + unique index exist
- test_observations_repo.py: insert, insert_many, current_best, history, no update/delete methods
- test_runs_repo.py: start/finish round-trip
- test_jobs_repo.py: enqueue/pop/concurrent SKIP LOCKED
- test_no_updates_guard.py: script exits 0 clean, exits 2 with injected UPDATE

## Acceptance criteria
- [ ] Skill has valid frontmatter matching polite-scraping style
- [ ] Migrations apply idempotently against docker compose Postgres
- [ ] observations is append-only (no UPDATE/DELETE in repo, test_no_updates_guard passes)
- [ ] companies_current matview returns highest-confidence-then-newest per (kbo_number, field)
- [ ] Coverage on src/scraper/db/ ≥ 90%
- [ ] mypy --strict clean
- [ ] ruff check + ruff format --check clean

## Risks
- asyncpg jsonb codec registration must happen at pool init
- Disposable test DB creation requires connecting to `postgres` system DB first
- verify_no_updates.sh must handle Windows line endings and path separators in CI

## Rollback plan
- The plan file is checked into git; revert the commit to undo all changes.
- `docker compose down -v` destroys the dev DB volume if migrations are broken.
