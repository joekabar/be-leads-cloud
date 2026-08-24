# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed — a two-day scraping outage reported `exit=0` four times

- On 2026-08-22 and 2026-08-23 every sector of all four scheduled runs failed with
  `Page.goto: net::ERR_NAME_NOT_RESOLVED at https://www.goudengids.be/` — a transient DNS
  failure on the host. Forty sector failures, **zero observations across two full days**,
  ~2.7 hours of runtime, and every run logged `END exit=0 sectors_done=0 blocks=0`.
- The wrapper decided success by grepping the log for `goudengids_sector_done`, which
  counts sectors **attempted**, and never counted `goudengids_sector_failed` at all. So a
  night where everything failed was indistinguishable from "nothing left to scrape". The
  same grep reported `sectors_done=10` for the 2026-08-24 run that the batch itself scored
  as 6.
- `be-leads-pipeline-batch` gains `--summary-json PATH`, writing the end-of-run summary it
  already builds as UTF-8 JSON. `nightly_scrape.ps1` reads that instead of parsing a
  UTF-16 log tail, and falls back to the old grep — with a `NOTE` — if the file is absent,
  which itself means the batch died before writing it.
- The state line now reads `END exit=4 scraped=0/10 failed=10 blocks=0 reason=sector-failures
  :: Page.goto: net::ERR_NAME_NOT_RESOLVED ...` — verified by replaying the recorded
  2026-08-22 and 2026-08-24 logs through the shipped decision block.
- New exit codes, because a Scheduled Task's `LastTaskResult` is the only thing most people
  glance at: **4** = sectors failed outright (DNS, browser never reached the site);
  **5** = scraped fine but a source failed. A *blocked* sector is not a failure — it stays
  queued and is still reported separately.
- A summary file that cannot be written is logged and swallowed: the observations are
  already committed by then, and losing a 49-minute run over a reporting file would be a
  worse failure than the one it exists to surface.

### Found — Brave cross-validation has been off since 2026-08-21

- The 2026-08-24 batch summary carries `"sources_failed": {"ddg_brave": "terminal HTTP 402"}`
  — Payment Required. The free tier's 2,000 queries/month is exhausted or the subscription
  lapsed. 180 candidates were queued for validation and none ran. Needs an account change,
  not a code change; it is now surfaced as `exit=5` rather than passing silently.

### Fixed — the daily export was pinned to one city while the scraper rotated past it

- The scheduled task ran `daily_export.ps1 -City oostende`, and the script itself defaulted
  to `@('oostende')`. The scraper rotates through `scrape_cities.toml`; the export did not.
- When the rotation moved to Brugge on 2026-08-21, the export kept asking for Oostende.
  **2,170 exportable Brugge leads were in the database and in no CSV at all** — 572 of them
  only reachable because of the postcode fix in this same release. The `exports/` folder
  held nothing but `leads_oostende_*.csv`, flat at ~298 kB, while Brugge data poured in.
- `daily_export.ps1` now writes **one file per city** and discovers the cities itself.
  Passing `-City` still overrides. A new city starts exporting the morning after its first
  scrape with nothing to edit.
- New `be-leads-export-cities` CLI and `cities_to_export()`. The signal is a **goudengids
  run**, not the presence of rows: `companies_current` holds the whole country from the KBO
  dump, so every configured city has registry rows — Brussels has the most exportable ones
  of any city (5,952) despite never having been scraped. Keying off `run_log` keeps the
  export to cities actually worked. Slugs are canonicalised, so the pre-normalisation
  `Oostende` rows fold into `oostende` rather than producing a second file.
- Row counts in the log now come from the export CLI's own record count instead of
  `(Get-Content | Measure-Object -Line).Lines - 1`, which counted **physical** lines: one
  Oostende address contains an embedded newline, so a 1,976-row file was logged as 1,977.
- `daily_export.ps1` also gains the script-scope `trap` and the shared `Invoke-Uv` helper
  that `nightly_scrape.ps1` already had, so an unhandled error writes an `END exit=1` line
  instead of leaving `START` as the last thing in the log.
