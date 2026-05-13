# Runbook

> Operational procedures. Content is filled in as each source is added in subsequent prompts.

## KBO Open Data ingestion

### First Full load

1. Register at https://kbopub.economie.fgov.be/kbo-open-data/login?lang=en and accept the licence.
2. Download `KboOpenData_<n>_<YYYY>_<MM>_Full.zip` to `data/kbo_dump/`.
3. Validate the number: `uv run be-leads-validate-kbo <enterprise_number>`.
4. Run the ingest:
   ```
   uv run be-leads-ingest-kbo --zip data/kbo_dump/KboOpenData_*_Full.zip
   ```
5. The last line of stdout is a JSON report — check `observations_inserted` > 0 and `phones_invalid_skipped` looks reasonable.
6. Verify in Postgres: `SELECT count(*) FROM companies_current;`

### Monthly Update ZIPs

Same command — the CLI auto-detects Full vs Update from `meta.csv` (`ExtractType` key).
Update ZIPs produce `status=deleted` observations for removed enterprises; no rows are deleted.

### SFTP automation (future)

`KboDumpDownloader` in `src/scraper/sources/kbo_dump/downloader.py` is a stub pending SFTP credentials from kbo-bce-webservice@economie.fgov.be.

### Sector / city filtering

```
uv run be-leads-ingest-kbo --zip data/kbo_dump/*.zip \
  --sector 43 --city Antwerpen --city Gent
```

Sector codes are NACE prefixes (e.g. `43` matches 43.1, 43.21, etc.). City names are matched case-insensitively against NL and FR municipality fields. Both filters are AND-combined.

## kbopub function holder enrichment

### Manual run (single or small batch)

```bash
uv run be-leads-fetch-kbopub --kbos 0439401387,0234567873 --lang nl
```

Last stdout line is a JSON report:
```json
{"kbos_processed": 2, "kbos_not_found": 0, "kbos_invalid": 0,
 "function_holders_total": 4, "observations_inserted": 4, "duration_s": 8.1}
```

### Batch run from file

```bash
uv run be-leads-fetch-kbopub --kbos @data/kbos.txt --lang nl --skip-recent-hours 24
```

One KBO per line in `kbos.txt`. Lines beginning with whitespace-only or empty after strip are skipped. `--skip-recent-hours 24` (default) skips KBOs already fetched in the last 24 h. Pass `--skip-recent-hours 0` to force re-fetch.

### Rate

kbopub is throttled to **0.25 req/s with concurrency 1** (configured in `.claude/skills/polite-scraping/references/per-host.toml`). A batch of 100 KBOs takes roughly 7 minutes.

### When kbopub blocks (HTTP 403)

The scraper raises `BlockedError` and aborts immediately — it does **not** retry on 403.

1. Stop the process.
2. Wait at least 30 minutes before retrying.
3. If blocks persist, the IP may need rotation (see *Rotating residential IP* section below).
4. Re-run with `--skip-recent-hours 0` only for the KBOs that did not complete.

## NBB CBSO Authentic Data — registration

1. Visit `https://api-portal.nbb.be`
2. Create account, verify email.
3. Subscribe to the product **"Authentic Data Query"** (FREE).
4. Copy the Subscription Key from "Profile → Subscriptions."
5. Add to `.env`:
   ```
   NBB_CBSO_API_KEY=<your_key>
   ```
6. Verify:
   ```
   uv run python .claude/skills/nbb-financials/scripts/probe.py
   ```

**Activation note:** subscriptions are typically active within minutes, sometimes
takes 1–2 hours. If `/references` returns 401 after 24 h, contact api-portal
support via the portal (their contact address rotates; do not put it in the repo).

## NBB financial data ingestion

### Manual run (single or small batch)

```bash
uv run be-leads-fetch-nbb --kbos 0439401387,0502699332 --subscription-key $NBB_CBSO_API_KEY
```

Last stdout line is a JSON report:
```json
{"kbos_processed": 2, "kbos_not_found": 0, "references_total": 4,
 "observations_inserted": 11, "duration_s": 4.2}
```

### Batch run from file

```bash
uv run be-leads-fetch-nbb --kbos @data/kbos.txt --skip-recent-hours 24
```

One KBO per line in `kbos.txt`. `--skip-recent-hours 24` (default) skips KBOs already
fetched in the last 24 h.

### Limit years fetched

```bash
uv run be-leads-fetch-nbb --kbos 0439401387 --years-back 3
```

Only emits observations for `exercise_year >= current_year - 3`.

### Rate

`ws.cbso.nbb.be` is throttled to **1.0 req/s with concurrency 2** (configured in
`.claude/skills/polite-scraping/references/per-host.toml`). A batch of 1 000 KBOs
takes ~17 min wall-clock (avg 2 calls per KBO).

## Goudengids / pagesdor discovery

### Initial setup

