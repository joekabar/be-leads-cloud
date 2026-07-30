# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed — Phase D/E/F failures were discarded, hiding three nights of dead prospect scores

- `batch.py` wrapped the matview refreshes, consolidation and prospect scoring in
  `with suppress(Exception)`. The 2026-07-30 nightly run therefore logged `phase_f_started`,
  **no** `phase_f_finished`, and `prospect_scores=0` inside an otherwise clean
  `batch_finished` — after spending 7m19s on the phase. `max(prospect_scores.computed_at)`
  had been stuck at **2026-07-27**: the scores that rank every export were three days stale
  and nothing reported it.
- Phases A, C1, C2 and G in the same file already used `try/except` →
  `report.sources_failed[...]` + `log.error(...)`. D/E/F now do the same. Failure stays
  non-fatal — a blocked scrape must not also cost the night's consolidation — but it is no
  longer silent. Keys: `matview_refresh_pre_consolidation`, `consolidation`,
  `matview_refresh`, `prospect_scores`.
- Failures record the exception **type** as well as its message, via `_describe()`:
  `str(MemoryError())` is the empty string, and MemoryError is the leading hypothesis for
  the production failure (Phase F holds 8.7M fetched rows plus ~2M dicts alongside
  Chromium). `batch_finished` now carries `failed=[...]` so a partial run cannot read as a
  clean one.
- Phase F is **not** broken in isolation: reproduced against the live DB it fetched
  8,743,514 rows in 28.6 s, scored 1,959,773 KBOs, and upserted 392 batches — slowest batch
  0.47 s, total 1.9 min, no timeout and no malformed JSONB. The production exception remains
  unidentified precisely because it was suppressed; this change is what will name it.

### Fixed — nightly_scrape.ps1 exited 1 on successful runs and never wrote its summary

- `& uv @argList *>> $log` ran under `$ErrorActionPreference = 'Stop'`. Windows PowerShell
  5.1 wraps every stderr line from a native exe in a `NativeCommandError` record, which that
  preference makes **terminating** — so the script died at the call and never reached the
  lines that record the exit code, the sector/block counts, or the `END` marker.
  `logs/nightly_scrape.log` shows `START` and `SCRAPE` for the 02:30 run but no `END`, while
  the batch log shows a clean `batch_finished`; Task Scheduler recorded `LastTaskResult = 1`.
- structlog writes all logging to stderr, so this fired on **every** run, not on failures
  only — the script had never once written its summary.
- The call is now bracketed by `$ErrorActionPreference = 'Continue'` restored in a `finally`.
  Verified with a standalone harness: a child writing to stderr and exiting 7 now yields
  `END exit=7` and propagates 7, where the old pattern wrote no `END` and exited 1.

### Fixed — scheduled exports silently wrote to the wrong drive location

- Both scheduler scripts computed their output directory from `$PSScriptRoot` **in a
  `param()` default**. Under `powershell.exe -File` from Task Scheduler that variable can be
  empty, so `$OutDir` became `\..\exports` and every scheduled export landed in `C:\exports`
  instead of the repo's `exports\`. The task reported **exit code 0**, so the failure was
  completely invisible: the scheduled run at 22:00 succeeded while the repo folder and its
  log had not changed since 14:40.
