# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed (NACE sector filter — three root-cause bugs causing wrong results)

**Bug 1 — kbo_dump prefix matching:** `_build_filter_set` in `kbo_dump/ingester.py` used `nace_code.split(".")[0]` to extract the "division", then compared it to the filter set with `in`. KBO Open Data stores NACE codes *without dots* (`"62019"`, not `"62.019"`), so `split(".")[0]` returned the full 5-digit code — meaning `"62019" in {"620"}` was always `False`. The kbo_dump therefore ingested 0 entities for any sector whose prefix is shorter than the full NACE code. Fixed by switching to `any(nace_code.startswith(p) for p in prefixes)`.

**Bug 2 — results query used only first prefix:** `fetch_results_for_run` in `ui/data.py` resolved `nace_prefix = prefixes[0]` (a single string). The KBO discovery SQL used `LIKE $2` with that one string, and the secondary in-memory filter only checked `startswith(nace_prefix)`. Sectors with multiple prefixes (informaticabedrijven: `["620","631","582"]`; transportbedrijven: `["4941","4939","4942"]`; etc.) would drop all companies matching any prefix after the first. Fixed by computing `nace_patterns = [f"{p}%" for p in nace_prefixes]`, using `LIKE ANY($2::text[])` in SQL, and checking all prefixes in the secondary filter.

**Bug 3 — incorrect NACE mappings for three sectors:**
- `elektriciens`: was `"432"` (overlapped with plumbing `4322`, plastering `4331`). Corrected to `"4321"` (electrical installation only).
- `metselaars`: was `"433"` (building *finishing* — plastering, joinery, painting). Bricklayers in Belgian KBO register under `4120` (general building construction) and `4399` (other specialised construction). Corrected to `["4120","4399"]`.
- `garagisten`: was `"452"` (2-digit-equivalent 3-char prefix). Tightened to `"4520"`.
- `informaticabedrijven`: added `"582"` (software publishing — 58210 custom software publishers, 58290 other).

**Tests added:**
- `tests/unit/sources/kbo_dump/test_ingester_build_filter.py` — 5 tests for `_build_filter_set`: exact match, 3-digit prefix against dotless 5-digit codes, multi-prefix union, no-filter returns None, sector+city intersection.
- `tests/unit/ui/test_data.py` — `test_nace_filter_includes_second_prefix` and `test_nace_filter_includes_third_prefix` verify multi-prefix NACE pass-through.
- `tests/unit/pipeline/test_sector_nace.py` — added spot-checks for corrected mappings and two negative assertions (`elektriciens` must not contain `"432"`, `metselaars` must not contain `"433"`).

### Added (UI review — gov.uk style theme, Approach B)
- `.streamlit/config.toml`: Streamlit base theme (`#1D70B8` primary, `#F3F2F1` background, `#FFFFFF` surface, `#0B0C0C` text).
- `src/scraper/ui/theme.py`: CSS module with `inject_theme()`. Covers: 5px Belgian flag accent bar (black/yellow/red), `#003078` headings with blue underline/border, square-cornered buttons, blue Run button, sidebar white surface, muted footer caption, gov.uk-style info box borders.
- Sources section now collapsed by default — Run pipeline button visible without scrolling.
- Idle hint replaced with muted grey text; no longer renders as a blue info box.
- 7 unit tests in `tests/unit/ui/test_theme.py` covering CSS token presence and `inject_theme()` smoke.

### Fixed (UI review — NACE sector filter missing for 58 sectors)
- `_SECTOR_NACE_PREFIXES` in `pipeline/orchestrator.py` only covered 10 construction/trade sectors. Any other sector (accountants, advocaten, restaurants, hotels, …) ran the KBO dump with no NACE filter, returning every company in the city. A search for "accountants · Aalst" produced 6437 results instead of ~50.
- Added NACE prefixes for all 67 sectors across 8 groups: construction, automotive, food/hospitality, retail, professional services, healthcare, ICT, and other services.
- Added `tests/unit/pipeline/test_sector_nace.py` with 19 tests: full-coverage assertion, no-empty-list guard, dotless-format guard, and 16 spot-checks for specific sector→prefix mappings.

### Fixed (Prompt 15 — phone false-positive spam)
- `_PHONE_TEXT_RE` in `website/ingester.py` ran against raw HTML, matching SVG `viewBox` coords, CSS `calc()` dimensions, decimal version strings, and other numeric noise as if they were Belgian phone numbers. Hundreds of `website_invalid_phone_skipped` warnings per run.
- Fix 1: removed `.` from the character class (`[0-9 \-\/]`) — Belgian phone numbers never contain decimal points.
- Fix 2: added `_visible_text()` helper (strips `<script>`, `<style>`, `<svg>`, `<noscript>` before extracting text nodes); `_PHONE_TEXT_RE` and `_EMAIL_TEXT_RE` now scan visible text instead of raw HTML. `tel:` hrefs still scan raw HTML as before.

