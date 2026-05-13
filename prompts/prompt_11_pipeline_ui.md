# Bootstrap Prompt 11 — Pipeline + Scoring + Streamlit UI (Integration Finale)

> **How to use:** `be-leads/`, Git Bash, fresh `claude` session. Postgres up. `.env` has `DATABASE_URL` and ideally `NBB_CBSO_API_KEY` (uncommented). Paste from `=== PROMPT ===`.

This is the largest prompt in the sequence. Budget 60–120 minutes. Ten sources are already built; this prompt wires them together, adds the consolidation logic (placeholder-KBO → real-KBO fuzzy match), the scoring engine (recency decay + consensus boost), the Streamlit UI, and an end-to-end smoke test that runs the whole pipeline against the synthetic kbo_dump fixture and verifies Bellock comes out the other end with full data.

---

=== PROMPT ===

You are shipping the integration layer: pipeline orchestration, the consolidation pass, the scoring engine, the Streamlit UI, and an end-to-end smoke test. After this prompt, the project is feature-complete: a user picks a sector + city in the UI, hits Run, and the pipeline coordinates all 6 sources in dependency order, consolidates placeholder KBOs into real ones, scores each (kbo, field) tuple, and presents a sortable lead table with CSV export.

No new sources, no new skills (one skill extension only). All the existing pieces are stable — your job is to glue them together correctly.

## Read first