- First run: 6 files, 8,253 rows — aalst 407, antwerpen 2,065, brugge 2,170, gent 1,140,
  oostende 1,981, sint-niklaas 490.

### Fixed — the city postcode map was wrong for 13 of 15 cities

- `pipeline/city_map.toml` carried a curated postcode list per city that **overrode**
  `lib/postcodes.toml`. The two had drifted, and the override was the worse of the pair.
  Audited against the KBO Open Data address table, 13 of 15 curated cities were wrong.
- Surfaced by the first Brugge run (2026-08-21). Three sectors — `dakdekkers`,
  `carrosserieherstellers`, `cateringbedrijven` — fetched cards and wrote **zero**
  observations while reporting success: `cards_found=30 cards_out_of_city=30`. Every card
  was discarded by the postcode filter. Brugge was mapped to `["8000","8020","8200"]`, so:
  - `8310` (Assebroek, Sint-Kruis) and `8380` (Zeebrugge, Lissewege, Dudzele) were
    **missing** — roughly 30% of the city could not be scraped at all; and
  - `8020` is **Oostkamp**, a separate municipality — 4,490 observations already carry it,
    scraped and exported as if they were Brugge.
- Both directions are silent. A missing code loses companies that are never fetched; an
  extra code sells a company as being somewhere it is not.
- Rule now stated and enforced: a slug covers exactly one legal municipality, including its
  sub-municipalities, and nothing else. Kuurne is not Kortrijk; Beveren is not Sint-Niklaas.
  `brussel` is the one deliberate exception — all 19 Brussels-Capital communes, since they
  are a single market and a single goudengids/pagesdor target.
- Net effect against the registry: **+32,631 companies become reachable** (namur regained
  `5100`/`5101` = 9,102; brugge +9,678; charleroi +8,338; antwerpen +1,909 for the 2025
  Borsbeek merger) and **160,959 stop being attributed to the wrong city** (sint-niklaas was
  71% other municipalities, hasselt 52%, mechelen 56%).
- Two registry traps handled explicitly: companies at `3720`–`3724` self-report "Hasselt"
  but those codes are Kortessem, so postal assignment wins over the registry; and `8401`,
  `3030`, `9110`, `9219`, `2008` appear in KBO only as a handful of foreign addresses
  (Winterthur, Limassol) and are excluded.

### Fixed — export's `city` column was blank for Gent, Liège, Mons and Namur

- `gent`/`ghent`, `liege`/`luik`, `mons`/`bergen` and `namur`/`namen` existed as separate
  entries each holding a copy of the same postcode list. `city_for_postal_code()` drops any
  code claimed by more than one slug rather than guessing, so every one of those postcodes
  resolved to `None` and the exported `city` column came out empty for all four cities.
- They are now `alias_of` declarations, which add no second owner. The two spellings can no
  longer drift apart either.

### Changed — `postcodes.toml` is authoritative; `city_map.toml` may only supplement

- Precedence inverted. `city_map.toml` may add cities `postcodes.toml` does not define and
  declare aliases; an entry redefining a city it already owns is ignored, and a test fails
  the build if one is added. Two competing lists for one city was the bug, not the fix.
- The Walloon slugs in `postcodes.toml` were renamed `bergen`→`mons`, `luik`→`liege`,
  `namen`→`namur` so the canonical slug matches the one the CLI and rotation already use;
  the old spellings keep working as aliases. Neither had ever been scraped.

### Fixed — uv's progress output on stderr killed every scheduled run for five days

- `nightly_scrape.ps1` and `daily_export.ps1` captured CLI output with `2>&1` under
  `$ErrorActionPreference = 'Stop'`. Windows PowerShell 5.1 wraps each stderr line from a
  native exe in a `NativeCommandError`, which is **terminating** under `Stop`, so the script
  died mid-statement — before the `if ($LASTEXITCODE -ne 0)` beneath it could log anything.
- The trigger was not a failure. `uv` writes ordinary progress to stderr, and it reinstalled
  the editable package on every invocation while the `be-leads-suppress` entry point sat
  uncommitted in `pyproject.toml`. So `Uninstalled 1 package in 0.3ms` was fatal.
