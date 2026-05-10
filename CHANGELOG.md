# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
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