- `CLAUDE.md`
- `agent_docs/architecture.md`, `agent_docs/data-model.md`, `agent_docs/runbook.md`
- `.claude/skills/provenance-schema/SKILL.md` — section on confidence formula and consensus boost (you'll implement it)
- `.claude/skills/polite-scraping/SKILL.md` — concurrency-1 hosts vs concurrency-15 (you'll respect these in the orchestrator)
- All six source `SKILL.md`: kbo-lookup, kbopub-selectors (in kbo-lookup), nbb-financials, goudengids-listing, website-analysis, search-cross-validation
- `src/scraper/db/repositories/observations.py` + `companies_current` matview definition
- `src/scraper/db/repositories/runs.py` (record run lifecycle)
- All six `ingester.py` modules — these are your primitives
- Project memories at `~/.claude/projects/C--Users-Oxfam-Documents-Saivy-Programs-be-leads/memory/`

## Plan first

`.claude/plans/2026-05-13-pipeline-ui-smoke.md`:
- Status: `approved`
- Goal: "Ship the pipeline orchestrator, the consolidation pass (placeholder→real KBO fuzzy match), the scoring engine (recency decay + cross-source consensus boost), the Streamlit UI, and an end-to-end smoke test that runs the full pipeline against the synthetic kbo_dump fixture and verifies Bellock emerges with phone/address/founding_date/website/financials/directors all populated and correctly scored."
- Scope in: `src/scraper/pipeline/` (run, consolidate, score modules); `src/scraper/scoring/` (confidence calculations); `src/scraper/ui/` (Streamlit app + components); a `scripts/smoke_e2e.py` runner; tests for pipeline, consolidation, scoring; one integration test that exercises the full happy path against the test DB; CHANGELOG / runbook / CLAUDE.md updates; minor `provenance-schema` skill extension to document the consensus formula's final form.
- Out of scope: the smart-refresh scheduler (job queue + cron — deferred; pipeline runs are one-shot for now); residential-proxy injection; advanced fuzzy-match algorithms beyond Levenshtein-on-normalized-name + postal-code match; NACE-based sector validation; multi-tenant UI auth.
- Acceptance: `uv run be-leads-pipeline --sector electriciens --city antwerpen --max-pages 1 --use-fixture` runs cleanly end-to-end against the synthetic kbo_dump fixture, produces ≥1 row in `companies_current` for Bellock (KBO 0439401387) with at least 6 distinct fields populated; Streamlit UI loads at `localhost:8501`, sector/city pickers work, results table populates from `companies_current`, CSV export works; the end-to-end smoke test passes in CI mode (no network); mypy --strict clean across the new modules; coverage on `src/scraper/pipeline/` and `src/scraper/scoring/` ≥ 85%.

## Pre-flight

```bash
docker compose up -d pg
uv run be-leads-migrate
uv run pytest -q -m "not network and not slow"   # 526 tests baseline
uv run pip list 2>&1 | grep -E "rapidfuzz|streamlit" || echo "rapidfuzz or streamlit not present — check pyproject"
```

`rapidfuzz` is needed for fuzzy-match in the consolidation pass. `streamlit` is already in deps. If `rapidfuzz` is missing, add it to runtime deps in `pyproject.toml` and `uv lock` + `uv sync --dev`.

## What to produce

### A. Scoring engine: `src/scraper/scoring/`

```
src/scraper/scoring/
├── __init__.py
├── confidence.py        # recency decay + consensus boost
└── ranking.py           # per-lead score for UI sort
```

#### confidence.py

```python
@dataclass(frozen=True, slots=True)
class ScoringConfig:
    base_priors: dict[tuple[str, str], float]    # (source, field_family) → prior, from confidence.md
    recency_decay_rate: float = 0.99              # per day
    recency_min: float = 0.30
    recency_max: float = 1.00
    consensus_boost_factor: float = 1.10           # × this per agreeing distinct source
    consensus_max: float = 1.00

def field_family(field: str) -> str:
    """Map a specific field to its prior family.
    revenue_2023 → financial; profit_2024 → financial; employees_2022 → financial;
    name → identity; address → address; phone → phone; website → website;
    founding_date → founding; nace_code → nace; function_holder → persons;
    activity_summary → activity; website_age → website_age; email → email;
    cross_validation → cross_validation; status → status; postal_code → address.
    """

def base_prior(source: str, field: str, config: ScoringConfig) -> float:
    """Look up (source, field_family) prior. Falls back to 0.5 if (source, family) missing."""

def apply_recency_decay(
    base: float,
    observed_at: datetime,
    now: datetime,
    config: ScoringConfig,
) -> float:
    """Returns base * (decay_rate ** days_since_observation), clamped to [min, max]."""

def apply_consensus_boost(
    raw_confidence: float,
    agreeing_sources_count: int,
    config: ScoringConfig,
) -> float:
    """For each distinct source beyond the first that observed the same (kbo, field, value),
    multiply by boost_factor. Cap at consensus_max."""
```

The base_priors dict is loaded once from a hardcoded constant that mirrors `.claude/skills/provenance-schema/references/confidence.md`. Don't read the markdown file at runtime — parse the table at module import (or just hardcode the values; the table is small and stable).

Hardcode this matrix verbatim (source → family priors):

```python
_PRIORS_TABLE: dict[tuple[str, str], float] = {
    # kbo_dump (canonical bulk)
    ("kbo_dump", "phone"):       0.95,
    ("kbo_dump", "identity"):    1.00,
    ("kbo_dump", "address"):     0.95,
    ("kbo_dump", "founding"):    1.00,
    ("kbo_dump", "website"):     0.85,
    ("kbo_dump", "nace"):        1.00,
    ("kbo_dump", "status"):      1.00,
    ("kbo_dump", "email"):       0.85,

    # kbopub (HTML)
    ("kbopub", "phone"):         0.85,
    ("kbopub", "identity"):      1.00,
    ("kbopub", "address"):       0.95,
    ("kbopub", "founding"):      1.00,
    ("kbopub", "website"):       0.80,
    ("kbopub", "persons"):       0.95,
    ("kbopub", "status"):        1.00,

    # nbb_authentic
    ("nbb_authentic", "financial"): 1.00,

    # goudengids
    ("goudengids", "phone"):     0.85,
    ("goudengids", "identity"):  0.85,
    ("goudengids", "address"):   0.80,
    ("goudengids", "founding"):  0.85,
    ("goudengids", "website"):   0.85,
    ("goudengids", "activity"):  0.70,

    # website (own site)
    ("website", "phone"):        0.75,
    ("website", "address"):      0.70,
    ("website", "website"):      1.00,
    ("website", "website_age"):  0.85,
    ("website", "persons"):      0.65,
    ("website", "email"):        0.85,
    ("website", "activity"):     0.80,

    # search engines
    ("brave", "website"):           0.55,
    ("brave", "cross_validation"):  0.55,
    ("ddg", "website"):             0.50,
    ("ddg", "cross_validation"):    0.50,

    # manual override (full trust)
    ("manual", "phone"):     1.00,
    ("manual", "address"):   1.00,
    ("manual", "identity"):  1.00,
    ("manual", "founding"):  1.00,
    ("manual", "website"):   1.00,
    ("manual", "financial"): 1.00,
    ("manual", "persons"):   1.00,
}
```

Field-family mapping in `field_family()`:
```python
def field_family(field: str) -> str:
    if field.startswith(("revenue_", "profit_", "employees_")):
        return "financial"
    return {
        "phone": "phone",
        "name": "identity",
        "address": "address",
        "postal_code": "address",
        "founding_date": "founding",
        "website": "website",
        "website_age": "website_age",
        "nace_code": "nace",
        "function_holder": "persons",
        "activity_summary": "activity",
        "email": "email",
        "status": "status",
        "cross_validation": "cross_validation",
    }.get(field, "other")
```

#### ranking.py

```python
@dataclass(frozen=True, slots=True)
class LeadScore:
    """Per-company headline score (0.0 to 1.0) for UI ranking."""
    kbo_number: str
    completeness: float          # 0-1: fraction of high-value fields populated
    authority: float             # 0-1: mean confidence over populated fields
    recency: float               # 0-1: 1.0 if all obs within 7 days, decays
    overall: float               # weighted blend

HIGH_VALUE_FIELDS: tuple[str, ...] = (
    "phone", "address", "founding_date", "website", "function_holder",
    "revenue_2023", "revenue_2024",
)

def compute_lead_score(
    observations: list[Observation],
    config: ScoringConfig,
    now: datetime,
) -> LeadScore:
    """Aggregate per-(kbo, field) confidences into a single 0-1 score for ranking."""
```

Algorithm:
1. Group observations by `field`. Within each field, pick the highest-confidence-currently observation (i.e. winning observation post-recency-and-consensus).
2. **completeness** = (number of HIGH_VALUE_FIELDS where at least one observation exists) / len(HIGH_VALUE_FIELDS).
3. **authority** = mean of `apply_recency_decay(base_prior, observed_at, now)` over populated HIGH_VALUE_FIELDS (or 0 if none populated).
4. **recency** = 1.0 - (mean(days_since_observation) / 90), clamped to [0, 1].
5. **overall** = 0.5 * completeness + 0.35 * authority + 0.15 * recency.

### B. Pipeline: `src/scraper/pipeline/`

```
src/scraper/pipeline/
├── __init__.py
├── orchestrator.py        # source-by-source coordinator
├── consolidate.py         # placeholder→real KBO match + matview refresh
├── run.py                 # top-level entry called by CLI
└── cli.py                 # be-leads-pipeline
```

#### orchestrator.py

```python
@dataclass(frozen=True, slots=True)
class PipelineConfig:
    sector: str
    city: str
    sector_slug: str        # resolved from sectors.toml
    max_pages: int = 5
    lang: Literal["nl", "fr"] = "nl"
    use_fixture: bool = False    # if True, kbo_dump uses synthetic mini; otherwise expects real ZIP path
    fixture_zip_path: Path | None = None
    do_kbo_dump: bool = True
    do_goudengids: bool = True
    do_kbopub: bool = True
    do_nbb: bool = True
    do_website: bool = True
    do_search: bool = True
    nbb_subscription_key: str | None = None
    brave_subscription_key: str | None = None

@dataclass
class PipelineReport:
    run_id: UUID
    sector: str
    city: str
    started_at: datetime
    ended_at: datetime | None
    sources_run: list[str]
    sources_skipped: list[str]
    sources_failed: dict[str, str]      # source → error message
    observations_inserted_per_source: dict[str, int]
    placeholders_created: int
    placeholders_resolved: int          # via consolidation
    companies_in_view: int              # rows in companies_current for this sector/city
    duration_s: float

async def run_pipeline(
    config: PipelineConfig,
    pool: asyncpg.Pool,
    polite_client: PoliteClient,
) -> PipelineReport: ...
```

Source ordering (this is the architecture):

1. **kbo_dump** (if `do_kbo_dump`): ingests the synthetic-mini fixture OR a real ZIP if `fixture_zip_path` is set. Populates the canonical company spine. Provides real KBO numbers + name + address + founding date + NACE + contact data. **Filters by sector_slug + city** via the optional filter params in `ingest_zip()`.
2. **goudengids** (if `do_goudengids`): listing-page discovery. Creates `9`-prefix placeholder KBOs for any companies not already in the DB. Provides phone confirmation, website, address cross-check.
3. **kbopub_html** (if `do_kbopub`): function-holder enrichment per real KBO found in step 1 (NOT for placeholders — they have no real KBO yet).
4. **nbb_authentic** (if `do_nbb` and key present): financial enrichment per real KBO from step 1.
5. **website** (if `do_website`): per-company website enrichment. Inputs: every (kbo_number, website) tuple in `companies_current` from sources 1-2.
6. **ddg_brave** (if `do_search`): cross-validation for placeholder KBOs from step 2 (resolves "is bellock.be really Bellock?").

Each source call is wrapped in try/except that catches and records to `sources_failed`. A failure in one source does NOT abort the pipeline.

After all sources, call the **consolidation pass** (see below) which fuzzy-matches placeholder KBOs to real ones.

After consolidation, **refresh the matview**: `SELECT refresh_companies_current();`.

Compute the report stats and return.

#### consolidate.py

```python
@dataclass(frozen=True, slots=True)
class ConsolidationMatch:
    placeholder_kbo: str       # 9-prefix
    real_kbo: str               # 0/1-prefix
    score: float                # 0-100, rapidfuzz ratio on normalized names
    matched_on: Literal["name+postal", "name+city", "name_only"]

async def consolidate(
    pool: asyncpg.Pool,
    *,
    name_match_threshold: float = 80.0,
) -> list[ConsolidationMatch]:
    """For each placeholder KBO in observations, find the best real-KBO match.
    Rewrites placeholder observations in place by inserting a NEW set of
    observations under the real_kbo (preserving source, value, observed_at, confidence,
    run_id) so the append-only invariant holds. Original placeholder rows remain
    in `observations` for audit; they are simply superseded in `companies_current`
    by the real-KBO rows which have higher consensus."""
```

Matching algorithm:
1. Query all distinct `kbo_number` from `observations` where `kbo_number` starts with `'9'`. For each, gather its `name`, `postal_code`, and `city` observations (latest).
2. Query all distinct real KBOs (start with `'0'` or `'1'`) and their `name`, `postal_code`, `city`.
3. For each placeholder:
   a. **First pass (strict)**: real-KBO candidates where `postal_code` matches exactly. Among those, compute `rapidfuzz.fuzz.token_set_ratio(placeholder_name_normalized, candidate_name_normalized)`. Best match ≥ `name_match_threshold` wins. `matched_on = "name+postal"`.
   b. **Second pass (looser)**: if no strict match, candidates where `city` (case-insensitive) matches. Same fuzz scoring. `matched_on = "name+city"`.
   c. **Third pass (loosest)**: name-only match across all real KBOs with `ratio ≥ 90`. `matched_on = "name_only"`. This is a fallback; many false positives expected here.
4. For each match, INSERT (don't UPDATE) the placeholder's observations under the real KBO. Set `source` unchanged, `observed_at` unchanged, but **decrease confidence by 10%** (multiply by 0.9) because consolidation is an inference, not a direct observation. New observations get the same `run_id` as the consolidation run (record this in `run_log`).
5. Return the list of matches for the report.

Name normalisation: same as classifier in prompt 10 — lowercase, strip diacritics, strip legal-form suffixes, strip whitespace/punctuation. Reuse `scraper.sources.ddg_brave.classifier.normalize_name` if it's exported; otherwise duplicate it (with a comment noting the shared function).

#### run.py

Top-level entry that wires everything:

```python
async def run(config: PipelineConfig) -> PipelineReport:
    """Initialise pool, polite_client, all source clients, then run orchestrator + consolidate."""
```

This is the function the CLI calls. It owns context-manager lifecycle for the pool and clients.

#### cli.py

`be-leads-pipeline`:
- `--sector <slug>` (required)
- `--city <name>` (required)
- `--max-pages N` (default 5)
- `--lang nl|fr` (default nl)
- `--use-fixture` flag: use synthetic kbo_dump ZIP from `tests/golden/kbo_dump/synthetic_mini/`
- `--fixture-zip <path>` if you want to point at a different real ZIP
- `--skip-kbo-dump --skip-goudengids --skip-kbopub --skip-nbb --skip-website --skip-search` individual disables
- `--database-url <DSN>` (env fallback)
- `--brave-key K` (env fallback)
- `--nbb-key K` (env fallback)

Register:
```
be-leads-pipeline = "scraper.pipeline.cli:cli_main"
```

Output: JSON report to stdout. Also: a human-readable summary table to stderr.

### C. Streamlit UI: `src/scraper/ui/`

```
src/scraper/ui/
├── __init__.py
├── app.py                  # main page
├── components/
│   ├── __init__.py
│   ├── pickers.py          # sector + city pickers (reads sectors.toml)
│   ├── results_table.py    # the data display
│   └── progress.py         # live progress bar
└── data.py                 # DB queries the UI runs
```

#### app.py

The single-page Streamlit app. Layout (top to bottom):

1. **Title**: "Belgian B2B Lead Generator"
2. **Sidebar**:
   - Sector picker (selectbox from sectors.toml)
   - City text input (default "Antwerpen")
   - Language radio (NL / FR)
   - "Pages to scan" slider (1-25, default 5)
   - "Use fixture (test data)" checkbox
   - Source toggles (6 checkboxes, all default on)
   - "Run pipeline" button
3. **Main area**:
   - When idle: a "Configure your search in the sidebar and click Run" placeholder
   - When running: a progress bar + log expander
   - When done: results table from `companies_current`, filtered to the sector/city, sortable by overall score, with a CSV download button
4. **Footer**: "Search results powered by Brave Search API" + a small note about KBO Open Data attribution.

The "Run pipeline" handler:
- Builds a `PipelineConfig` from the sidebar inputs.
- Calls `asyncio.run(scraper.pipeline.run(config))` inside a `with st.spinner(...)`.
- Captures stdout/stderr via `redirect_stdout` for the log expander.
- After completion, stores the report in `st.session_state["last_report"]`.
- Queries `companies_current` joined with the report's run_id to get the result rows.

Use `st.session_state` to persist between reruns. Don't run the pipeline on every interaction; only on the button click.

#### components/results_table.py

```python
def render_results_table(
    rows: list[dict[str, Any]],
    *,
    show_score: bool = True,
) -> None:
    """rows are dicts with keys: kbo_number, name, address, phone, website,
    founding_date, employees, revenue_latest, function_holders, score_overall.
    Renders st.dataframe with column config + a CSV download button."""
```

Column config:
- `kbo_number`: text
- `name`: text, wide
- `address`: text, wide
- `phone`: text
- `website`: link
- `founding_date`: date
- `employees`: number
- `revenue_latest`: number with EUR format
- `function_holders`: text (semicolon-joined)
- `score_overall`: progress (0-1)

CSV: button that builds a `pandas.DataFrame` from rows and writes `df.to_csv(index=False)` to a `download_button`.

#### data.py

```python
async def fetch_results_for_run(
    pool: asyncpg.Pool,
    run_id: UUID,
    *,
    sector: str | None = None,
    city: str | None = None,
) -> list[dict[str, Any]]:
    """Pull rows from companies_current for KBOs touched by this run,
    optionally filtered to sector/city via NACE code prefix + address city match.
    Computes per-row score via scoring.ranking.compute_lead_score on the
    raw observations."""
```

Query strategy: select distinct kbo_number from observations where run_id = ?, then for each kbo, select all observations and aggregate (in Python) into the dict shape expected by the table. Compute the LeadScore per kbo.

### D. Tests

```
tests/unit/scoring/
├── __init__.py
├── test_confidence.py
└── test_ranking.py
tests/unit/pipeline/
├── __init__.py
└── test_consolidate.py
tests/integration/pipeline/
├── __init__.py
├── conftest.py
├── test_orchestrator.py
├── test_consolidate_integration.py
└── test_smoke_e2e.py          # THE finale test
tests/unit/ui/
├── __init__.py
└── test_data.py
```

Required cases:

`test_confidence.py`:
- `base_prior("kbo_dump", "phone", ...)` → 0.95.
- `base_prior("unknown_source", "phone", ...)` → 0.5 fallback.
- `field_family("revenue_2023")` → "financial". `field_family("phone")` → "phone". `field_family("xxx")` → "other".
- `apply_recency_decay(0.95, 30 days ago)` → 0.95 * 0.99^30 ≈ 0.704, clamped above min.
- `apply_recency_decay(0.40, 5 years ago)` → clamped to 0.30 (the floor).
- `apply_consensus_boost(0.85, agreeing=1)` → 0.85 (no boost; first source IS the baseline).
- `apply_consensus_boost(0.85, agreeing=3)` → 0.85 * 1.1^2 = 1.0285, clamped to 1.00.

`test_ranking.py`:
- Empty observations → completeness=0, overall=0.
- Bellock-style: 7 obs covering phone, address, founding_date, website, function_holder, revenue_2023, plus one extra → completeness = 7/7 = 1.0, authority ≈ mean of priors, recency ≈ 1.0 (recent), overall ≈ 0.5 + 0.35 * 0.85 + 0.15 = ~0.94.
- Sparse: 1 obs (just name) → completeness very low (name isn't in HIGH_VALUE_FIELDS), overall < 0.2.

`test_consolidate.py`:
- Placeholder "9123456789" with name "Bellock" and postal "2060", real "0439401387" with name "Bellock NV" and postal "2060" → match via name+postal, score ≥ 80.
- Same names, different postal → fall through to name+city.
- Different names → no match.
- Placeholder "Acme BV" vs real "Acme NV" same postal → match (token_set_ratio handles legal-form suffix differences).
- Diacritic case: "Bückens" placeholder vs "Buckens" real, same postal → match.

`test_consolidate_integration.py` (integration):
- Seed test DB with: 1 placeholder KBO observation (name="Bellock", postal="2060", city="Antwerpen", phone="+3232361306") and 1 real KBO observation (KBO=0439401387, name="Bellock NV", postal="2060", city="Antwerpen", founding_date="1989-12-28").
- Run `consolidate(pool)`.
- Assert: returns 1 match. The placeholder's phone is re-emitted under 0439401387 with confidence × 0.9. After matview refresh, querying `companies_current WHERE kbo_number = '0439401387'` returns at minimum: name, phone, founding_date, postal_code.

`test_orchestrator.py` (integration):
- Mock each source's ingester (kbo_dump, goudengids, kbopub_html, nbb_authentic, website, ddg_brave) to insert known fixture observations.
- Run `run_pipeline(config)`.
- Assert source order in `sources_run` is exactly: kbo_dump, goudengids, kbopub_html, nbb_authentic, website, ddg_brave.
- One source raising an exception → recorded in `sources_failed`, other sources still run.
- Disabled source flag → recorded in `sources_skipped`.

`test_smoke_e2e.py` — the finale (integration):
- Uses the synthetic kbo_dump fixture from prompt 5.
- Mocks the other 5 sources with respx + fixtures from prompts 6-10 (Bellock-themed fixtures already exist).
- Runs `be-leads-pipeline --sector electriciens --city antwerpen --use-fixture` via subprocess.
- Asserts exit code 0.
- Queries `companies_current WHERE kbo_number = '0439401387'`.
- Asserts: ≥ 6 distinct fields populated. Specifically:
  - `name` value contains "Bellock"
  - `phone` value has `e164` = `+3232361306`
  - `founding_date` value `iso` = `1989-12-28`
  - `website` value `url` contains "bellock"
  - At least one `revenue_*` observation exists
  - At least one `function_holder` observation with `name` containing "Boonen"
- Asserts: `companies_current` row count for this run ≥ 1.

`test_data.py`:
- `fetch_results_for_run(pool, run_id)` against a seeded DB → returns list of dicts matching the expected schema (kbo_number, name, address, phone, website, score_overall).
- Sector filter: setting `sector="electriciens"` filters to KBOs whose NACE code starts with `43.2*` (electrical installation NACE family). Test with one matching + one non-matching KBO seeded.

### E. The smoke-test runner script

Create `scripts/smoke_e2e.py`. A standalone runnable (called by `test_smoke_e2e.py` via subprocess, also runnable manually by the user) that:

1. Connects to `DATABASE_URL`.
2. Creates a fresh schema migration on the test DB.
3. Runs the full pipeline against the synthetic fixture with all sources except NBB and Brave mocked.
4. NBB and Brave: if their env keys are set AND a `--live` flag is passed, hit real API. Otherwise mock.
5. Prints a pass/fail summary.
6. Exits 0 if all assertions pass, 1 otherwise.

Useful for the user to run manually after this prompt lands. Document in runbook.md.

### F. Update `provenance-schema` skill

Read `.claude/skills/provenance-schema/SKILL.md`. In section 4 (confidence formula), make these explicit:

```
recency_decay(base, observed_at, now) = clamp(base * 0.99 ** days_since, 0.30, 1.00)

consensus_boost(raw, agreeing_distinct_sources_count) =
    min(1.0, raw * 1.10 ** (agreeing_distinct_sources_count - 1))

Consolidation penalty (placeholder→real KBO): * 0.9 on re-emitted observations.
```

Add a short paragraph: "Consolidation observations carry the same `source` value as their origin (kbo_dump, goudengids, etc.) but confidence × 0.9 to reflect inference. Querying `observations WHERE confidence < origin_prior_threshold` reveals consolidation rows."

### G. Update CLAUDE.md

Under "## How to run":
```
- Pipeline (end-to-end): `uv run be-leads-pipeline --sector electriciens --city antwerpen --max-pages 5`
- UI: `uv run streamlit run src/scraper/ui/app.py`
- Smoke test: `uv run python scripts/smoke_e2e.py`
```

Under "## Per-source knowledge", add:
```
- Pipeline orchestration: `src/scraper/pipeline/orchestrator.py`. Source order is fixed: kbo_dump → goudengids → kbopub_html → nbb_authentic → website → ddg_brave. Consolidation runs last, before matview refresh.
```

### H. Update agent_docs/runbook.md

```
## End-to-end pipeline

### Sandbox run (synthetic data only)
    uv run be-leads-pipeline --sector electriciens --city antwerpen --use-fixture

### Live run (requires real KBO Open Data ZIP and API keys)
    export NBB_CBSO_API_KEY=...
    export BRAVE_SEARCH_API_KEY=...
    uv run be-leads-pipeline \
      --sector electriciens --city antwerpen \
      --fixture-zip data/kbo_dump/KboOpenData_2026_05_Full.zip \
      --max-pages 5

### Streamlit UI
    uv run streamlit run src/scraper/ui/app.py
    # Open http://localhost:8501

### Smoke test
    uv run python scripts/smoke_e2e.py
    uv run python scripts/smoke_e2e.py --live   # uses real NBB/Brave keys if set

### Expected first-run output (synthetic mini fixture, Bellock should appear)
- 1 row in companies_current for KBO 0439401387
- Fields populated: name, address, phone, founding_date, website, function_holder,
  revenue_2023, employees_2023 (from mocked NBB)
- Overall score ≥ 0.85
```

### I. Update CHANGELOG

```
### Added
- Pipeline orchestrator (`src/scraper/pipeline/`) wiring all six sources in dependency order with per-source error isolation.
- Consolidation pass: rapidfuzz-based placeholder→real KBO matching with 3-tier strictness (name+postal, name+city, name only).
- Scoring engine (`src/scraper/scoring/`): recency decay + cross-source consensus boost + lead ranking with completeness/authority/recency components.
- Streamlit UI (`src/scraper/ui/`): sector × city pickers, source toggles, run trigger, results table, CSV export.
- End-to-end smoke test in `scripts/smoke_e2e.py` and `tests/integration/pipeline/test_smoke_e2e.py`.
- CLI: `uv run be-leads-pipeline --sector <slug> --city <name>` plus `uv run streamlit run src/scraper/ui/app.py`.
```

## Verification

```bash
docker compose up -d pg
uv sync --locked --dev
uv run pytest -q -m "not network and not slow"
uv run pytest --cov=src/scraper/pipeline --cov=src/scraper/scoring --cov-fail-under=85 -q tests/unit/scoring tests/unit/pipeline tests/integration/pipeline tests/unit/ui
uv run mypy src/scraper
uv run ruff check src/scraper tests
uv run ruff format --check src/scraper tests

# Smoke test
uv run python scripts/smoke_e2e.py 2>&1 | tail -20

# End-to-end via CLI (synthetic fixture)
uv run be-leads-pipeline --sector electriciens --city antwerpen --use-fixture 2>&1 | tail -30

# Verify Bellock is in companies_current
docker compose exec pg psql -U leads -c "
  SELECT field, value::text
  FROM companies_current
  WHERE kbo_number = '0439401387'
  ORDER BY field;
"

# Streamlit launches (kill within 3 sec — we just want to confirm import works)
timeout 3 uv run streamlit run src/scraper/ui/app.py --server.headless true 2>&1 | head -5 || true
```

Expected outputs:
- Smoke test prints "ALL ASSERTIONS PASSED" and exits 0.
- The pipeline CLI prints a JSON report with `companies_in_view >= 1` and `sources_run` containing all 6 sources.
- The `psql` query returns ≥ 6 rows for Bellock (name, phone, address, founding_date, website, status, plus possibly NACE / function_holder / revenue depending on whether mocks ran).
- The `streamlit` launch prints `You can now view your Streamlit app in your browser` (then gets killed by timeout).

## Stop conditions

When all green:
1. Print summary: new files, tests passing total (was 526), coverage on pipeline + scoring + ui, the full verbatim output of the `psql` Bellock query, and the JSON report from the CLI run.
2. Print verbatim: `Project complete. 11 prompts shipped. Final commit: git add . && git commit -m "pipeline + scoring + Streamlit UI (prompt 11) — finale"`.
3. End the turn.

## Things you must NOT do

- Do not implement the smart-refresh scheduler. Deferred. Pipeline runs are one-shot.
- Do not implement a job queue. The pipeline is fully in-process for now.
- Do not add new sources. Six is the scope.
- Do not add multi-tenant / auth to the UI.
- Do not change the observation JSONB shapes. They're contracts.
- Do not blanket-add dependencies. `rapidfuzz` is the only acceptable addition; verify it's not already in lockfile before adding.
- Do not hit live KBO / NBB / Brave / DDG in tests. The smoke test runs against mocks unless `--live` is passed.
- Do not modify source modules from prompts 5-10. They're stable. Pipeline orchestrator wraps them; doesn't reach into them.
- Do not skip the end-to-end Bellock assertion. That's the load-bearing check that everything connects.