- Cost: **every scheduled run from 2026-08-12 14:30 to 2026-08-17 died silently** — ten
  nightly scrapes and ~30 four-hourly exports. Each logged `START` and nothing more, exited
  1, and produced no per-run log. Latest observation stood still at 2026-08-12 01:02 and
  `prospect_scores` — which ranks every export — went five days stale with nothing reported.
- The trap was already known: `nightly_scrape.ps1` documents it and guards the batch call.
  Three call sites were missed — `next-city`, `next-sectors`, and the export. All three now
  route through a helper that drops to `'Continue'`, splits stdout from stderr **by object
  type** (`ErrorRecord` vs string) so `Uninstalled 1 package` can never be parsed as a city
  name, logs stderr as UTF-8 via `Add-Content` (a bare `2>>` writes UTF-16), and returns the
  real exit code.
- Added a script-scope `trap` so any *other* unhandled terminating error still writes an
  `END exit=1 reason=unhandled :: <message>` line. A night that produced nothing must say so.
- Removed a stray em dash from `daily_export.ps1`, which broke the file's own pure-ASCII rule.

### Added — suppression list: objections and erasure requests are honoured at export time

- New `suppression_list` table (migration `009`) plus `be-leads-suppress` CLI. Every export
  consults the list and refuses to emit a matching row.
- Suppression is a **separate mutable layer**, not a delete. `observations` is append-only
  by design and its provenance trail is what makes the dataset defensible, so honouring
  GDPR Art. 21 (objection to direct marketing, absolute) and Art. 17 (erasure) by deleting
  rows would falsify the record of what was seen and when. The observation stays; the
  disclosure stops.
- An entry may key on **KBO number, email, or phone** — at least one, enforced by a CHECK
  constraint. Objections arrive as "stop calling this number", not as a company number.
  KBO matches are filtered in the selection query; phone and email are checked per row,
  because the same number sits on both a placeholder and the real KBO it merged into, and
  a KBO-only filter would leave the twin exporting the very number that was objected to.
- Matching tolerates the shapes the data actually arrives in: `CHAR(10)` space padding on
  KBO numbers, and case differences on email (a request typed `INFO@Example.be` suppresses
  a scraped `info@example.be`).
- A missing table is tolerated so exports still run on pre-009 schemas, but **only**
  `UndefinedTableError` is caught. Any other fault — permission denied, a transient error —
  raises rather than reading as an empty list, which would silently ship every objector.
  That is the same swallowed-failure pattern removed from phases D/E/F below.
- Existing CSV files already written are unaffected; the CLI says so on every insert.

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

### Added — consolidation matches on street address, bridging trade name vs legal name

- goudengids lists what is on the shopfront; KBO lists what is on the register. No fuzzy
  name score connects `Art Barbershop` to `bro`, `Hotel Melinda` to `melinda`, or
  `Dokter Storme` to `dokterthierrystorme` — and that mismatch, not absence from the
  registry, is why most placeholders stayed unmatched.
- Diagnosis on 589 unmatched Oostende placeholders: **69.8% scored 60–79** against a real
  company (just under the threshold), only 29.2% scored below 60, and just 1% were
  rejected by the phone veto. Lowering the threshold to 60 was not an option —
  `Bakkerij Desmedt → DRUKKERIJ DESMET` happened *at* 80.
- Phone corroboration was measured first and rejected: it would have rescued **4**, because
  86% of these placeholders have a phone matching no real company (KBO holds contact data
  for only ~36% of companies).
- The new pass matches on normalised `street|postcode` where **exactly one** real company
  occupies that address and the name still scores ≥60. Shared addresses are skipped
  entirely: an office building holds dozens of companies and picking the best name among
  them would attach a neighbour's identity.
- **Measured result: 47 matches** across the whole database (average name score 69.7),
  adding 22 NACE labels, 18 revenue figures and 33 status values to the Oostende export.
  The pairs are unambiguous — `TOTALE RENOVATIE BRUGGE`/`tr.totale renovatie`,
  `GARAGE VANDEGINSTE`/`VANDEGINSTE`, `Dokter Storme`/`DOKTER THIERRY STORME`.