```bash
uv run playwright install chromium     # ~150 MB, one-time
```

### Discover a sector × city

```bash
uv run be-leads-discover-goudengids --sector elektriciens --city antwerpen --max-pages 10
```

Last stdout line is a JSON report:
```json
{"sector":"elektriciens","city":"antwerpen","pages_scanned":10,"cards_found":98,
 "cards_with_phone":82,"cards_with_website":54,"observations_inserted":412,
 "placeholders_created":98,"duration_s":37.2}
```

### French variant (pagesdor.be)

```bash
uv run be-leads-discover-goudengids --sector electriciens --city liege --lang fr
```

`--lang fr` switches the domain to `pagesdor.be` and uses `/recherche/` URLs.

### Rate

0.3 req/s, concurrency 1. 10 pages × ~10 cards = ~100 leads per run, ~35 seconds
wall-clock (plus 3–5 s Playwright warmup).

### When goudengids blocks

A 403 triggers an automatic re-warmup + retry. If the second attempt also 403s, the
ingester aborts cleanly with a `BlockedError` and logs `goudengids_blocked_aborting`.

If blocks become consistent:
1. Stop using the CLI for at least an hour, then resume.
2. If still blocked after multiple hours: consider routing through a residential proxy.
   See `.claude/skills/goudengids-listing/references/imperva-bypass.md` for the planned
   proxy injection point (not implemented in prompt 8).

### Cookie hygiene

Cookies live ~30–60 min. The fetcher auto-refreshes at 25 min. Do NOT cache cookies
across process restarts — the fetcher always warms up fresh on startup.

### Synthetic placeholder KBOs

Goudengids listing pages don't include KBO numbers. The transformer assigns each card a
deterministic 10-digit placeholder KBO starting with `9` (real KBOs start with `0`/`1`).
These are reconciled to real KBOs by the consolidation pass (prompt 11).

To query only confirmed-real companies (excluding placeholders):
```sql
SELECT * FROM observations WHERE kbo_number NOT LIKE '9%';
```

## Brave Search API — registration

1. Go to https://api.search.brave.com/app
2. Sign up (no credit card required for the free tier).
3. Create a subscription: "Data for Search" → free 2k/month.
4. Copy the subscription key.
5. Add to `.env`:
   ```
   BRAVE_SEARCH_API_KEY=<key>
   ```
6. Verify:
   ```
   uv run python .claude/skills/search-cross-validation/scripts/probe_search.py "Bellock" "Antwerpen"
   ```

## Quota budgeting

Free tier: 2000 queries / month ≈ 65 / day average.
One default ingest run of 50 companies in one sector × city ≈ 50–75 Brave queries.
That's ~25 sector-city runs per month on Brave alone. Beyond that, DDG fallback engages.

## DuckDuckGo fallback

No registration. Rate-limited aggressively — practical ceiling 100–200 queries per day
before sustained blocks. Use only when Brave is exhausted or unavailable.

## Cross-validation invocation

```bash
# By file (TSV: kbo<TAB>name<TAB>city)
echo -e "0439401387\tBellock\tAntwerpen" > /tmp/cv.tsv
uv run be-leads-search-validate --inputs /tmp/cv.tsv

# From DB (placeholder KBOs from goudengids)
uv run be-leads-search-validate --from-db --limit 50

# DDG-only (no Brave key)
uv run be-leads-search-validate --inputs /tmp/cv.tsv --engine ddg
```

## Rotating residential IP

> Coming in the enrichment source prompt.

The enrichment pipeline supports an HTTP proxy via `SCRAPER_PROXY_URL` in `.env.local`.
Rotating residential proxies reduce per-IP rate limiting when scraping listing sites at scale.