### Fixed (Prompt 15 — UI always shows 0 results)
- `PipelineReport.run_id` is always `None` (the orchestrator never sets it), so `app.py`'s guard `if pool and report.run_id:` short-circuited to an empty row list after every pipeline run.
- Changed `fetch_results_for_run` to accept `started_at: datetime` instead of `run_id: UUID`. The query now finds all KBOs with `observed_at >= started_at`, which covers both source observations and consolidation re-emissions (which have their own `run_id` and were invisible under the old approach).
- `app.py` now passes `report.started_at` (always populated) and drops the `run_id` guard.

### Fixed (Prompt 14 — pipeline orchestrator scoping bug)
- `_get_real_kbos()`, `_get_website_pairs()`, `_get_placeholder_inputs()` each previously fetched from the entire observations table (1.9M rows), causing kbopub to attempt enrichment of every Belgian company and website source to visit 36K URLs on each pipeline run.
- All three now accept a `since: datetime` parameter and filter `observed_at >= since`, scoping each source to companies discovered in the current pipeline run only. `started_at` (captured at `run_pipeline` entry) is passed through.
- `_get_website_pairs()` also drops the `NOT LIKE '9%'` filter so it visits goudengids-placeholder companies' websites (they have websites but placeholder KBOs).

### Fixed (Prompt 14 — goudengids parser null JSON fields)
- `data.get("title", "")`, `data.get("href", "")`, `data.get("phone", "")`, `data.get("logo", "")` in `_parse_card()` all returned `None` when the JSON field existed with `null` value (Python `dict.get` only falls back to the default when the key is *absent*). Changed to `(data.get(key) or "")` pattern to treat both absent and null as empty string.

### Fixed (Prompt 14 — kbopub multi-holder parser bug)
- Root cause: companies with >~5 function holders use a different layout — kbopub wraps all holders in a hidden `<table id="toonfctie">` inside a single `<td colspan="3">`. `find_all("td")` recursed into nested TDs, making `tds[0].get_text()` the entire concatenated block ("whole bestuurder block"), logged as `unknown_role_label`.
- Fixed `parse_function_holders` to detect `<table id="toonfctie">` sibling rows and delegate to new `_parse_hidden_function_table()`. Changed direct-child TD selection to `find_all("td", recursive=False)` so nested table content never bleeds into the column list.
- Added `_parse_holder_tds()` shared helper to eliminate code duplication between the two layouts.
- Extended `_LINKED_KBO_RE` with two new patterns: parenthesised dotted `(0405.117.332)` and standalone dotted `0405.117.332` — the actual formats kbopub uses in multi-holder pages (prev. patterns only covered `met KBO` prefix and bare 10-digit).
- Added `"Persoon belast met dagelijks bestuur": "daily_manager"` to `_ROLE_MAP`.
- New golden fixture `0500000001_many_holders.html`; 5 new tests covering the hidden-table layout, both KBO link formats, and zero unknown_role_label warnings.

### Added (Prompt 14 — kbo_dump skip-if-fresh)
- `ingest_zip(..., skip_if_fresh=True)`: checks for existing `kbo_dump` observations in the same snapshot month before starting; returns immediately with 0 rows if already ingested. Prevents duplicate ~250 MB ingests in recurring pipeline runs.
- `be-leads-ingest-kbo --skip-if-fresh` CLI flag wired through `_run`.
- Two new tests: `test_skip_if_fresh_skips_when_data_exists` and `test_skip_if_fresh_runs_when_no_data`.

### Fixed (Prompt 14 — goudengids Imperva two-phase warmup)
- `BrowserListingFetcher._warmup()`: navigate to domain homepage with `wait_until="load"` on first `fetch_listing` call to establish Imperva `incap_ses_*` session cookies before hitting search pages. Without this, Imperva's JS challenge page is returned instead of real results (0 cards). `wait_until="networkidle"` was rejected — Imperva's challenge scripts keep the network permanently busy.
- Main `fetch_listing` navigation changed from `wait_until="domcontentloaded"` to `wait_until="load"` so any JS redirect after the challenge completes.
- Pre-existing ruff issues cleaned: `assert` → `RuntimeError`, `try/except/pass` → `contextlib.suppress`, `S311` noqa for intentional sleep jitter.

### Added (Prompt 14 — goudengids Imperva two-phase warmup)
- `test_warmup_runs_once_then_skipped`: verifies homepage navigation fires exactly once across multiple `fetch_page` calls.

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