- An earlier draft of this entry claimed 139. That figure counted every uniquely-addressed
  candidate **before** applying the ≥60 name floor that the pass actually uses; the sample
  behind it ranged down to 33.8. The design was right, the projection was not.
- It runs ahead of the name-only pass, which is the least reliable (17.8% phone
  disagreement). The phone veto applies on top, and the name floor guards against premises
  that changed hands.

### Performance — stop paging once results leave the requested city

- goudengids pads a thin local search with nationwide results, which the postcode filter
  then discards. Those were the scraper's most expensive and least productive requests:
  `machinebouwers` fetched **25 pages and 500 cards of which all 500 were out of city**;
  `logistiekverleners` kept 35 of 500.
- That mattered more as the WAF tightened. Pages fetched per block fell from **~120
  (2026-08-05) to ~11 (2026-08-11)** while total pages per run barely moved — the same
  volume now draws 6–8× the blocks, so budget spent on discarded pages directly starves
  the sectors that would have produced.
- The ingester now abandons a sector after `max_empty_pages` (default 3) consecutive pages
  with no in-city card. Local results rank first, so a run of empty pages means the useful
  part is already behind us. The streak resets whenever a local card reappears.
- Stopping early counts as `[complete]`, not `[interrupted]`: it is a decision, not a
  failure, and re-running would reach the same conclusion. `GoudengidsReport.stopped_early`
  records it and `goudengids_left_city_stopping` logs it.
- `max_pages` drops from 25 to **12** across `BatchConfig` and the batch CLI, for the same
  reason.
- This reduces load rather than working around the block: it stops requesting pages that
  were always going to be thrown away.

### Fixed — six sectors were invisible to the queue because run_log stores the URL slug

- `_run_goudengids_sector` resolves a config key to its goudengids slug *before* calling
  the ingester, so `start_run` records `aannemers`, not `bouwbedrijven`. The queue compares
  against config keys, so the six sectors whose slug differs — bouwbedrijven/aannemers,
  logistiekverleners/logistiek, machinebouwers/machinebouw,
  metaalverwerkingsbedrijven/metaalbewerking, recyclagebedrijven-industrieel/
  recyclagebedrijven, transportbedrijven-zwaar/vrachttransport — **could never be marked
  done however much they produced**, and held a slot on every run indefinitely.
- Five of those six are exactly the sectors seen stuck across eleven consecutive runs.
  **This, not the "obs=0" rule, was their root cause**; the previous entry's analysis was
  real but secondary.
- `completed_sectors()` now normalises the recorded slug back to config keys. The map is
  deliberately one-to-many: `recyclagebedrijven` is both a config key and the alias for
  `recyclagebedrijven-industrieel`, and since both fetch the same URL one run genuinely
  covers both.

### Fixed — a DNS outage marked 25 real sectors as complete

- On 2026-08-09/10 every sector failed with `net::ERR_NAME_NOT_RESOLVED`. That raises
  during fetcher warmup — *before* the page loop that sets the interrupted flag — so the
  `finally` block wrote `[complete]` regardless, retiring 25 genuine sectors (restaurants,
  scholen, supermarkten, tandartsen, slagers, sanitair…) that had done no work at all.
  Introduced by the previous change; caught within a day by the export flatlining again.
- The marker now requires positive evidence: not interrupted **and** `pages_scanned > 0`.
  That counter only increments after a successful fetch, so any failure raising out of the
  function leaves it at 0 and can never be mistaken for coverage.
- Repaired the 30 affected `run_log` rows in place. The direction is deliberate — re-running
  a sector costs a little WAF budget, wrongly retiring one loses its leads permanently.
- Root cause of the outage itself is environmental, not code: NordVPN is running and the
  host resolves via a private DNS server (172.26.164.17). Resolution and a live fetch both
  succeed now, so it was transient — but the pipeline had no way to distinguish "the site
  said no" from "we never reached the site".

