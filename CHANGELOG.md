# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed (Prompt 13 — goudengids browser-throughout)
- `goudengids` fetcher: replaced two-phase warmup+httpx pattern with a single Playwright Chromium session held open for the entire sector×city scrape. Eliminates Imperva re-challenges on httpx TLS fingerprint. User-agent is read from the installed binary at launch (no hardcoded Chrome version).
- `goudengids` ingester: `ingest_sector_city` now manages the browser lifecycle internally via `async with fetcher:` — callers no longer call `fetcher.warm()`.
- `goudengids` CLI and pipeline orchestrator updated to construct `BrowserListingFetcher` instead of `GoudengidsFetcher`.
- Coverage config: `omit = ["*/archive/*"]` so archived reference code doesn't drag total coverage below threshold.

### Added (Prompt 13 — goudengids browser-throughout)
- `BrowserListingFetcher` class with `fetch_listing(url) → str` and `fetch_page(sector, city, page) → ListingPage`.
- `is_blocked(html)` helper: detects "pardon our interruption" / "imperva" in page body and raises `BlockedError` immediately (no retry loop).
- Old `warmup.py` and `fetcher.py` (httpx-based) archived to `src/scraper/sources/goudengids/archive/` for reference.
- Fetcher tests rewritten with Playwright route mocking (`context.route("**/*", handler)`) — no real network traffic; 5 tests covering listing parse, no-results, FR domain, city slug hyphenation, Imperva block detection.

### Changed (Prompt 12 — KBO real-scale refactor + filters)
- `kbo_dump` ingester: bulk insert via asyncpg text-format COPY (~100x faster than per-row INSERT).
- `kbo_dump` ingester: removed per-batch dedup SELECT — matview resolves duplicates at refresh time. Re-ingesting the same ZIP without `--truncate-first` creates duplicate rows (storage waste, ~250MB/run); data integrity is preserved by `companies_current` DISTINCT ON resolution.

### Added (Prompt 12 — KBO real-scale refactor + filters)
- `kbo_dump` CLI: `--month YYYY-MM` (auto-detected from filename), `--sector-nace`, `--city`, `--max-enterprises`, `--truncate-first`, `--yes` flags.
- `kbo_dump` filter implementation (deferred from prompt 5): two-pass keep-set strategy across activity.csv + address.csv with AND logic for combined sector + city filters.
- Generated 10k-row deterministic fixture (`tests/integration/sources/kbo_dump/_generate_large_fixture.py`, seed=42, cached to `tests/golden/kbo_dump/large_10k/`).
- 5 new scale integration tests (`@pytest.mark.slow`) in `test_ingester_scale.py`.
- Runbook section: real-ZIP manual smoke procedure.

### Added (Prompt 11 — Pipeline orchestrator + Streamlit UI)
- Scoring engine (`src/scraper/scoring/`): `confidence.py` (per-source priors table, recency decay, consensus boost) and `ranking.py` (`LeadScore` dataclass, `compute_lead_score` — 0.5 completeness + 0.35 authority + 0.15 recency).
- Pipeline orchestrator (`src/scraper/pipeline/orchestrator.py`): `PipelineConfig`, `PipelineReport`, `run_pipeline` — wires all 6 sources in dependency order with per-source error isolation.
- Consolidation pass (`src/scraper/pipeline/consolidate.py`): three-pass rapidfuzz name matching (name+postal → name+city → name_only ≥ 90); re-emits placeholder observations under real KBO with confidence × 0.9 inference penalty.
- Pipeline runner (`src/scraper/pipeline/run.py`): loads settings, initialises pool + PoliteClient, calls `run_pipeline`, closes resources.
- CLI entry point `be-leads-pipeline` (`src/scraper/pipeline/cli.py`): `--sector`, `--city`, `--max-pages`, `--lang`, `--use-fixture`, `--skip-*` flags, JSON output.
- Streamlit UI (`src/scraper/ui/`): `app.py` (sector × city picker, source toggles, run button, results table), `data.py` (`fetch_results_for_run` with NACE + city filtering), `components/pickers.py`, `components/results_table.py`, `components/progress.py`.
- Integration tests: consolidation integration (3), orchestrator with mocked ingesters (3), end-to-end smoke (2 in-process + 1 subprocess CLI).
- Unit tests: scoring confidence (33), scoring ranking (8), consolidation unit (9), UI data helpers (16 including 5 mocked async fetch tests), pipeline CLI unit (7). 609 total passing.
- `rapidfuzz>=3.9` and `pandas>=2.2` added to runtime dependencies.
- Mypy overrides added for `rapidfuzz`, `streamlit`, `pandas` (no public stubs).