Steps (to be documented):
1. Obtain a rotating proxy endpoint from your provider.
2. Set `SCRAPER_PROXY_URL=http://user:pass@proxy.example.com:8080` in `.env.local`.
3. The `src/scraper/lib/http/` pool passes this to `httpx.AsyncClient(proxies=...)`.
- `jq` (used by .claude/hooks/*.sh)

## Database operations

- Start dev Postgres: `docker compose up -d pg`
- Apply migrations: `uv run be-leads-migrate`
- Refresh companies_current: `docker compose exec pg psql -U leads -c "SELECT refresh_companies_current();"` (the pipeline does this automatically; manual only for debugging)
- Wipe dev DB: `docker compose down -v` (destroys the volume — re-run `be-leads-migrate` after)

## Test database

- Integration tests create a disposable `leads_test_<timestamp>` DB and drop it at teardown.
- Never point integration tests at the dev `leads` DB.
- Run only integration tests: `uv run pytest -m integration`
- Run unit tests only (fast, no DB): `uv run pytest -m "not network and not slow and not integration"`

## Phone validation

Quick CLI test:

    uv run be-leads-validate-phone "03 236 13 06"

Refresh BIPT prefixes (quarterly):

1. Download latest from https://www.bipt.be/operators/publication/database-with-reserved-and-allocated-numbers
2. Update `.claude/skills/belgian-phone-validation/references/prefixes.tsv` preserving the column order
3. Run: `uv run pytest tests/unit/lib/validators/ -q`
4. Commit with message: `data: refresh BIPT prefix table (YYYY-MM)`

## End-to-end pipeline

The `be-leads-pipeline` CLI runs all six sources in order, consolidates placeholder KBOs,
refreshes the `companies_current` view, and prints a JSON report to stdout.

### Quick start

```bash
# Electricians in Antwerp, all sources
uv run be-leads-pipeline --sector electriciens --city antwerpen

# French, pages limited, skip NBB and search
uv run be-leads-pipeline \
  --sector electriciens --city liege --lang fr \
  --max-pages 3 --skip-nbb --skip-search

# Synthetic fixture (no live sources, useful for testing)
uv run be-leads-pipeline --sector electriciens --city antwerpen --use-fixture
```

### Environment variables required

| Variable | Source |
|---|---|
| `DATABASE_URL` | asyncpg pool URL (`postgresql://...`) |
| `BRAVE_SEARCH_API_KEY` | Brave API (optional; DDG fallback if absent) |
| `NBB_CBSO_API_KEY` | NBB portal (optional; NBB source skipped if absent) |

### Source execution order

1. `kbo_dump` — bulk KBO data (NACE + city filter applied here)
2. `goudengids` — listing discovery (placeholder KBOs emitted)
3. `kbopub_html` — function holder enrichment for real KBOs
4. `nbb_authentic` — financial observations
5. `website` — contact page + structured data enrichment
6. `ddg_brave` — cross-validation of placeholder KBOs
7. **Consolidation** — placeholder → real KBO fuzzy matching (rapidfuzz)
8. **`REFRESH MATERIALIZED VIEW companies_current`**

Per-source failures are isolated: a source that raises an exception is logged and skipped;
the pipeline continues and reports it in `sources_failed`.

### JSON report (stdout)

```json
{
  "sector": "electriciens",
  "city": "antwerpen",
  "sources_run": 6,
  "sources_skipped": 0,
  "sources_failed": {},
  "observations_inserted_per_source": {"kbo_dump": 412, "goudengids": 210, ...},
  "placeholders_created": 98,
  "placeholders_resolved": 71,
  "companies_in_view": 340,
  "duration_s": 127.4
}
```

### Streamlit UI

```bash
uv run streamlit run src/scraper/ui/app.py
```

Opens at `http://localhost:8501`. Configure sector, city, language, page count, and source
toggles in the sidebar; click **Run pipeline**. Results are scored (lead score = 0.5 ×
completeness + 0.35 × authority + 0.15 × recency) and sortable. A CSV download button
appears below the results table.

### Verifying a specific company (Bellock example)

```bash
# After a pipeline run:
psql $DATABASE_URL -c "
  SELECT field, value, source, confidence
  FROM companies_current
  WHERE kbo_number = '0439401387'
  ORDER BY field;
"
```

Should return ≥ 6 distinct fields (name, address, phone, website, founding_date, nace_code,
function_holder, revenue_*).

## Real KBO Open Data ZIP — manual smoke

### Download (one-time per month)
1. Log in to https://kbopub.economie.fgov.be/kbo-open-data/login (account joekabar).
2. Download the latest "Aansluiting KBO Open Data Bestand" Full ZIP — refreshed first Sunday of each month.
3. Place at `data/kbo_dump/KboOpenData_<n>_<YYYY>_<MM>_Full.zip`.
   Filename pattern is what the portal gives you; do not rename.

### Full ingest (~30 min)
```
uv run be-leads-ingest-kbo --zip data/kbo_dump/KboOpenData_*_Full.zip
```

Expected: ~2M enterprises, ~10M observations, ~1.2GB Postgres growth on first run.
Subsequent monthly Full re-ingests without `--truncate-first` add another ~1.2GB each.
Use `--truncate-first --yes` if storage is a concern.

### Filtered ingest (~30 sec for one city + one sector)
```
uv run be-leads-ingest-kbo \
    --zip data/kbo_dump/KboOpenData_*_Full.zip \
    --sector-nace 43 \
    --city Antwerpen \
    --truncate-first --yes
```

### Eyeball verification (Bellock)
```
docker compose exec pg psql -U leads -d leads \
    -c "SELECT field, value FROM companies_current WHERE kbo_number='0439401387' ORDER BY field;"
```

Expect ≥3 rows: at minimum `founding_date` (1989-12-28), `name` (BELLOCK NV), `address`.

## Spec deviations from initial prompts
   - Prompt 2 (polite-scraping): no runtime robots.txt checking. Project is testing-only.
   - Prompt 2: kbopub used for KBO number lookups too, not just function holders.