### Fixed — nine of ten nightly slots were stuck re-scraping finished sectors

- The Oostende export sat at **220 kB for three consecutive days** while both nightly runs
  spent the full WAF budget. On 2026-08-06 the run fetched **2,173 cards across 111 pages
  and inserted zero observations.** Sectors had been retried up to **11 times** without
  ever being productive.
- `completed_sectors()` marked a sector done only when `jobs_done > 0`, but "obs=0"
  conflates three unrelated outcomes and only one of them deserves a retry:
  1. **No local businesses.** goudengids pads a thin local search with nationwide results.
     `machinebouwers` returned 500 cards of which **all 500** were outside Oostende, so the
     postcode filter correctly discarded every one. It can never yield a local lead.
  2. **Already covered.** `bouwbedrijven` had **84 in-city cards** pass the filter and still
     insert nothing — those firms were already known from other sectors. Complete, not
     failed. Dedup is per *company*, not per sector, and one firm appears under many.
  3. **Blocked or timed out.** The genuine retry case.
- Completion, not productivity, is now the signal. `ingester.py` records
  `[complete]`/`[interrupted]` in `run_log.notes` — it already distinguished `BlockedError`
  and `PlaywrightTimeoutError` from a normal return, that fact was simply discarded — and
  `completed_sectors()` retires anything that finished, whatever it inserted.
- Rows without a marker fall back to the old productivity rule, so history stays valid and
  the queue self-heals after one further run per sector rather than needing a backfill.
- The diagnosis was invisible because `cards_out_of_city` was tracked in
  `GoudengidsReport` and logged by the *source* ingester, but the batch-level
  `goudengids_sector_done` line reported only `cards`/`obs`/`pages`.

### Added — Brave runs report their own quota

- `BraveClient` records `x-ratelimit-remaining` / `-limit` / `-policy` and logs them once
  per client as `brave_quota`, so "did the quota hold?" is answerable from the run log
  afterwards instead of needing a live probe. Without it, exhaustion only ever surfaces as
  an HTTP 403 after the damage is done.
- Measured on the live key: `x-ratelimit-policy: 50;w=1, 0;w=2678400` — **50 queries per
  second**, with the monthly window reporting 0 (not the free tier, which is 1/s and
  2,000/month). Against a measured burn of ~250 queries/day, per-second headroom is five
  orders of magnitude clear.
- Burn rate is bounded by *new* placeholders per run, not the total backlog: Phase C2
  selects `kbo_number LIKE '9%' AND observed_at >= started_at`. Recent days produced
  109–257 new placeholders, and `--ddg-brave-skip-recent-hours 168` suppresses repeats.

### Fixed — API keys were read before .env was loaded, disabling Brave *and* NBB

- `batch_cli.py` read `BRAVE_SEARCH_API_KEY` and `NBB_CBSO_API_KEY` from `os.environ` on
  the two lines **above** the `load_settings()` call that runs `load_dotenv()`. Both were
  therefore always `None` for anyone keeping keys in `.env` — which is exactly what
  `.env.example` instructs.
- Two silent consequences. Phase C2 fell back to DuckDuckGo alone and died; and
  `_phase_c1_nbb` skips when no key is present, so **the batch pipeline has never run NBB
  financial enrichment at all**. Every nightly run since batch mode landed was missing
  both.
- Key resolution moved after `load_settings()` and extracted as `_resolve_api_keys()` so
  the ordering requirement is stated where it can be tested rather than implied by line
  order. Verified live: the Brave key returns HTTP 200 with real results, and a real
  Phase C2 pass over three placeholders made 3 Brave queries, inserted 6 observations and
  confirmed 3 websites with no errors.
- **Not a billing problem.** The key is valid and within quota; the request never left the
  process.

### Fixed — "No results found." aborted the entire cross-validation phase

- `ddgs` raises `DDGSException("No results found.")` when a query simply matches nothing.
  `DdgClient.search()` caught only `RatelimitException`, so that escaped uncaught past the
  caller's handler and killed Phase C2 outright: every batch from 2026-07-30 to 08-02
  logged `phase_c2_failed error='No results found.'` and cross-validated nothing.