- Both scripts now resolve the repo root from `$PSCommandPath` in the script body, with
  `$MyInvocation.MyCommand.Path` as a fallback, and only then derive `exports\` / `logs\`.
  Verified under the exact scheduler invocation: output goes to the repo, and the stray
  `C:\exports\daily_export.log` is no longer touched.
- `scripts/nightly_scrape.ps1` also documents that it must stay pure ASCII: Windows
  PowerShell 5.1 reads a BOM-less UTF-8 script as ANSI, and a mangled multi-byte character
  inside a string breaks the parser (an em-dash made the first version fail to parse).


### Added — nightly chunked scraping (`be-leads-next-sectors`)

- goudengids' Imperva WAF blocks on sustained volume, not request rate alone. A 103-sector
  run served 8 sectors in ~30 min, then blocked **15 of the next 21** (71%). Scraping a
  small slice per night keeps each session under that threshold.
- **`pipeline/sector_queue.py`** — `select_pending_sectors()` returns the next N sectors a
  city still needs, preserving config order so the rotation covers everything once before
  repeating. `completed_sectors()` counts a sector as done only when it produced
  observations (`jobs_done > 0`): a blocked run reached the WAF, not the data, so treating
  it as done would skip that sector forever.
- **`be-leads-next-sectors --city X --limit N`** prints the pending slugs, or nothing when
  the city is fully covered so the caller can skip the night. `--cycle` restarts the
  rotation for a city that should be refreshed continuously.
- **`scripts/nightly_scrape.ps1`** — asks for the night's slice and scrapes only those
  sectors, skipping `kbo_dump` since staging is already loaded.


### Performance — Phase B refreshed the materialised view once per sector

- `goudengids/ingester.py` ran `refresh_companies_current()` in a `finally` block after
  **every sector**. That rebuild is a `DISTINCT ON` over ~8.7M observation rows and costs
  ~130 s, so a 103-sector batch paid for 103 of them. Measured live: a sector that found
  **zero** cards still took 161.8 s, nearly all of it the refresh.
- Nothing in a batch reads `companies_current` until Phase D (consolidate). The ingester
  now takes `refresh_matview: bool = True` — default preserved so the standalone
  `be-leads-discover-goudengids` CLI still leaves the view consistent — and `batch.py`
  passes `False`, refreshing exactly once before Phase D.
- Six other ingesters refresh the view the same way; only goudengids is fixed here because
  only it runs per-sector in a loop. This also contradicts `CLAUDE.md`, which states the
  view is refreshed *after each pipeline run*.

### Added — explicit pause between Phase B sectors

- The per-sector refresh was, by accident, the only thing pacing Phase B: it sat between
  one sector's last request and the next sector's first. Removing it would make requests
  arrive **faster** and trip the Imperva WAF sooner, so `BatchConfig.goudengids_sector_pause_s`
  (default 120 s) replaces it as deliberate rate control.
- Observed live on 2026-07-29: goudengids served 8 sectors over ~30 min, then blocked every
  subsequent sector on page 1. The ingester correctly aborts on a block rather than
  retrying, per the project's no-retry-on-403 rule.

### Fixed — cards_out_of_city was counted but never logged

- The city filter tracked `GoudengidsReport.cards_out_of_city` but omitted it from the
  `goudengids_ingest_finished` log line, so a thin run could not be explained from the
  batch log — exactly when the number matters. Now logged.


### Fixed — city_slug was not case-normalised, forking one city into two histories

- `run_log` holds both `oostende` (31 runs) and `Oostende` (11 runs) for the same city:
  `build_batch_config` stripped the value but never lower-cased it. Everything that matches
  on `city_slug` does so case-sensitively, so the two spellings behaved as different cities.
- Impact: `batch.py`'s Phase C2 scope query missed runs recorded under the other casing, so
  those companies never got search validation; and the goudengids `skip_recent` dedup keyed
  on the same column, so a differently-cased run looked new and got re-scraped — at
  concurrency 1 against a WAF, the most expensive mistake the pipeline can make.
- `get_postal_codes` already lower-cased its argument, which is why city resolution kept
  working and hid the split.
- Fixed at the entry point (`city.strip().lower()`); the Phase C2 query now compares
  `lower(city_slug) = lower($1)` so the already-split historical rows are matched too.


### Added — targeted lead exports (city / required field / revenue ceiling)

- `be-leads-export` could only export **everything** (1.96M KBOs) or a single `--run-id`,
  neither of which answers "small businesses in this city that have a phone" — the normal
  shape of a lead request. New `--city SLUG` (repeatable), `--require-field FIELD`
  (repeatable, all must match) and `--max-revenue N`.
- Filtering happens in the selection SQL (`build_selection_sql`), not in Python after the
  fetch, because the unfiltered set is 1.96M KBOs.
- `--max-revenue` excludes only companies with a **published** revenue above the ceiling.
  Companies with no revenue on file are kept: micro enterprises file abbreviated accounts
  and legitimately publish no turnover, so dropping them would remove most of a
  small-business list.
- An unknown `--city` slug raises rather than resolving to "no postcodes", which would have
  silently widened the export from one city to the whole country.
- **`scripts/daily_export.ps1`** — date-stamped export driven by a Windows Scheduled Task,
  with logging and retention pruning.

### Fixed — status was blank everywhere, silently disabling the active-company filter

- `ui/data.py::_aggregate_row` read `status["text"]`, but both kbo_dump producers write
  `status = {"value": "active"}` — the same defect already fixed in
  `scoring/prospect.py::_business_activity` and missed here. All 1,948,404 status rows in
  `companies_current` are `{"value": "active"}`, so the column was empty in **every** CSV
  export and in the UI results table.
- The worse half: `_passes_filters` treats an empty status as "unknown, keep" (missing
  values pass). Because status was *always* empty, the `active_only` filter matched
  everything — dissolved companies passed a filter meant to exclude them. Now reads
  `value`, with `text` kept as a fallback.

### Added — the UI checks the database is reachable before starting a run

- A stopped Postgres previously surfaced as a raw `WinError 1225` from inside the batch
  daemon thread, minutes into a run that was never going to work. `db/pool.py::check_reachable`
  now preflights the connection and `_friendly_db_error` maps the failure to an actionable
  message ("Start Docker Desktop, then run `docker compose up -d pg`"). Wired into both entry
  points: `ui/app.py` before the sector loop and `ui/pages/run_pipeline.py` before
  `start_async_job`.
- The timeout is passed **natively** to `asyncpg.connect` rather than wrapping the call in
  `asyncio.wait_for` — the same precedent as the staging COPY and prospect upsert fixes, since
  cancelling asyncpg from outside makes it take its generic cancel path, which can hang on the
  very socket this preflight exists to test.
- `ui/app.py` also had a fall-through bug: when `DATABASE_URL` was unset it rendered an error
  and then **continued into the sector loop anyway**. It now stops. `ui/pages/run_pipeline.py`
  resolved the DSN with a raw `os.environ` read — the same bug already fixed in `app.py` — and
  now goes through `lib/config.py::database_url()`, which loads `.env` from the project root.

### Fixed — Phase F wedged on an unbounded prospect_scores upsert

- `scoring/prospect.py::refresh_prospect_scores` sent every score in **one**
  `pool.executemany` — ~1.96M parameter tuples materialised in a single Python list.
  A UI-launched batch wedged there for 25+ minutes: Postgres in
  `state=active`/`wait_event=ClientRead`, the client at 0% CPU holding 4.3 GB, no
  blocking locks. Being unbounded, the call also had no timeout, so it hung
  indefinitely rather than failing. The identical operation had taken 110 s on earlier
  runs, so it was stuck, not slow.
- The upsert is now sent in bounded batches (`_chunked`, 5,000 rows) on a single
  acquired connection, each with a native asyncpg `timeout=`. Following the precedent
  from the staging COPY fix, the timeout is passed **into** asyncpg rather than wrapping
  the call in `asyncio.wait_for`: cancelling from outside makes asyncpg take its generic
  cancel path, which needs the same wedged socket and can hang in turn. A batch that
  exceeds its ceiling raises the new `ScoringTimeoutError`.
- Verified against the same 1.96M-row production database that had just wedged:
  **1,959,502 KBOs in 392 batches, 147.6 s.** No data was lost by the wedge — the
  uncommitted upsert rolled back and all 1,959,506 rows remained intact.

### Fixed — consolidation redid all its work on every run

- `pipeline/consolidate.py` re-matched **every** placeholder in the database on every
  run and re-emitted the observations of every match again. Two consecutive production
  runs both logged `matches=2797, observations_re_emitted=43466` — the same ~43k rows
  inserted a second time into an append-only table — after ~40 min of single-threaded
  rapidfuzz matching that grows with each goudengids discovery.
- New `consolidation_state` table (migration `008`) records every processed placeholder:
  `real_kbo` set on a match, NULL on a non-match, tagged with the KBO `snapshot_date`
  the attempt was made against. `select_placeholders_to_process()` then skips matched
  placeholders permanently (their observations already exist) and retries unmatched ones
  only once a **newer snapshot** is staged — the only thing that can turn a previous
  non-match into a match. `consolidate(..., force=True)` reprocesses everything.
- Steady-state consolidation is now proportional to *new* placeholders rather than the
  whole population. Integration-tested against a real DB: a second run returns no
  matches and adds no observations.
- `tests/integration/conftest.py::clean_pool` now truncates `consolidation_state`.
  Without it, a placeholder left by an earlier test is skipped as "already processed"
  and the next test silently sees zero matches — which is exactly how it first failed.

  Note: the first run after this change still does one full pass (the state table starts
  empty) and re-emits duplicates one last time; every run after that is incremental.
  Existing duplicate observations from previous runs are left in place — nothing is deleted.

### Added — manual NACE codes in the search parameters

- **`src/scraper/lib/nace.py`** (new) — `parse_nace_input` / `normalize_nace`. Accepts the
  dotted form copied from official tables (`43.21`) as well as KBO's dotless form, split on
  commas/semicolons/whitespace, deduplicated and order-preserving. A single bad entry raises
  the new `InvalidNaceError` rather than being silently dropped, so a typo cannot quietly
  narrow a search.
- **`BatchConfig.extra_nace`** + `batch.py::resolve_nace_prefixes(sectors, extra_nace)` — the
  Phase A staging filter is now the union of sector-mapped prefixes and manually entered
  codes. Entering a code a sector already covers does not duplicate the `LIKE ANY` pattern.
- **UI** — "Extra NACE codes (optional)" on the batch run page; **Sectors may be left empty**
  when codes are supplied (`resolve_sectors(..., allow_empty=True)`), making a NACE-only
  search possible. Same via `be-leads-pipeline-batch --nace CODE` (repeatable).

### Fixed — goudengids ignored the requested city

- goudengids serves a **nationwide** result list when a sector is thin locally, and those cards
  were stored under a run tagged with the requested city — silently mislabelling out-of-area
  leads. Every card carries a postal code even when its city name is blank, so
  `ingester.card_in_city()` now scopes results by postcode. Out-of-area cards are counted in
  the new `GoudengidsReport.cards_out_of_city` (and the CLI JSON) rather than dropped
  invisibly, so a thin run is explainable. An unmapped city disables filtering rather than
  discarding the whole run.
  Verified live: `kappers x antwerpen` keeps 34 of 40 cards (6 dropped; every kept card in an
  Antwerp postcode 2000-2610), while `tuinaanleggers x oostende` drops all 16 — goudengids has
  no Oostende results for that sector at all.
- **`pipeline/city_map.py`** — `get_postal_codes` now falls back to `lib/postcodes.toml`.
  The two city sources had drifted: the UI picker lists 16 cities from postcodes.toml while
  city_map.toml has 15, so Oostende resolved to `None` and silently disabled city filtering
  (observed live as `goudengids_city_not_in_postcode_map`). Curated city_map entries still win.

### Fixed — business_activity was 0.0 for every company in the database

- `scoring/prospect.py::_business_activity` read `status["text"]`, but both kbo_dump producers
  write `status = {"value": "active"}`. `is_active` was therefore always False, pinning
  `business_activity` at 0.0 for all 1.9M companies and zeroing 20% of the prospect score.
  The pre-existing tests all used the `"text"` shape — which no producer emits — so they
  passed while production was wrong. Now reads `value`, with `text` kept as a fallback.
  After rescoring: business_activity 0.5 for 1,941,153 KBOs and 1.0 for 7,250 (previously 0.0
  for all 1,959,468). Sample lead 0738550377 moved 0.200 -> 0.300 overall.

### Fixed — the UI could not show a completed batch run

- The search page rendered results only from `st.session_state`, so a batch finished on the
  CLI or in another browser session was invisible — the only way to see leads that already
  existed was to re-run the whole pipeline. Added `ui/data.py::fetch_completed_runs` and a
  "Load a completed run" control that replays any finished sector x city run through the same
  `fetch_results_for_run` path, so loaded results are indistinguishable from a live run.
  Only runs with an `ended_at` and both a sector and city are offered.
- `ui/app.py` resolved `DATABASE_URL` with a raw `os.environ` read that executes *before*
  anything loads `.env`, yielding `""` on the first click and silently skipping the results
  fetch. Now goes through the new `lib/config.py::database_url()`, with `.env` located from
  the **project root** (`project_root()`) instead of the working directory.
- A NACE-only run writes `sector_slug` NULL, so requiring a sector hid exactly the searches
  the new NACE input makes possible. `fetch_completed_runs` now requires only a city, and the
  picker labels such runs "NACE-only x <city>".
- `fetch_results_for_run` gained an optional `run_id`, used by the load path. Discovery
  previously fell back to "every company whose address city matches" when no sector was
  given — for Antwerpen that is tens of thousands of companies aggregated in Python, and the
  page hung. Scoping by `run_id` is exact and returned 135 companies in ~12 s. The live-run
  path (no `run_id`) is unchanged.

### Added (UI-first operation: server + local goudengids)

- **`src/scraper/ui/pages/run_pipeline.py`** — new Streamlit page to trigger the production **batch** pipeline from the browser (city × sectors, per-source toggles, dedup windows, optional export dir). Runs `run_batch` in a daemon thread; progress shows on the existing KBO Data → Live Progress tab.
- **`src/scraper/ui/run_config.py`** — `build_batch_config(...)`: pure, Streamlit-free mapping of UI inputs → `BatchConfig`, with sector validation against `_SECTOR_NACE_PREFIXES` (unknown slug / empty city raise `ValueError`).
- **`src/scraper/ui/batch_runner.py`** — `run_batch_job(dsn, config)`: wires an asyncpg pool + `PoliteClient` around `run_batch` (mirrors `batch_cli._run`) for launch from the UI.
- **`src/scraper/ui/background.py`** — shared `start_async_job` / `poll_job` helpers (daemon thread + result queue) for long-running async work in Streamlit, extracted from the staging pattern in `pages/kbo_data.py`.
- **`hetzner/docker-compose.prod.yml`** — new long-running `ui` service (Streamlit, `restart: unless-stopped`) published on the server loopback (`127.0.0.1:8501`); KBO ZIP volume mounted at `/app/KBO_zip` so the staging tab finds them. Postgres now also published on the server loopback (`127.0.0.1:5432`) so a laptop can reach it via SSH tunnel.
- **`hetzner/scripts/tunnel-db.ps1`, `tunnel-ui.ps1`, `run-ui-local.ps1`** — laptop-side PowerShell helpers: open SSH tunnels to the remote DB / UI, and launch the local UI pointed at the remote DB.
- **`hetzner/README.md`** — new sections "Running the UI on the Server" and "Running Goudengids Locally (Imperva workaround)".

### Fixed (goudengids)

- **`_BLOCKED_PHRASES`** now includes `_incapsula_resource`, so Imperva/Incapsula challenge pages are detected as blocks (the datacenter IP receives these instead of listings).

### Added (unattended pipeline runs)

- **`hetzner/scripts/run-pipeline.sh`** — wrapper that launches `be-leads-pipeline-batch` detached (`docker compose run -d`) so the run survives SSH disconnect / closing the laptop. Injects a date-stamped `--export-dir` automatically. Prints container id and the exact commands to follow logs and verify completion.
- **`hetzner/README.md`** — new "Running Unattended" section documenting the script, how to follow logs after reconnecting, and how to clean up stopped containers.

### Added (Hetzner cloud deployment)

- **`Dockerfile`** — multi-stage build (`python:3.12-slim` builder + `playwright/python:v1.59.0-jammy` runtime). Pins `uv==0.6.17`, installs `playwright==1.59.0` into the venv, creates non-root `app` user, healthcheck via `be-leads-validate-kbo`.
- **`.dockerignore`** — excludes tests, `.venv`, `KBO_zip`, `.env`, `.claude`, screenshot artefacts from build context.
- **`hetzner/docker-compose.prod.yml`** — production compose with `pg`, `migrate`, `pipeline`, `kbo-stage` services. Postgres on internal network only; host-mounted volumes for exports, KBO ZIPs, and logs.
- **`hetzner/.env.example`** — environment template with all required variables.
- **`hetzner/README.md`** — deployment runbook: server sizing (CCX23 16 GB), first-time setup, KBO staging, pipeline execution, monthly refresh, CSV retrieval, backup guidance.
- **`hetzner/scripts/monthly-stage.sh`** — executable helper to stage a new KBO ZIP and clean old snapshots.
- **`hetzner/crontab.example`** — optional cron entry for monthly KBO staging (pipeline runs remain manual).

### Added (CSV export)

- **`export_csv` chunk mode** — new `chunk_size: int = 0` parameter. When `> 0`, writes `leads_part_0001.csv`, `leads_part_0002.csv`, … into a directory instead of a single file. Returns `list[Path]`.
- **`be-leads-export --chunk-size N`** — CLI flag for chunked export (default 0 = single file).
- **`be-leads-pipeline-batch --export-dir PATH`** — auto-exports after Phase F (prospect scoring) into 5 000-row chunk files. No export when omitted.
- **`be-leads-pipeline-batch --export-chunk-size N`** — configures chunk size for auto-export (default 5 000).

### Added (city postal-code lookup)

- **`src/scraper/pipeline/city_map.toml`** — lookup table mapping 15 Belgian city slugs to their postal code lists (Antwerpen, Gent, Brussel, Liège, Charleroi, Brugge, Namen, Leuven, Mechelen, Hasselt, Kortrijk, Mons, Aalst, Sint-Niklaas, Ghent alias).
- **`src/scraper/pipeline/city_map.py`** — `get_postal_codes(city_slug)` lazy-loads the TOML and returns the postal code list or `None` for unknown cities.
- **`get_entity_filter`** in `batch.py` — now queries `zipcode = ANY(postal_codes)` for known cities; falls back to `municipality_nl/fr` name match for unknown slugs. Ensures `--city antwerpen` captures Borgerhout, Berchem, Deurne, etc.

### Changed (dedup / no double scraping)

- **`goudengids_skip_recent_hours`** default raised from `0` to **`720`** (30 days). Monthly re-runs skip sectors already scraped within the last month. Override with `--goudengids-skip-recent-hours 0`.
- **`ddg_brave_skip_recent_hours`** default raised from `0` to **`168`** (7 days). Override with `--ddg-brave-skip-recent-hours 0`.
- **`db/migrations/006_observations_dedup_index.sql`** — `ix_observations_source_kbo_recent` index on `(source, kbo_number, observed_at DESC)` speeds up the `skip_recent_hours` look-ahead query at scale.
### Performance (kbo_dump staging — multi-core parse + UNLOGGED tables + no raw_row)

Speeds up `be-leads-kbo-stage` (the local ZIP→staging step) from ~7.5 min to ~5.5 min on the
full 1.5 GB dump (43.5M rows). Previously the 5 CSV passes ran in an `asyncio.TaskGroup` but,
being synchronous CPU-bound parse loops, executed on a single core; every row also paid a
`json.dumps` for the `raw_row` column, and COPY maintained all secondary indexes per row on
WAL-logged tables.

**`db/migrations/007_kbo_stage_optim.sql`** (new)
- `SET UNLOGGED` on all 5 `kbo_stage_*` tables — skips WAL for the bulk load (re-stageable, so
  crash-safety is unneeded; tables are TRUNCATEd on unclean Postgres restart → just re-stage).
- `DROP COLUMN raw_row` — it duplicated the typed columns and cost a `json.dumps` per row
  (~14M/run) for a schema-drift net that never fired.

**`sources/kbo_dump/staging.py`** (rewrite)
- Parses the 5 CSVs in a `ProcessPoolExecutor` (true multi-core). Workers stream escaped rows
  to a temp TSV file and return `(path, row_count)` — O(1) worker memory, path-only IPC. The
  `executor` arg is injectable so tests run in-process.
- `activity.csv` (34.7M rows, the long pole) is decompressed once and parsed across cores via
  line-aligned byte-range shards, with a single-worker fallback. Activity parse ~314s → ~146s.
- Drops `kbo_stage_*` secondary indexes before the load and recreates them after.
- One COPY per table (no per-batch connection churn); no per-row JSON.
- Real schema-drift detection: `_detect_drift` reads each CSV header and logs
  `kbo_schema_drift_detected` with the new column names (the old `_check_drift` was dead code —
  it compared against an empty column set and never fired).

**`sources/kbo_dump/parser.py`**
- `read_csv_header(zip_path, csv_name)` + `extract_member(zip_path, csv_name, dest)` — CSV header
  for drift detection and one-pass decompression for parallel activity parsing.

**`sources/kbo_dump/stage_cli.py`**
- Pool `max_size` 5 → 12 for the concurrent table + activity-shard COPYs.

### Performance (pipeline — stage-once KBO batch + epoch-level consolidation/scoring)

Eliminates the biggest sources of wall-time waste: re-parsing the 1.5 GB ZIP per sector,
running consolidation/scoring after every sector, and leaving kbopub/nbb/website idle during
the goudengids loop. Target: ~1.5 h for a 95-sector all-sectors batch vs. ~12 h previously.

**`db/migrations/004_kbo_stage.sql`** (new)
- 5 staging tables (`kbo_stage_enterprise`, `kbo_stage_address`, `kbo_stage_denomination`,
  `kbo_stage_contact`, `kbo_stage_activity`) keyed by `entity_number + snapshot_date`.
- `raw_row JSONB` on each table for forward-compatible schema-drift handling.
- Indexes: entity_number, snapshot_date, composite city (lower municipality_nl/fr), NACE prefix.

**`db/migrations/005_pipeline_progress.sql`** (new)
- `pipeline_progress` mutable telemetry table (one row per run) for live UI progress reporting.

**`sources/kbo_dump/staging.py`** (new)
- `stage_zip(zip_path, pool, *, force=False, progress=None)` — streams all 5 CSVs once into
  staging tables via concurrent `asyncio.TaskGroup`. Idempotent by snapshot_date; `force=True`
  deletes and re-inserts. Logs `kbo_schema_drift_detected` on unknown CSV columns.
- `cleanup_old_snapshots(pool, keep_n)` — deletes all but the N most-recent snapshots.

**`pipeline/progress.py`** (new)
- `ProgressReporter(pool, run_id)` with `async report(phase, stage, ...)` — upserts into
  `pipeline_progress` for live UI monitoring.

**`pipeline/batch.py`** (new)
- `BatchConfig` + `run_batch(config, pool, polite_client)` — epoch-aware orchestrator.
- Phase A: DELETE old snapshot obs, filter entities from staging tables by city + NACE union,
  bulk-COPY observations using existing transformer functions.
- Phase B/C1 overlap: goudengids loop (sequential, WAF-bound) runs concurrently with
  kbopub_html + nbb_authentic + website enrichers in one `asyncio.TaskGroup`.
- Phase C2: ddg_brave after Phase B (needs all placeholders).
- Phases D/E/F: single consolidation → single matview refresh → single prospect scoring pass.

**`pipeline/batch_cli.py`** (new): `be-leads-pipeline-batch --city X [--sector S | --all-sectors]`

**`sources/kbo_dump/stage_cli.py`** (new): `be-leads-kbo-stage <zip_path>` one-time ingest CLI.

**`sources/kbo_dump/cleanup_cli.py`** (new): `be-leads-cleanup-stage --keep N`.

**`pipeline/orchestrator.py`** (extended)
- Added `recyclagebedrijven-industrieel` and `transportbedrijven-zwaar` to `_SECTOR_NACE_PREFIXES`.

**`ui/pages/kbo_data.py`** (new) — "KBO Data Management" Streamlit page with 5 tabs:
- Available ZIPs (stage button with background thread + live queue polling)
- Staged Snapshots (row counts per table, force re-stage button)
- Live Progress (auto-refresh from `pipeline_progress` table)
- Cleanup (keep-N slider + run button)
- New Leads diff view (since-date or between-two-snapshots modes, CSV export)

**`ui/queries/snapshots.py`** (new) — DB query helpers used by the KBO Data Management page.

Tests added:
- `tests/unit/kbo_dump/test_staging.py` — pure-Python tests for `_pg_text_escape`, `StagingReport`.
- `tests/unit/pipeline/test_batch.py` — `BatchConfig`, `_resolve_goudengids_slug`, `BatchReport`.
- `tests/unit/pipeline/test_sector_nace.py` — updated to use section keys (not nl_slug values).
- `tests/integration/pipeline/test_batch_e2e.py` — 9 integration tests covering: staging
  idempotency, force re-stage, observations inserted, no-duplicate re-run, scoring, cleanup,
  missing-staging error, unknown-city zero-result.



### Phase 0: Industrial sector expansion + HV-tier prospect scoring

Adds a `ProspectScore` alongside `LeadScore` — orthogonal signals answering "how commercially
interesting is this company to Saive?" vs. "how well do we know it?".

**`scoring/hv_prior.py`** (new)
- `_HV_PRIORS` dict: 100+ NACE prefixes → HV-probability in [0,1], organised into T1–T4 tiers.
- `hv_probability(nace_codes)`: longest-prefix match returning max probability across all codes.
  Unknown prefixes contribute 0.0 (not a default 0.5) — uncovered sectors are not prioritised.

**`scoring/prospect.py`** (new)
- `ProspectScore` frozen dataclass: `hv_probability`, `business_activity`, `contact_quality`,
  `growth_signal`, `overall_prospect` (all ∈ [0,1]).
- Weights: `0.45·hv + 0.20·activity + 0.20·contact + 0.15·growth`. `growth_signal = 0.0` Phase 0.
- `refresh_prospect_scores(pool)`: reads `companies_current`, scores every KBO, bulk-upserts to
  `prospect_scores` plain table via `INSERT … ON CONFLICT DO UPDATE`. Returns count of upserted rows.

**`db/migrations/003_prospect_scores.sql`** (new)
- Plain table (not matview) with `NUMERIC(7,6)` score columns and `computed_at TIMESTAMPTZ`.
- Plain table required because the Python longest-prefix-match cannot be expressed in SQL.

**`pipeline/orchestrator.py`** (extended)
- Added ~15 T1–T4 industrial sector slugs to `_SECTOR_NACE_PREFIXES`: energy, chemicals, pharma,
  steel, automotive, water/sewage, food, waste, hospitals, ports, logistics, construction, etc.
- Goudengids step skips gracefully (logs `goudengids_skipped_kbo_only_sector`) when sector slug
  is not in `sectors.toml` — KBO-only industrial sectors don't trigger a ValueError.
- Calls `refresh_prospect_scores` after each `refresh_companies_current` run.

**`ui/data.py`** (extended)
- Bulk-fetches `overall_prospect` from `prospect_scores` and merges into result rows.
- Sort order updated: `overall_prospect DESC` primary, `score_overall DESC` secondary.

**`ui/export.py`** (new) + `pyproject.toml` entry `be-leads-export`
- `export_csv(pool, out_path, *, run_id=None) -> int`: ranked CSV export of all KBOs.
- Columns: kbo_number, name, postal_code, city, nace_code, tier (T1–T4), phone, email, website,
  status, founding_date, revenue_2023, revenue_2024, employees_2024, score columns.
- Sorted by `overall_prospect DESC`. NULL fields become empty string.
- CLI: `uv run be-leads-export --out leads.csv [--run-id <uuid>]`.

### Performance (pipeline — wave-based parallelism + consolidation speedup)

Reduced wall-clock pipeline time by ~30% on a real `elektriciens × oostende` run
(1592 s → projected ~710 s for source phase) without changing the politeness policy.

**Wave-based orchestrator** (`src/scraper/pipeline/orchestrator.py`)
- Replaced six sequential source blocks in `run_pipeline` with two `asyncio.TaskGroup` waves.
  Wave A: `kbo_dump || goudengids`. Wave B: `kbopub_html || nbb_authentic || website || ddg_brave`.
- Each wave is a hard barrier — Wave B starts only after both Wave A tasks complete.
- Each source extracted into a `_run_<name>` coroutine that catches all exceptions internally,
  so a failure in one Wave B source cannot cancel its siblings.
- `HostLimiter` already enforces per-host rate + concurrency limits independently for every
  host, so running sources in parallel across different hosts does not violate the politeness policy.

**Consolidation speedup** (`src/scraper/pipeline/consolidate.py`)
- Pre-built `postal_index` and `city_index` (`dict[str, list[_KboInfo]]`) once before the
  placeholder loop — Pass 1 and 2 are now O(1) bucket lookups instead of O(N) list scans.
- Pass 3 (name-only) uses `rapidfuzz.process.extractOne` with `score_cutoff=90.0` — the C
  inner loop releases the GIL, ~10-50x faster than the previous Python for-loop over 1.9 M reals.
- Matching loop runs in `asyncio.to_thread` so the event loop stays responsive during the
  CPU-bound phase (~591 s previously).

Tests added:
- `tests/unit/pipeline/test_consolidate.py` — `TestBestMatchWithIndexes`: verifies index
  path produces identical results to baseline across all existing scenarios.
- `tests/integration/pipeline/test_orchestrator.py` — `test_wave_b_starts_after_wave_a_completes`,
  `test_wave_b_failure_does_not_cancel_siblings`, `test_sources_run_recorded`.

### Fixed (NBB ingester — transient errors abort entire source)

`RetriesExhaustedError` and `TransientServerError` from a single KBO (e.g. NBB returning
5xx for some companies) propagated uncaught through `ingest_kbos`, causing the entire
`nbb_authentic` source to be marked failed in the pipeline report.

- `ingester.py` — both exceptions are now caught per-KBO; the KBO is logged as a warning
  and skipped; the batch continues. A new `kbos_transient_error` counter on `NbbReport`
  tracks how many KBOs hit this path.
- `tests/unit/sources/nbb_authentic/test_ingester.py` — new file with 4 unit tests
  covering: transient error on references (skipped, counter incremented), auth error
  re-raised, not-found counted, transient error on PDF fetch (KBO still counted as processed).

### Fixed (NBB integration tests — PDF mock path)

Integration tests in `tests/integration/sources/nbb_authentic/` mocked the old JSON-based
`/accountingData` path.  Since the ingester now fetches PDFs via `AccountingDataURL`, the
mock was returning no data and `observations_inserted` was always 0.

- `conftest.py` — `nbb_side_effect` now injects `accountingDataURL` into every reference
  (pointing to `/authentic/deposit/{ref}/accountingData`) and returns the MICRO golden PDF
  for all PDF fetches.  The old accounting-JSON path is removed.
- `test_ingester.py` — observation counts updated to match MICRO PDF output (2 obs per
  reference: `revenue_YYYY` + `profit_YYYY`; no `employees_YYYY` since MICRO filings don't
  disclose headcount).
- `test_cli.py` — `observations_inserted` assertion updated from 9 → 6.

### Fixed (ruff / mypy — pre-existing lint errors)

- `kbopub_html/parser.py` — moved `from datetime import date` and `from typing import Literal`
  above the module-level `_FOOTNOTE_RE` regex (E402).
- `nbb_authentic/parser.py` — simplified if-else to ternary in `_parse_belgian_number` (SIM108).
- `ui/theme.py` — replaced EN DASH with hyphen in score range comment (RUF003).
- `ui/app.py` — annotated `last_report: object = None` to eliminate `no-redef`; added
  `PipelineReport` import for the `_fetch` closure parameter; removed stale
  `# type: ignore[arg-type]` on `render_diagnostics` call.