### Added
- Skill: `search-cross-validation` with `engines.md`, `result-classification.md`, `query-templates.md`, and `scripts/probe_search.py`.
- Source: `ddg_brave` — Brave Search API client (primary, 1 qps, 2k/month free) + DuckDuckGo via `ddgs` library (fallback). Per-result classifier: `official_website | directory | social | news | other`.
- New observation field type: `cross_validation` (JSONB summary of one search query's classified results). Added to `ALLOWED_FIELDS`.
- 8 golden fixtures in `tests/golden/ddg_brave/` (Brave JSON + DDG list responses).
- 57 unit tests + 19 integration tests for `ddg_brave`; coverage ≥ 85% on source.
- CLI: `uv run be-leads-search-validate --inputs <tsv>` or `--from-db --limit N`.
- `ddgs>=9` runtime dependency.
- `.env.example`: `BRAVE_SEARCH_API_KEY` entry.
- Runbook: Brave registration walkthrough + quota budgeting + cross-validation invocation.
- Updated `CLAUDE.md`: `search-cross-validation` skill reference; anti-pattern for treating search results as authoritative.
- Skill: `website-analysis` with `selectors-heuristics.md`, `age-heuristics.md`, `extraction-priorities.md` references and `scripts/analyze_url.py`.
- Source: `website` — fetcher, JSON-LD extractor (`structured.py`), contact-page discoverer (`contact_page.py`), person extractor — microdata + heuristic (`persons.py`), age estimator — WHOIS + footer year (`age.py`), transformer, ingester (concurrency-15 fan-out, 7-day skip window), CLI.
- 5 golden HTML fixtures in `tests/golden/website/`: WordPress LocalBusiness, Squarespace Organization, custom-no-JSON-LD, Person microdata contact page, FR heuristic about page.
- CLI: `uv run be-leads-enrich-website --kbos-and-websites <tsv>` or `--from-db --limit N`.
- Added `python-whois>=0.9.5` runtime dependency (optional WHOIS path; falls back gracefully to footer-year if unavailable).
- Updated CLAUDE.md: `website-analysis` skill reference.
- Skill: `goudengids-listing` with `selectors.md`, `imperva-bypass.md`, `sectors.toml` (65 sectors), and `scripts/probe_listing.py`.
- Source: `goudengids` — Playwright warmup + httpx-based listing scraper for goudengids.be / pagesdor.be.
- Synthetic placeholder KBO scheme (9-prefix, SHA-256-based) for sources without authoritative KBO numbers.
- 4 golden HTML fixtures: antwerpen full (12 cards), brugge sparse (6 cards), no-results, FR Liège.
- CLI: `uv run be-leads-discover-goudengids --sector <slug> --city <name>`.
- `Observation._validate_kbo` now accepts 10-digit 9-prefix placeholder KBOs.
- Provenance-schema skill §9: Synthetic placeholder KBOs documented.
- Runbook: Goudengids / pagesdor discovery section with rate, blocking, and placeholder guidance.
- Skill: `nbb-financials` with `SKILL.md`, `references/api-spec.md`, `references/field-mapping.md`, `references/filing-types.md`, and `scripts/probe.py`.
- Source: `src/scraper/sources/nbb_authentic/` — async REST client + parser + transformer + ingester for NBB CBSO Authentic Data API.
- Two new errors in `lib/errors.py`: `NbbAuthError` (401 — abort batch) and `NbbNotFoundError` (404 — skip and continue).
- 8 static JSON fixtures in `tests/golden/nbb_authentic/` covering 3-year, 1-year, empty, and null-field cases.
- 25 unit tests (parser, transformer) + 17 integration tests (client, ingester, CLI); coverage ≥ 90 % on `nbb_authentic`.
- CLI: `uv run be-leads-fetch-nbb --kbos <list>` with `--years-back`, `--skip-recent-hours`, `--subscription-key`.
- Runbook: NBB CBSO registration walkthrough + ingestion commands.
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
