# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project (one paragraph)
High-volume recurring scraper for Belgian B2B company data. Sources will be added incrementally:
KBO Open Data dump (canonical bulk), kbopub HTML (function holders), NBB CBSO Authentic Data
(financials), goudengids/pagesdor listing pages (discovery), company websites (enrichment),
DuckDuckGo + Brave (cross-validation). Output: provenance-tracked Postgres database with a
Streamlit UI for sector × city queries.

## Architecture map
- `src/scraper/lib/`              cross-cutting helpers (http, polite, validators, errors, logging, config); `data_paths.py` resolves bundled TOML files (`per-host.toml`, `sectors.toml`, `postcodes.toml`) relative to the installed package
- `src/scraper/db/`               asyncpg pool, repositories, migrations, Pydantic row models; `fields.py` (ALLOWED_FIELDS + financial-field regex); `sources.py` (ALLOWED_SOURCES registry — validate before inserting any `source` column value)
- `src/scraper/sources/<name>/`   one directory per source. Core pipeline is `parser.py` (raw → typed records) → `transformer.py` (typed records → observation tuples) → `ingester.py` (persist) → `cli.py`. The fetch layer is source-specific: `fetcher.py` (kbopub/website/goudengids — goudengids also has `warmup.py`), `client.py` (nbb_authentic), `brave_client.py`/`ddg_client.py`/`classifier.py` (ddg_brave), `downloader.py`/`staging.py`/`stage_cli.py`/`cleanup_cli.py` (kbo_dump — no `fetcher.py`), `structured.py`/`contact_page.py`/`persons.py`/`age.py` (website). `goudengids/archive/` holds the retired httpx warmup approach (excluded from coverage).
- `src/scraper/pipeline/`         `run.py` (entry), `orchestrator.py` (single-run fan-out), `batch.py` (multi-sector batch orchestrator), `consolidate.py` (placeholder merge), `progress.py` (live progress reporter), `cli.py` / `batch_cli.py`; city slug→postal-code lookup in `city_map.py` (reads `city_map.toml` next to it)
- `src/scraper/scoring/`          `confidence.py` (priors + decay), `ranking.py` (LeadScore aggregation), `hv_prior.py` (NACE→HV probability table), `prospect.py` (ProspectScore)
- `src/scraper/ui/`               Streamlit app (`app.py`), `data.py` (main DB queries), `export.py` (CSV export CLI), `components/` (reusable widgets), `queries/` (page-specific DB queries, e.g. `snapshots.py` for KBO staging data), `pages/` (multi-page Streamlit pages). **UI-triggered pipeline runs** (added in `8cfc418`): `pages/run_pipeline.py` (batch-launch page) → `run_config.py` (`build_batch_config`: widget values → `BatchConfig`, streamlit-free so it's unit-testable) → `batch_runner.py` (`run_batch_job`: wires a pool + `PoliteClient`, mirrors `batch_cli._run`) run off the script thread via `background.py` (`start_async_job`/`poll_job` — async work in a daemon thread, result delivered through an `st.session_state` queue). This is a second execution path into `pipeline/batch.py::run_batch` that does not go through the CLI.

Async boundary: every I/O function is `async`. Sync code is forbidden in `sources/`, `db/`, `pipeline/`.
UI may call `asyncio.run` at boundaries.

## Data model
Core: five tables + one materialised view, plus batch-support tables (5 `kbo_stage_*` staging tables + `pipeline_progress`). Migrations `001`–`007` live in `src/scraper/db/migrations/` and are applied in order by `runner.py`.

- `run_log` — one row per pipeline run; every `observations` row has a `run_id` FK into it.
- `observations` — append-only fact store. Each scraped field value is one INSERT; UPDATE is forbidden.
  - Key columns: `kbo_number CHAR(10)`, `field TEXT`, `value JSONB`, `source TEXT`, `confidence NUMERIC(3,2)`, `run_id UUID`.
  - Allowed field names defined in `src/scraper/db/fields.py`: `phone | email | website | address | name | founding_date | nace_code | function_holder | activity_summary | website_age | postal_code | status | cross_validation | legal_form`. Financial fields follow `{revenue|profit|employees}_{YYYY}`.
  - Allowed `source` strings defined in `src/scraper/db/sources.py::ALLOWED_SOURCES` (validated, else `InvalidSourceError`): `kbo_dump | kbopub | nbb_authentic | goudengids | pagesdor | website | ddg | brave | wayback | manual`. **These differ from directory names** — dir `kbopub_html` → source `"kbopub"`; dir `ddg_brave` → two sources `"ddg"` and `"brave"`. Never write the directory name as the source.
- `jobs` — `SELECT … FOR UPDATE SKIP LOCKED` worker queue; `JobsRepo.pop_pending()` atomically claims jobs. **Not wired into the pipeline orchestrator** — the orchestrator calls ingesters directly. The table exists for future async-worker use.
- `prospect_scores` — upsertable (not append-only) commercial scoring table. One row per KBO; populated by `scoring/prospect.py::refresh_prospect_scores(pool)` after each pipeline run. Columns: `hv_probability`, `business_activity`, `contact_quality`, `growth_signal`, `overall_prospect`, `computed_at`. Unlike `observations`, rows are overwritten on conflict.
- `schema_version` — migration tracker; managed exclusively by `src/scraper/db/migrations/runner.py`.
- `kbo_stage_*` (5 tables: `enterprise | address | denomination | contact | activity`) — `UNLOGGED`, keyed by `entity_number + snapshot_date`; populated once per ZIP by `sources/kbo_dump/staging.py::stage_zip` (parses the 5 CSVs in a `ProcessPoolExecutor`, drops/recreates secondary indexes around the load). The batch pipeline (Phase A) emits observations from these via SQL filter + COPY — no re-parse. Schema drift is detected by `_detect_drift` (CSV-header compare, logged warning); there is no `raw_row` column (dropped in migration 007).
- `pipeline_progress` — mutable telemetry table, one row per run, for live UI progress reporting (`pipeline/progress.py`). Not a fact store.
- `companies_current` (materialised view) — `DISTINCT ON (kbo_number, field)` ordered by `confidence DESC, observed_at DESC`. Refreshed via `refresh_companies_current()` after each pipeline run. Never refresh from a repo method.

See `agent_docs/data-model.md` for full column specs, JSONB shapes, and the no-UPDATE enforcement layers.

### Pipeline execution order
**Single-run (`orchestrator.py::run_pipeline`)** — used by `be-leads-pipeline`:
- Wave A: `kbo_dump` **alone** (CPU-heavy ZIP parse runs first so it doesn't starve Chromium)
- Wave B: `goudengids` ‖ `kbopub_html` ‖ `nbb_authentic` ‖ `website` ‖ `ddg_brave` (parallel, different hosts)
- Then: `consolidate` → `refresh_companies_current()` → `refresh_prospect_scores()`

**Batch (`batch.py::run_batch`)** — used by `be-leads-pipeline-batch` (preferred for production; stage-once, ~1.5 h):
- Phase A: emit from `kbo_stage_*` tables (SQL filter + COPY, no network)
- Phase B: goudengids per sector, sequential (WAF-bound, concurrency=1)
- Phase C1: kbopub + nbb + website enrichment, concurrent with Phase B
- Phase C2: ddg_brave search validation, after Phase B completes
- Phase D-F: single consolidation → single matview refresh → single prospect scoring pass

### KBO number conventions
- Real KBOs: 10 digits, mod-97 checksum, validated via `python-stdnum.be.vat`. KBO Open Data stores NACE codes **without dots** (e.g. `"43211"` not `"43.21"`).
- Placeholder KBOs: `9xxxxxxxxx` pattern (prefix `9`), generated by goudengids when a listing has no KBO number. They intentionally fail the mod-97 check.

### Enrichment dependency chain (critical)
- `kbopub_html` and `nbb_authentic` **only run on real KBOs** — `_get_real_kbos()` filters `WHERE kbo_number NOT LIKE '9%'`. Placeholders get **no** function holders, founding dates, or financials until consolidation merges them.
- Consolidation needs real KBOs in the DB to match against. **Without a loaded KBO Open Data ZIP, every goudengids placeholder stays unenriched forever.** This is the single biggest cause of thin results.
- `website` enrichment runs on any KBO with a website observation (placeholders included).
- Canonical ZIP location in this project: `KBO_zip/KboOpenData_*.zip`. The pipeline CLI requires either `--use-fixture` (synthetic test data) or `--fixture-zip <path>` — kbo_dump never auto-discovers.

### Sector-scoped goudengids queries
Goudengids placeholders have no NACE observation, so the standard sector filter can't exclude them. When querying goudengids results by sector, **JOIN on `run_log.sector_slug`** (which is set per-run by `RunsRepo.start_run(sector_slug=...)`) and filter on the slug list `[nl_slug, fr_slug]`. See `ui/data.py::fetch_results_for_run` for the canonical pattern.

### Consolidation pass
After each pipeline run `pipeline/consolidate.py` fuzzy-matches placeholder KBOs (`9%`) to real KBOs using `rapidfuzz.fuzz.token_set_ratio` (threshold 80, three passes: name+postal → name+city → name_only@90). Matching placeholder observations are **re-emitted** under the real KBO with `confidence × 0.9`. Originals are never deleted.

### Scoring formula (`scoring/ranking.py`) — LeadScore (data trust)
`overall = 0.5 × completeness + 0.35 × authority + 0.15 × recency`
- **completeness**: fraction of `HIGH_VALUE_FIELDS` with at least one observation.
- **authority**: mean recency-decayed `base_prior(source, field_family)` across populated HVF.
- **recency**: `1 - mean_days_since / 90`, clamped to [0, 1].
Source priors live in `scoring/confidence.py::_PRIORS_TABLE`.
`HIGH_VALUE_FIELDS` in `ranking.py` includes `revenue_2023` and `revenue_2024` — **update these year constants annually**.

### ProspectScore (`scoring/prospect.py`) — commercial fit
Orthogonal to LeadScore. Answers "how likely is this company to be an HV / heavy-industry buyer?"
`overall_prospect = 0.45 × hv + 0.20 × activity + 0.20 × contact + 0.15 × growth`
- **hv_probability**: longest-prefix NACE match against `scoring/hv_prior.py::_HV_PRIORS`. T1 ≥ 0.80 / T2 0.55–0.79 / T3 0.30–0.54 / T4 < 0.30. Unknown prefixes → 0.0 (not 0.5).
- **business_activity**: 1.0 if active status + financial observation; 0.5 if active only; 0.25 if financial only.
- **contact_quality**: mean of three binary signals (phone, email, website).
- **growth_signal**: 0.0 placeholder — populated when growth-signal sources land.
Call `refresh_prospect_scores(pool)` after `refresh_companies_current()`. Never call from a repo method.

## Testing rules — TDD IS ENFORCED BY HOOKS
- Every change to `src/scraper/**` MUST touch `tests/**` in the same turn.
- Tests organised: `tests/unit/`, `tests/integration/`, `tests/golden/` (HTML/JSON/XBRL samples).
- `uv run pytest --cov=src/scraper --cov-fail-under=85` must pass before Stop.
- New scrapers require ≥3 golden HTML samples in `tests/golden/<source>/`.
- Network-hitting tests are marked `@pytest.mark.network` and skipped in CI.
- `asyncio_mode = "auto"` is set in `pyproject.toml` — `async def` tests run automatically; **do not add `@pytest.mark.asyncio`**.
- Integration tests (`@pytest.mark.integration`) create a disposable `leads_test_<timestamp>` DB and require a live Postgres instance. Never run them against the dev `leads` DB.

## Coding conventions
- Type hints everywhere; `mypy --strict`.
- Pydantic v2 only at boundaries (parsed records, API I/O). Internal data: `@dataclass(frozen=True, slots=True)`.
- Pass dependencies explicitly (httpx client, asyncpg pool). No module-level globals.
- `asyncio.TaskGroup` for fan-out, never bare `create_task`.
- `structlog` with `contextvars`; bind `kbo_number`, `source`, `run_id` at outermost scope.
- Errors: typed exceptions in `src/scraper/lib/errors.py`. No bare `except:`.
- HTTP: never `httpx.AsyncClient()` per request — use the pool from `src/scraper/lib/http/`.

## Anti-patterns (never)
- `UPDATE observations SET ...` — observations only, never overwrite canonical facts.
- Synchronous I/O in async paths.
- Auto-retry on 403 — escalate or stop. Retry only on 429/503/504.
- Reimplementing KBO checksum or Belgian phone validation — use `python-stdnum.be.vat` and `phonenumbers`.
- Adding `update` or `delete` methods to `ObservationsRepo`. The repo is intentionally append-only.
- Concurrent goudengids requests. The host's WAF penalises bursts harder than sustained low rate. Always concurrency 1.
- Treating search-engine observations as authority. They are evidence signals (confidence 0.50–0.55), never canonical. Never resolve conflicts by trusting a search hit over KBO/NBB/goudengids.
- NACE codes with dots — KBO Open Data uses dotless codes (`43211`, not `43.21`). `_SECTOR_NACE_PREFIXES` in `orchestrator.py` must match this format.
- Calling `httpx.AsyncClient` directly from a goudengids fetcher — goudengids uses Playwright/Chromium (see `sources/goudengids/fetcher.py`). The old httpx warmup approach is archived in `sources/goudengids/archive/`.

## Per-source knowledge
Skills live under `.claude/skills/<name>/SKILL.md` and load on demand. Don't put per-source detail in this file.
- Polite scraping rules: `.claude/skills/polite-scraping/SKILL.md`
- Provenance schema rules: `.claude/skills/provenance-schema/SKILL.md`
- Belgian phone validation rules: `.claude/skills/belgian-phone-validation/SKILL.md`
- KBO / CBE rules (Open Data + kbopub): `.claude/skills/kbo-lookup/SKILL.md`
- NBB financials rules: `.claude/skills/nbb-financials/SKILL.md`
- Goudengids / pagesdor scraping rules: `.claude/skills/goudengids-listing/SKILL.md`
- Website enrichment rules: `.claude/skills/website-analysis/SKILL.md`
- Search cross-validation rules: `.claude/skills/search-cross-validation/SKILL.md`

Per-host rate limits: `.claude/skills/polite-scraping/references/per-host.toml`.

## Polite scraping
Default 0.5 req/s per host, exponential backoff with jitter on 429/503. Honour Retry-After. Skip on 403.

## Environment variables
| Variable | Used by | Notes |
|---|---|---|
| `DATABASE_URL` | `lib/config.py::load_settings()`, pipeline CLI | Full R/W Postgres URL. Local dev (from `docker compose up -d pg`): `postgresql://leads:leads@localhost:5432/leads` |
| `LEADS_DB_RO_URL` | `.mcp.json` Postgres MCP server | Read-only role for Claude Code queries |
| `BRAVE_SEARCH_API_KEY` | `ddg_brave/brave_client.py`, pipeline CLI `--brave-key` | Optional |
| `NBB_CBSO_API_KEY` | `nbb_authentic/client.py`, pipeline CLI `--nbb-key` | Optional |

## How to run
```
# One-time setup
uv python install 3.12 && uv sync --locked --dev && uv run playwright install chromium
docker compose up -d pg
uv run be-leads-migrate   # apply DB migrations

# Daily dev
uv run pytest -x -q -m "not network and not slow and not integration"   # fastest: unit-only, fail-fast
uv run pytest -m "not network and not integration"      # unit tests only (no DB)
uv run pytest -m "not network"                          # full suite (unit + integration), skip live network
uv run pytest -m integration                            # integration tests only (needs running Postgres)
uv run pytest tests/unit/ui/test_data.py -v             # single file
uv run pytest tests/unit/ui/test_data.py::TestFetchResultsForRun::test_empty_run_returns_empty_list -v  # single test
uv run ruff check . && uv run ruff format --check .
uv run mypy src/scraper
uv run streamlit run src/scraper/ui/app.py   # UI can also launch batch runs (Run Pipeline page → pipeline/batch.py), not just query results

# Pipeline (requires DATABASE_URL)
uv run be-leads-pipeline --sector elektriciens --city antwerpen --use-fixture
uv run be-leads-pipeline --sector elektriciens --city antwerpen --fixture-zip KBO_zip/KboOpenData_*.zip
uv run be-leads-pipeline --sector elektriciens --city antwerpen --skip-kbo-dump --skip-nbb

# Batch pipeline (stage-once; always supply --city and --sector explicitly)
uv run be-leads-kbo-stage KBO_zip/KboOpenData_*.zip          # stage ZIP once (idempotent)
uv run be-leads-kbo-stage KBO_zip/KboOpenData_*.zip --force  # re-stage (deletes old rows first)
uv run be-leads-pipeline-batch --city antwerpen --all-sectors
uv run be-leads-pipeline-batch --city antwerpen --sector elektriciens --sector accountants
# With auto-export (writes leads_part_0001.csv … in the given dir):
uv run be-leads-pipeline-batch --city antwerpen --all-sectors --export-dir ./exports/2026-06-01
# Force re-scrape even if already done this month:
uv run be-leads-pipeline-batch --city antwerpen --all-sectors --goudengids-skip-recent-hours 0
uv run be-leads-cleanup-stage --keep 3                       # delete all but 3 most-recent snapshots
```

Key dedup defaults (prevent monthly re-scraping): `goudengids_skip_recent_hours=720` (30 days),
`ddg_brave_skip_recent_hours=168` (7 days). City lookup via `pipeline/city_map.toml` — e.g.
`--city antwerpen` matches all Antwerp postal codes (Borgerhout, Berchem, Deurne, etc.).

For Hetzner Cloud deployment: see `hetzner/README.md`.

Per-source CLIs (useful for isolated debugging):
```
uv run be-leads-ingest-kbo           # kbo_dump ingester
uv run be-leads-validate-kbo         # validate a single enterprise number (mod-97 checksum)
uv run be-leads-fetch-kbopub         # kbopub HTML scraper
uv run be-leads-fetch-nbb            # NBB CBSO financials
uv run be-leads-discover-goudengids  # goudengids listing (uses Playwright/Chromium)
uv run be-leads-enrich-website       # website enrichment
uv run be-leads-search-validate      # DuckDuckGo + Brave cross-validation
uv run be-leads-validate-phone       # phone validation helper
uv run be-leads-export --out results.csv                     # export all KBOs ranked by overall_prospect
uv run be-leads-export --out results.csv --run-id <uuid>     # restrict to a single pipeline run
uv run be-leads-export --out ./exports/ --chunk-size 5000    # write 5000-row chunk files
```

## Definition of done (every change)
1. Plan written in `.claude/plans/` and approved.
2. Tests added/updated FIRST, failing on the new behaviour.
3. Implementation makes them pass.
4. `ruff check`, `ruff format --check`, `mypy --strict` clean on changed files.
5. `uv run pytest --cov=src/scraper --cov-fail-under=85` passes.
6. CHANGELOG entry added (Keep a Changelog format — add under `## [Unreleased]`).