- A query matching nothing is an outcome, not a failure — it now returns `[]`.
  `RatelimitException` subclasses `DDGSException`, so it is caught first and still raises
  `DdgRateLimitedError`; a test pins that ordering.
- The per-company loop in `ingester.py` also catches unexpected errors, records them on the
  report and continues. One company's search must never cost the batch its whole pass —
  the same failure shape as the Phase D/E/F suppression fixed earlier this week.

### Fixed — revenue and employees were blank in every export and every UI row, always

- `sources/nbb_authentic/transformer.py` writes `{"value": <amount>, "currency": "EUR", …}`,
  but both readers — `ui/export.py` and `ui/data.py::_latest_financial` — looked for
  `"eur"`/`"count"`. Those keys exist on **1 of 73,939** financial observations, so
  `revenue_2023`, `revenue_2024` and `employees_2024` were empty for every company in both
  the CSV and the Streamlit UI, regardless of how much NBB data had been collected.
- 70 `nbb_authentic` runs and 128,892 jobs of financial data were being discarded at the
  last step. After the fix, on the live Oostende export: `revenue_2023` 34.6%,
  `revenue_2024` 36.0%, `employees_2024` 7.7% — all previously 0.0%.
- Extracted as `_financial_amount()`, shared by both readers, preferring `"value"` and
  keeping the legacy keys as fallbacks. It tests key **membership** rather than truthiness:
  a genuine turnover of 0 is data, and `or` chaining silently discarded it.
- The `--max-revenue` filter was never affected — its SQL already read `value->>'value'`
  correctly, so the two halves of the same feature disagreed about the schema.
- **Why the test suite missed it:** the existing tests asserted against
  `{"eur": …}` / `{"count": …}` — they encoded the same imagined shape as the code, so
  1,200 tests at 86% coverage all passed while the feature produced nothing. New tests use
  the shape the producer actually writes.

### Fixed — a third of exported rows had no city

- goudengids listing cards usually carry a postcode but no municipality: **358,414 of its
  642,520** address observations (56%) have no city, against 106 of 1,182,231 for
  `kbo_dump`. So `city` was blank on 495 of 1,340 rows even though the postcode that
  selected the row was sitting in the next column.
- New `city_map.city_for_postal_code()` inverts the existing city→postcodes map to fill the
  gap. A postcode claimed by more than one configured city resolves to `None` rather than a
  guess — writing the wrong municipality is worse than leaving the column empty.
- City coverage on the Oostende export: **63.1% → 100%**.

### Added — the scrape walks a city rotation instead of one hard-coded city

- `nightly_scrape.ps1` no longer pins `-City oostende`. It asks the new
  **`be-leads-next-city`** which city to work on, and that returns the first entry in
  `src/scraper/lib/scrape_cities.toml` still holding a scrapeable sector. One city is
  finished before the next begins: a complete city is a sellable dataset, eleven
  half-scraped ones are not. Passing `-City <slug>` still pins a single city.
- Rotation order: **brugge** (by request), then **oostende** (already ~46% done, so a
  second finished city comes cheap), then the rest roughly by company count. Flemish
  cities only — Charleroi, Liège, Mons and Namur sit on pagesdor.be and need `lang="fr"`
  with a different slug set, which is separate work. `gent`/`ghent` in `city_map.toml`
  are byte-identical duplicates; only `gent` is in the rotation, so Ghent is not scraped
  twice.
- `select_next_city()` skips sectors goudengids cannot serve, so a city whose only
  remaining entries are unscrapeable counts as finished rather than pinning the rotation.
  When every city is complete the CLI prints nothing and the run exits early.
- Because the run log is named after the city and the city is not known until the
  database has answered, preflight output now goes to its own `preflight_<stamp>.log`.

### Changed — a scraped sector stays done until a refresh is requested

- `fetch_completed_sectors()` defaulted to a 720-hour (30-day) window, so every sector
  silently returned to the queue after a month. Harmless with one city; fatal to an
  eleven-city rotation, where early cities would re-enter the queue before the last was
  ever reached. All-time is now the default — refresh only on command.
