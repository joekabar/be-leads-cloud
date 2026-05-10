# Plan: Ship the polite-scraping skill and src/scraper/lib/http/ module
Date: 2026-05-10
Author: Claude Code
Status: approved

## Goal
Ship the polite-scraping skill plus the supporting Python module `src/scraper/lib/http/`
(client, limiter, retry, robots) it documents, with full test coverage for the limiter, retry,
and robots logic. Every subsequent source module will import from this module instead of
creating ad-hoc HTTP clients.

## Scope (in)
- `.claude/skills/polite-scraping/` — SKILL.md, references/, scripts/
- `src/scraper/lib/errors.py` — typed exception hierarchy
- `src/scraper/lib/http/` — client.py, limiter.py, retry.py, robots.py, __init__.py
- `tests/unit/lib/http/` — test_limiter.py, test_retry.py, test_robots.py, test_client.py
- `tests/integration/test_polite_client_live.py` — @pytest.mark.network
- CLAUDE.md — one-line pointer under Per-source knowledge
- CHANGELOG.md — Unreleased entry

## Out of scope
- Source modules (src/scraper/sources/)
- Playwright / Imperva cookie handling (goudengids prompt)
- Caching layer (hishel or similar)
- Database code (prompt 3)
- New pyproject.toml dependencies (all already in lockfile)

## Files to be created or modified
- `.claude/plans/2026-05-10-polite-scraping.md` (this file)
- `.claude/skills/polite-scraping/SKILL.md`
- `.claude/skills/polite-scraping/references/per-host.toml`
- `.claude/skills/polite-scraping/references/headers.md`
- `.claude/skills/polite-scraping/references/status-codes.md`
- `.claude/skills/polite-scraping/scripts/check_robots.py`
- `src/scraper/lib/__init__.py`
- `src/scraper/lib/errors.py`
- `src/scraper/lib/http/__init__.py`
- `src/scraper/lib/http/limiter.py`
- `src/scraper/lib/http/retry.py`
- `src/scraper/lib/http/robots.py`
- `src/scraper/lib/http/client.py`
- `tests/unit/__init__.py`
- `tests/unit/lib/__init__.py`
- `tests/unit/lib/http/__init__.py`
- `tests/unit/lib/http/test_limiter.py`
- `tests/unit/lib/http/test_retry.py`
- `tests/unit/lib/http/test_robots.py`
- `tests/unit/lib/http/test_client.py`
- `tests/integration/__init__.py`
- `tests/integration/test_polite_client_live.py`
- `CLAUDE.md`
- `CHANGELOG.md`

## Tests required (red first)
- test_limiter: rps capping, concurrency cap, load_from_toml round-trip, default fallback
- test_retry: 200 first try; 429→200; 503×3→200; 403→BlockedError; Retry-After; exhausted→RetriesExhaustedError
- test_robots: 404→allow; disallow rule; cache hit; TTL expiry
- test_client: end-to-end through respx; RobotsDisallowedError before HTTP

## Acceptance criteria
- [ ] Skill file exists at `.claude/skills/polite-scraping/SKILL.md` with valid YAML frontmatter
- [ ] All four http/ modules importable
- [ ] `uv run pytest --cov=src/scraper/lib --cov-fail-under=90 -q -m "not network"` passes
- [ ] `mypy --strict` clean on src/scraper
- [ ] `ruff check` and `ruff format --check` clean

## Risks
- Token-bucket timing tests can be flaky on slow CI; use generous tolerances
- respx version API differences (>=0.22 assumed)

## Rollback plan
- Delete src/scraper/lib/, tests/unit/lib/, tests/integration/ and revert CLAUDE.md/CHANGELOG.md