### Fixed (NBB CBSO — PDF-based accounting data extraction)

**Root cause:** The NBB `/accountingData` endpoint returns `application/pdf`, not JSON.
The original code expected a JSON response with keys like `code_700`, `code_70`, etc.
This resulted in a silent 415 or 404 on every call — no financial data was ever stored.

**Fix:**
- `NbbClient.get_accounting_pdf(accounting_data_url)` — new method; fetches the annual
  accounts PDF using `Accept: application/pdf` and returns raw bytes.  Old
  `get_accounting_data()` kept for unit-test compatibility (marked legacy).
- `parse_accounting_pdf(reference, pdf_bytes)` in `parser.py` — extracts Belgian GAAP
  codes from the PDF via pdfminer positional layout (`LTTextLine` Y-coordinate matching).
  Codes extracted: `700`/`70` (revenue), `9904` (profit/loss), `9087`/`9086` (employees).
  Falls back to `9900` (Brutomarge / gross-margin) when codes `700`/`70` are absent
  (common in MICRO and some ABBREVIATED filings).
- `ingester.py` — now calls `get_accounting_pdf` + `parse_accounting_pdf` per reference;
  skips references with no `accounting_data_url`.
- `ReferenceRow` — new field `accounting_data_url: str = ""` populated from
  `AccountingDataURL` in the live API response.