- Pass `--within-hours 720` to reinstate the old rolling window, or `--cycle` to restart
  a city deliberately. A commanded re-scrape also wants
  `--goudengids-skip-recent-hours 0`, since that is a separate dedup layer.
- `_completed_window_clause(0)` returns all-time rather than an empty window.
  Interpolating 0 would have produced `started_at >= now()`, marking every sector pending
  forever — the exact inverse of what passing 0 means.
- This immediately recovered real work: brugge, sint-niklaas, antwerpen, aalst and gent
  were scraped on 2026-05-17 (brugge's `advocaten` alone yielded 2,578 observations) and
  had all silently expired. 63 sector-jobs preserved rather than re-scraped.

### Changed — two scrape runs a day

- `be-leads-nightly-scrape` now triggers at **02:30 and 14:30**. Measured evidence says the
  WAF limiter is a short rolling window rather than a daily quota: on 2026-08-02 a block at
  16.2 min was followed by `kledingwinkels` pulling 25 pages and 749 observations at
  35.7 min. Two sessions 12 hours apart should each start clean.
- Remaining work across the rotation is **772 sector-jobs** — roughly 2.6 months at ~10
  productive sectors/day. Frequency is no longer the constraint; the sector supply is.

### Fixed — a third of every export was the same company twice

- Consolidation re-emits a matched placeholder's observations under the real KBO but never
  deletes the placeholder, correctly, since observations are append-only. The export then
  selected **both**, so `LIAM VERHUIZINGEN` shipped as `9001582028` (phone, no NACE) *and*
  as `1028670251` (phone, NACE 49420). Measured on the 2026-08-01 Oostende file: **559 of
  1,674 rows** were the redundant half of a matched pair. The apparent 61% gap in
  `nace_label` was largely this, not missing data.
- The export now drops a placeholder when its matched real KBO **is also in the selection**.
  That membership test is essential rather than defensive: a company listed on goudengids in
  Oostende may be *registered* elsewhere, so a city-filtered export selects the placeholder
  but not the twin. An unconditional drop orphaned **147 real leads (13% of the file)** with
  no representative left — caught before release and covered by a regression test.
- Result on live data: 1,674 → 1,340 rows, 559 duplicates removed, **0 orphaned**, and
  `nace_label` coverage rises from 39.1% to 53.5% on the same underlying data.

### Fixed — a disagreeing phone number now vetoes a consolidation match

- `Bakkerij Desmedt` (a bakery, +3259704201) had been matched to `DRUKKERIJ DESMET` (a
  printing works, +3259332224) at score exactly **80.00**, the threshold floor, via
  `name+postal` — both sit in 8400 Oostende. The bakery's phone was then re-emitted onto the
  printer's registry record at 0.9 confidence.
- Neither obvious lever fixes this. Raising the threshold does not: score-100 pairs still
  disagree on phone 8.4% of the time. Nor does geography: `name_only` matches disagree 15.2%
  within a province versus 17.4% across provinces — statistically indistinguishable.
- The phone does separate them. Across production matches the two sides agree **2,954** times
  and disagree **303** times, and the disagreement rate tracks pass reliability exactly:
  `name+postal` 6.6%, `name+city` 11.1%, `name_only` **17.8%**.
- `_phones_conflict()` now rejects any candidate whose phone differs, in all three passes.
  Where only one side has a phone there is no evidence either way, so the name decides. On
  the `name_only` pass the veto rejects the placeholder outright rather than falling through
  to a runner-up — that pass has the worst false-match rate, so it fails closed.
- Deliberate trade for a dataset that gets sold: a missed link is far cheaper than attaching
  one company's phone number to another company's record. Pre-existing bad links are left in
  place — observations are append-only, so this fixes forward only.

### Added — the export says what a company does, not just its NACE number

- The CSV carried `nace_code` as a bare number (`43320`), which tells a reader nothing.
  Two columns now sit beside it: **`nace_label`** (`43320` → "Schrijnwerk") and
  **`activity_summary`** (the website-derived sentence, where enrichment found one).
- Labels come from `code.csv` inside the KBO Open Data ZIP — the official descriptions,
  already downloaded. `scripts/generate_nace_labels.py` extracts them once into the bundled
  `src/scraper/lib/nace_labels.toml` (10,422 labels, 772 kB) alongside `sectors.toml` and
  `postcodes.toml`. **Bundled rather than staged on purpose**: the `kbo_stage_*` tables are
  UNLOGGED, so crash recovery empties them and an export joined against them would silently
  blank the column — the same failure mode that nearly killed the 2026-07-31 run.
- All three NACE versions are included (2025 ≈1.23M companies, 2008 ≈17k, 2003 ≈14k);
  omitting the older two would have left ~31k companies unlabelled.
- Lookup is longest-prefix *within a single version*, mirroring `scoring/hv_prior.py`, so
  `01999` resolves to its `01` parent group and the 15 production rows carrying 6–7 character
  codes still resolve. It deliberately never falls back across versions: codes are reused with
  different meanings between taxonomies, so a cross-version match could attach a plainly wrong
  description.
- Measured on the live 1,674-row Oostende export: **654 of 654 companies that have a NACE code
  got a label — zero lookup failures.** The remaining 1,020 rows have no NACE code at all, 956
  of them goudengids placeholders that consolidation has not yet matched to a real KBO. Raising
  that 39% is a consolidation problem, not a labelling one.

### Added — the nightly scrape brings its own database up

- Every step of the nightly run needs Postgres, which runs in Docker — and Docker Desktop is
  configured **not** to start at login on the scrape host (`AutoStart = False`, startup entry
  disabled). A reboot therefore killed the whole night, which is exactly how the 2026-07-30
  session found the database unreachable.
- `docker-compose.yml` gives `pg` `restart: unless-stopped`, so the container returns whenever
  Docker runs instead of staying down after a host or daemon restart.
- `nightly_scrape.ps1` now preflights the database before doing anything else: probe
  127.0.0.1:5432, and only if it is closed start Docker Desktop (waiting up to 300 s for the
  daemon), `docker compose up -d pg`, then wait for `pg_isready`. An open port is not treated
  as readiness — after a cold start Postgres binds 5432 while still recovering and rejects
  connections for the better part of a minute.
- Failure is explicit: `END exit=3 reason=database-unavailable` in the state log and exit code
  3, rather than three commands' worth of confusing asyncpg tracebacks.
- New `-CheckOnly` switch runs the preflight and stops, so the dependency can be verified
  without spending an hour of WAF budget. Verified both ways: with the database already up the
  check returns in under a second; with the container stopped it restarted it and reported
  ready in 9 s.

### Fixed — sectors goudengids cannot serve occupied a nightly slot forever

- `completed_sectors()` counts a sector done only when `jobs_done > 0`. That is correct for a
  *blocked* sector — it reached the WAF, not the data — but wrong for one the site does not
  index at all: it yields zero every time, so "retry" meant "retry forever".
  `afvalverwerkingsindustrie` and `automobielfabrieken` both logged
  `goudengids_sector_not_indexed` on 2026-07-30 and sat at the head of the queue.
- New `goudengids_unscrapeable_sectors()` derives the dead set from the existing
  `goudengids_sector_not_indexed` flag in `sectors.toml` (also catching sectors with no
  goudengids entry at all), and `select_pending_sectors()` takes an `unscrapeable` argument
  that drops them. The exclusion survives `--cycle`; blocked-sector retry is unchanged.
- Effect on the live queue: pending for oostende fell from **82 to 55**. Twenty-seven
  configured sectors can never be scraped from goudengids, and each would have consumed a
  slot on every future night.

### Changed — nightly slice lowered from 15 sectors to 10

- On 2026-07-30 the WAF served 10 productive sectors over ~44 minutes and then blocked the
  next three on page 1. Ten keeps the session under the observed threshold, and after the
  fix above all ten slots go to sectors that can actually produce data. Applied to the
  `be-leads-nightly-scrape` scheduled task, which lives outside the repo.

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
