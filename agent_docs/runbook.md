# Runbook

> Operational procedures. Content is filled in as each source is added in subsequent prompts.

## Daily KBO Open Data update

> Coming in the KBO Open Data source prompt.

Steps (to be documented):
1. Download the latest delta dump from `kbopub.economie.fgov.be/kbo-open-data/`.
2. Validate ZIP checksums.
3. Run `uv run python -m scraper.pipeline.kbo_refresh --mode=delta`.
4. Confirm observation counts in `pipeline_runs` are non-zero.
5. Run `REFRESH MATERIALISED VIEW CONCURRENTLY companies_current;`.

## NBB CBSO key registration

> Coming in the NBB source prompt.

Steps (to be documented):
1. Register at `ws.cbso.nbb.be` for Authentic Data access.
2. Obtain `NBB_CBSO_API_KEY` and `NBB_CBSO_CLIENT_NUMBER`.
3. Add both to `.env.local` (gitignored).
4. Verify: `uv run python -m scraper.sources.nbb_cbso --check-auth`.

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
   - Prompt 2: kbopub used for KBO number lookups too, not just function holders.