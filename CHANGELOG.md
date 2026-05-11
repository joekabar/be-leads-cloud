# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Source: `src/scraper/sources/kbopub_html/` — fetches kbopub detail pages to extract function holders (directors, managers, auditors) and writes them as append-only `function_holder` observations with confidence 0.95.
- CLI entry point `be-leads-fetch-kbopub` with `--kbos` (comma list or `@file`), `--lang`, `--skip-recent-hours`, `--database-url`.
- Parser supports NL + FR page languages, 21 role labels mapped to canonical English slugs, legal-person and linked-KBO detection, and `since` date parsing.
- Idempotency: skips KBOs with a kbopub observation within `--skip-recent-hours` (default 24).
- BlockedError on HTTP 403 aborts the batch without retry; 404 is counted and the batch continues.
- 5 golden HTML fixtures in `tests/golden/kbopub_html/`.
- 46 unit tests (parser, transformer) + 8 integration tests + 1 slow rate-limiter timing test; coverage 98.4%.
- Updated `kbopub-selectors.md` with page structure, selectors, role-label table, and date-parsing rules.
- Updated runbook with function-holder enrichment section (manual run, batch, rate, 403 handling).
- Skill: `kbo-lookup` with SKILL.md, `references/open-data-schema.md`, `references/checksum.md`, `references/kbopub-selectors.md` (placeholder), and `scripts/validate_kbo.py`.
- Source: `src/scraper/sources/kbo_dump/` — streaming CSV parser, observation transformer, idempotent ingester (Pattern A dedup by kbo/field/value/source), Update ZIP delete markers, sector/city filter.
- CLI entry points: `be-leads-ingest-kbo` and `be-leads-validate-kbo`.
- Golden fixture: `tests/golden/kbo_dump/synthetic_mini/` (5 enterprises, 39 expected observations).
- 71 unit tests + 9 integration tests for kbo_dump; coverage ≥ 91%.
- Skill: `belgian-phone-validation` with `references/prefixes.tsv` (BIPT-derived) and `numbering-plan-rules.md`.
- Module `src/scraper/lib/validators/phone.py` with `validate_phone()` returning the canonical `PhoneValidation` Pydantic model.
- CLI: `uv run be-leads-validate-phone "<number>"`.
- Skill: `provenance-schema` with schema.sql, current-view.sql, confidence.md, and verify_no_updates.sh guard script.
- Module `src/scraper/db/`: asyncpg pool, repositories (observations, runs, jobs), Pydantic row models, fields/sources constants.
- Module `src/scraper/lib/config.py`: dotenv-aware settings loader with `ConfigError`.
- Migrations 001 (initial schema: schema_version, run_log, observations, jobs) and 002 (companies_current materialised view + refresh function).
- CLI entry point `be-leads-migrate` (`uv run be-leads-migrate`).
- Integration tests against disposable Postgres test database (71 tests total, 91% coverage).
- Scaffold: project structure, pyproject.toml, Docker Compose, Claude hooks, and TDD guardrails (prompt 1).
- Skill: `polite-scraping` with per-host TOML, headers, and status-code reference.
- Module `src/scraper/lib/http/` (client, limiter, retry) and `lib/errors.py`.
- Tests: 4 unit modules + 1 network-marked integration test.
