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

## Imperva cookie warm-up

> Coming in the goudengids/pagesdor source prompt.

Some listing pages on goudengids.be and pagesdor.be are behind Imperva/Incapsula. A
browser-based warm-up step (via Playwright) generates a valid session cookie. The async
scraper then uses this cookie for subsequent requests.

Steps (to be documented):
1. `uv run playwright install chromium` (one-time).
2. `uv run python -m scraper.sources.goudengids.warm_up` — opens a headless browser,
   completes the challenge, dumps the cookie jar to `data/cookies/goudengids.json`.
3. The fetcher reads the cookie jar on startup.

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

## Spec deviations from initial prompts
   - Prompt 2 (polite-scraping): no runtime robots.txt checking. Project is testing-only.
   - Prompt 2: kbopub used for KBO number lookups too, not just function holders.2