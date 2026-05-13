# be-leads — Claude Operating Manual

## Project (one paragraph)
High-volume recurring scraper for Belgian B2B company data. Sources will be added incrementally:
KBO Open Data dump (canonical bulk), kbopub HTML (function holders), NBB CBSO Authentic Data
(financials), goudengids/pagesdor listing pages (discovery), company websites (enrichment),
DuckDuckGo + Brave (cross-validation). Output: provenance-tracked Postgres database with a
Streamlit UI for sector × city queries.

## Architecture map
- `src/scraper/lib/`              cross-cutting helpers (http, polite, provenance, validators, errors, logging)
- `src/scraper/db/`               asyncpg pool, repositories, migrations, Pydantic row models
- `src/scraper/sources/<name>/`   one directory per source, layout: `fetcher.py | parser.py | __init__.py`
- `src/scraper/pipeline/`         orchestration: smart-refresh scheduler, enrichment fan-out, consolidation
- `src/scraper/scoring/`          confidence + dedup
- `src/scraper/ui/`               Streamlit app

Async boundary: every I/O function is `async`. Sync code is forbidden in `sources/`, `db/`, `pipeline/`.
UI may call `asyncio.run` at boundaries.

## Data model (canonical)
- `companies(kbo_number PK, ...)`             materialised current-best, NEVER directly UPDATEd
- `observations(id, kbo_number, field, value JSONB, source, observed_at, confidence, run_id, ...)`  append-only
See `agent_docs/data-model.md` for the full schema. The schema migration ships in prompt 3.

## Testing rules — TDD IS ENFORCED BY HOOKS
- Every change to `src/scraper/**` MUST touch `tests/**` in the same turn.
- Tests organised: `tests/unit/`, `tests/integration/`, `tests/golden/` (HTML/JSON/XBRL samples).
- `uv run pytest --cov=src/scraper --cov-fail-under=85` must pass before Stop.
- New scrapers require ≥3 golden HTML samples in `tests/golden/<source>/`.
- Network-hitting tests are marked `@pytest.mark.network` and skipped in CI.

## Coding conventions
- Type hints everywhere; `mypy --strict`.
- Pydantic v2 only at boundaries (parsed records, API I/O). Internal data: `@dataclass(frozen=True, slots=True)`.
- Pass dependencies explicitly (httpx client, asyncpg pool). No module-level globals.
- `asyncio.TaskGroup` for fan-out, never bare `create_task`.
- `structlog` with `contextvars`; bind `kbo_number`, `source`, `run_id` at outermost scope.
- Errors: typed exceptions in `src/scraper/lib/errors.py`. No bare `except:`.
- HTTP: never `httpx.AsyncClient()` per request — use the pool from `src/scraper/lib/http/`.

## Anti-patterns (never)
- `UPDATE companies SET ...` — observations only, never overwrite canonical facts.
- Synchronous I/O in async paths.
- Auto-retry on 403 — escalate or stop. Retry only on 429/503/504.
- Reimplementing KBO checksum or Belgian phone validation — use `python-stdnum.be.vat` and `phonenumbers`.
- Reading personal data into the system without per-source flags. (Out of scope for this iteration but the schema must support it later.)
- Adding `update` or `delete` methods to `ObservationsRepo`. The repo is intentionally append-only.
- Concurrent goudengids requests. The host's WAF penalises bursts harder than sustained low rate. Always concurrency 1.
- Treating search-engine observations as authority. They are evidence signals (confidence 0.50–0.55), never canonical. Never write code that resolves conflicts by trusting a search hit over KBO/NBB/goudengids.

## Per-source knowledge
Skills live under `.claude/skills/<name>/SKILL.md` and load on demand. Don't put per-source detail
in this file.
- Polite scraping rules: `.claude/skills/polite-scraping/SKILL.md` (active)
- Provenance schema rules: `.claude/skills/provenance-schema/SKILL.md` (active)
- Belgian phone validation rules: `.claude/skills/belgian-phone-validation/SKILL.md` (active)
- KBO / CBE rules (Open Data + kbopub): `.claude/skills/kbo-lookup/SKILL.md` (active)
- NBB financials rules: `.claude/skills/nbb-financials/SKILL.md` (active)
- Goudengids / pagesdor scraping rules: `.claude/skills/goudengids-listing/SKILL.md` (active)
- Website enrichment rules: `.claude/skills/website-analysis/SKILL.md` (active)
- Search cross-validation rules: `.claude/skills/search-cross-validation/SKILL.md` (active)

## Polite scraping
Default 0.5 req/s per host, exponential backoff with jitter on 429/503. Honour Retry-After. Skip on 403.
robots.txt fetched and cached at startup. See `.claude/skills/polite-scraping/SKILL.md` (added prompt 2).

## MCP setup
Set `LEADS_DB_RO_URL` (env var) to a read-only Postgres role URL before starting Claude Code.
The postgres MCP server (`.mcp.json`) uses this variable. Example:
`export LEADS_DB_RO_URL=postgresql://leads_ro:pass@localhost:5432/leads`

## How to run
- One-time: `uv python install 3.12 && uv sync --locked --dev && uv run playwright install chromium`
- DB: `docker compose up -d pg`
- Tests: `uv run pytest` or `uv run pytest -m "not network"`
- Lint: `uv run ruff check . && uv run ruff format --check .`
- Type check: `uv run mypy src/scraper`
- Pipeline CLI: `uv run be-leads-pipeline --sector electriciens --city antwerpen`
- App: `uv run streamlit run src/scraper/ui/app.py`

## Definition of done (every change)
1. Plan written in `.claude/plans/` and approved.
2. Tests added/updated FIRST, failing on the new behaviour.
3. Implementation makes them pass.
4. `ruff check`, `ruff format --check`, `mypy --strict` clean on changed files.
5. Coverage not regressed.
6. CHANGELOG entry added.