- `parse_references` — captures `AccountingDataURL` (live PascalCase) and
  `accountingDataURL` (legacy camelCase) into `ReferenceRow.accounting_data_url`.

**Tests added (`tests/unit/sources/nbb_authentic/test_parser.py`):**
- `test_parse_references_live_accounting_data_url_captured` — URL preserved from live format.
- `test_parse_references_camelcase_accounting_data_url_missing_gives_empty` — legacy fixtures default to `""`.
- `test_parse_accounting_pdf_micro_profit_loss` — MICRO filing: `9904 = -25390`.
- `test_parse_accounting_pdf_micro_revenue_uses_brutomarge_proxy` — MICRO: no code 70 value, falls back to `9900 > 0`.
- `test_parse_accounting_pdf_micro_no_employees` — MICRO: `employees_fte is None`.
- `test_parse_accounting_pdf_abbreviated_profit_loss` — ABBREVIATED: `9904 = 2021`.
- `test_parse_accounting_pdf_abbreviated_revenue` — ABBREVIATED: `9900 = 77137`.
- `test_parse_accounting_pdf_empty_bytes_returns_all_none` — bad bytes → all None, no crash.

**Golden PDF fixtures added:**
- `tests/golden/nbb_authentic/0439401387_pdf_2024-00290653.pdf` (MICRO, m87-f, 53 KB)
- `tests/golden/nbb_authentic/0439401387_pdf_2019-35100012.pdf` (ABBREVIATED, m07-f, 51 KB)

### Fixed (NBB CBSO — `parse_references` format mismatch)

The live `/references` API returns a JSON **list** with PascalCase keys and a nested
`ExerciseDates: {startDate, endDate}` object.  The original parser expected a dict
`{"references": [...]}` with camelCase keys.  Fixed: `parse_references` now accepts
both formats (list or dict wrapper, PascalCase or camelCase keys, nested or flat dates).

### Fixed (`.env` — duplicate malformed NBB key line)

Removed `NBB_CBSO_API_KEY = "..."` (with spaces and quotes) that caused
`command not found` shell warnings when sourcing the file.

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
