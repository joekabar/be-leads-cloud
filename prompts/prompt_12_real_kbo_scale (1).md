# Bootstrap Prompt 12 — Real-Scale KBO Ingestion (Performance + Filters)

> **How to use:** `be-leads/`, Git Bash, fresh `claude` session. Postgres up. **You do NOT need a real KBO ZIP downloaded for this prompt** — the work is bounded by a 10k-row generated fixture that exercises the same code paths the real 2M-row dump will. The real-ZIP smoke test is documented in the runbook for whenever you have the download. Paste from `=== PROMPT ===`.

---

=== PROMPT ===

You are refactoring `src/scraper/sources/kbo_dump/` from a "passes a 5-row synthetic fixture" prototype into a "handles 2M Belgian enterprises on 8GB RAM in <30 minutes" production ingester. The interfaces stay the same; the internals get harder.

Three concrete changes:
1. **Bulk insert via asyncpg COPY** — replace whatever per-batch INSERT pattern exists today with `copy_records_to_table()` (binary COPY). This is the only change that gets us from ~500 rows/sec to ~50,000 rows/sec.
2. **Implement the sector_filter / city_filter parameters** that prompt 5 accepted but did not actually use. Two-pass: pass 1 builds the matching-entity-number set; pass 2 emits observations only for those entities.
3. **Drop the 24h dedup SELECT-before-insert.** At 2M companies × ~5 fields each, the dedup query becomes the bottleneck. Re-thinking: the matview `companies_current` already resolves duplicates via `DISTINCT ON (kbo_number, field) ORDER BY confidence DESC, observed_at DESC`. Re-ingesting the same Full ZIP creates duplicate observations rows (storage waste, ~250MB per re-run) but does not corrupt data. Document this trade-off; add a `--truncate-first` CLI flag for development cycles where storage matters.

This is a refactor + extension prompt. Existing test suite stays green; new tests cover scale and filters.

## Read first

- `CLAUDE.md`
- `agent_docs/architecture.md`, `agent_docs/runbook.md`
- `.claude/skills/kbo-lookup/SKILL.md` and `references/open-data-schema.md`
- `.claude/skills/provenance-schema/SKILL.md`
- `src/scraper/sources/kbo_dump/` (all five modules — parser, transformer, ingester, downloader, cli)
- `src/scraper/db/repositories/observations.py` (whatever insert path it currently uses)
- `src/scraper/db/migrations/` (you may need a new migration for a partial unique index)
- `tests/integration/sources/kbo_dump/test_ingester.py` (the existing test suite stays passing)
- Project memories under `~/.claude/projects/C--Users-Oxfam-Documents-Saivy-Programs-be-leads/memory/`

## Plan first

Create `.claude/plans/2026-05-13-kbo-real-scale.md`:
- Status: `approved`
- Goal: "Refactor `kbo_dump` ingester for production scale (2M enterprises, ~10M observations) on 8GB RAM in <30 min. Switch bulk insert to asyncpg COPY, implement deferred sector/city filters, add CLI flags for development cycles, document real-ZIP manual smoke."
- Scope in: refactor `ingester.py` insert path; implement two-pass filter logic; new CLI flags `--month YYYY-MM`, `--sector-nace`, `--city`, `--max-enterprises`, `--truncate-first`; generated 10k-row fixture for tests; new integration test for scale; update runbook with manual real-ZIP procedure; update CHANGELOG.
- Out of scope: SFTP automated downloader (still a stub); migration to add a `dedup_hash` column (rejected — matview resolution is sufficient); changes to other sources (`kbopub_html`, `nbb_authentic`, `goudengids`, `website`, `ddg_brave`); changes to schemas, models, or the matview definition.
- Acceptance: existing prompt-5 tests still pass; new 10k-fixture ingest completes in <60 seconds; sector_filter=['43'] + city_filter=['Antwerpen'] produces strictly fewer observations than unfiltered; re-ingesting the 10k fixture with `--truncate-first` produces the same `companies_current` row count as the first ingest; `mypy --strict` clean; coverage on `src/scraper/sources/kbo_dump/` stays ≥ 90%.

## Pre-flight

```bash
docker compose up -d pg
docker compose exec pg pg_isready -U leads
uv run pytest -q -m "not network and not slow" 2>&1 | tail -5    # 609 tests baseline
```

If the baseline fails, stop and report. Do not refactor on a red suite.

## What to produce

### A. Generated 10k fixture (replaces synthetic_mini for scale tests)

Add a fixture generator at `tests/integration/sources/kbo_dump/_generate_large_fixture.py`. This is a script, not a test. It produces a ZIP with realistic distributions:

- 10,000 enterprise rows
  - 70% legal persons (TypeOfEnterprise=1), 30% natural persons (TypeOfEnterprise=2)
  - StartDate distributed across 1990-2026
  - 5% start with `1` (modern allocation); 95% with `0`
  - All KBOs valid by `stdnum.be.vat.is_valid()` — generate via `stdnum.be.vat.format(random_valid_number)`
- 12,000 denomination rows (avg 1.2 per enterprise — some have legal+commercial+abbreviation)
- 15,000 address rows (avg 1.5 — seat + occasional branches)
  - Postal codes distributed: 30% Brussels (1000-1210), 25% Antwerp (2000-2660), 20% Ghent (9000-9052), 25% rest of Belgium
- 25,000 contact rows (avg 2.5 — phone + email + website mix)
  - 80% valid Belgian phones, 5% deliberately invalid (to test skip path)
  - 60% have email, 40% have website
- 18,000 activity rows (avg 1.8 — main + sometimes secondary)
  - NACE codes distributed: 15% start with `43` (construction), 15% with `46` (wholesale), 10% with `47` (retail), 10% with `62` (IT), 50% across other NACE divisions
  - Mix of NaceVersion 2008 and 2025

Critical: include **Bellock at `0439401387` as enterprise #1** with the canonical values (founding 1989-12-28, address Lange Van Bloerstraat 116/2060 Antwerpen, phone 03 236 13 06, name "Bellock NV", NACE 43.211). This keeps the discipline-rule eyeball check working.

The generator script writes to `tests/golden/kbo_dump/large_10k/` (gitignored — too big for repo) and the ZIP itself to a configurable path. Add `tests/golden/kbo_dump/large_10k/.gitignore` containing `*` so generated CSVs never get committed by accident.

The script is **idempotent and deterministic** — use `random.Random(seed=42)` so re-running it produces byte-identical output. This is what makes the integration test reproducible.

Hook it into `conftest.py`:

```python
@pytest.fixture(scope="session")
def large_zip(tmp_path_factory) -> Path:
    """Generate (once per session) a 10k-row fixture ZIP. Cached on disk."""
    cache = Path(__file__).parent.parent.parent / "golden" / "kbo_dump" / "large_10k" / "cached.zip"
    if cache.exists():
        return cache
    from tests.integration.sources.kbo_dump._generate_large_fixture import build
    cache.parent.mkdir(parents=True, exist_ok=True)
    build(cache, n_enterprises=10_000, seed=42)
    return cache
```

### B. Bulk insert refactor in `ingester.py`

Find the current insert path. Whatever it is — `INSERT ... VALUES`, `executemany`, `ObservationsRepo.insert_many()` with per-row binds — replace the kbo_dump-specific bulk path with asyncpg's binary COPY.

Reference shape:

```python
async def _bulk_insert_observations(
    conn: asyncpg.Connection,
    observations: list[Observation],
) -> int:
    """Bulk insert via COPY. Returns count inserted. ~50,000 rows/sec on local Postgres."""
    if not observations:
        return 0
    records = [
        (
            obs.kbo_number,
            obs.field,
            json.dumps(obs.value),     # JSONB serialised
            obs.raw_value,
            obs.source,
            obs.source_url,
            obs.observed_at,
            float(obs.confidence),
            obs.run_id,
        )
        for obs in observations
    ]
    await conn.copy_records_to_table(
        "observations",
        records=records,
        columns=[
            "kbo_number", "field", "value", "raw_value",
            "source", "source_url", "observed_at", "confidence", "run_id",
        ],
    )
    return len(records)
```

Notes:
- The `value` column is JSONB. asyncpg's COPY wants you to encode it as text and the server casts. Pass `json.dumps(...)` strings.
- The `run_id` column is UUID. Pass `UUID` objects directly — asyncpg encodes them.
- `confidence` is NUMERIC(3,2). asyncpg accepts `Decimal` and `float`.
- The COPY happens inside a single transaction per batch. Batch size stays at 5000 (prompt 5 default). At 10M total observations that's 2000 batches, each ~100ms = 200 seconds total. Plus the parse/transform overhead, total ingest time ~25 minutes for the real 2M-row Full ZIP.

**Remove the 24h dedup SELECT.** If it currently exists in `ingester.py`, delete it. The matview's `DISTINCT ON (kbo_number, field) ORDER BY confidence DESC, observed_at DESC` resolves duplicates correctly at refresh time. Document this in the docstring:

```python
async def ingest_zip(
    zip_path: Path,
    pool: asyncpg.Pool,
    *,
    batch_size: int = 5000,
    sector_filter: list[str] | None = None,
    city_filter: list[str] | None = None,
    month_label: str | None = None,
    max_enterprises: int | None = None,
    truncate_first: bool = False,
) -> IngestReport:
    """Stream the ZIP through transformers and bulk-insert via COPY.

    Idempotency note: this function does NOT dedupe at insert time. Re-running the same
    Full ZIP creates duplicate observation rows (~250MB per re-run on real data). The
    matview `companies_current` resolves duplicates via DISTINCT ON, so data integrity
    is preserved, only storage is wasted. Use --truncate-first for development cycles
    where storage matters more than history preservation.
    """
```

### C. Filter implementation (the bit prompt 5 deferred)

Two-pass strategy in `ingester.py`:

```python
async def _build_filter_set(
    zip_path: Path,
    *,
    sector_filter: list[str] | None,
    city_filter: list[str] | None,
) -> set[str] | None:
    """If filters are active, scan activity.csv + address.csv to find matching entity numbers.
    Returns None when no filters are active (the caller emits for every entity).
    Returns set[str] of compact 10-digit KBOs to keep otherwise."""
    if not sector_filter and not city_filter:
        return None

    keep: set[str] = set()
    if sector_filter:
        normalised = {s.strip().lstrip("0") for s in sector_filter}  # "43" matches NACE 43.xxx
        for row in iter_activities(zip_path):
            nace_div = row.nace_code.split(".")[0].lstrip("0")[:2]   # first 2 digits of NACE division
            if nace_div in normalised:
                keep.add(row.entity_number)

    if city_filter:
        normalised_cities = {c.strip().lower() for c in city_filter}
        if sector_filter:
            # Intersect: must match BOTH sector AND city
            keep_after_city: set[str] = set()
            for row in iter_addresses(zip_path):
                if row.entity_number not in keep:
                    continue
                muni_nl = (row.municipality_nl or "").lower()
                muni_fr = (row.municipality_fr or "").lower()
                if muni_nl in normalised_cities or muni_fr in normalised_cities:
                    keep_after_city.add(row.entity_number)
            keep = keep_after_city
        else:
            for row in iter_addresses(zip_path):
                muni_nl = (row.municipality_nl or "").lower()
                muni_fr = (row.municipality_fr or "").lower()
                if muni_nl in normalised_cities or muni_fr in normalised_cities:
                    keep.add(row.entity_number)

    return keep
```

In the main ingest loop, after building `keep`, every transformer call checks `if keep is not None and row.entity_number not in keep: continue` before emitting an observation. Apply this in every `iter_*` consumer (enterprises, denominations, addresses, contacts, activities).

Memory budget: 2M entities × 10-digit string = ~30MB for the keep set at worst case (full Belgium). Acceptable. For typical filtered runs (one city + one sector) the set is <10k entries / <300KB.

### D. CLI updates in `cli.py`

Add flags to `argparse`:

```
--zip PATH                          (required, unchanged)
--month YYYY-MM                     (optional; auto-detect from filename if absent)
--sector-nace CODES                 (comma-separated 2-digit NACE divisions, e.g. "43,46")
--city NAMES                        (comma-separated municipality names, e.g. "Antwerpen,Brussel")
--max-enterprises N                 (stop after N enterprises emitted — for dev cycles)
--truncate-first                    (DELETE FROM observations WHERE source='kbo_dump' before ingest)
--no-refresh                        (existing — skip matview refresh)
--database-url DSN                  (existing — env fallback)
```

Filename auto-detect for `--month`: `KboOpenData_42_2026_04_Full.zip` → `2026-04`. Regex: `_(\d{4})_(\d{2})_(?:Full|Update)\.zip$`. If neither flag nor filename gives a month, raise a clear error.

The `--truncate-first` path:

```python
if args.truncate_first:
    async with pool.acquire() as conn:
        deleted = await conn.execute("DELETE FROM observations WHERE source = 'kbo_dump'")
        print(f"Truncated {deleted} kbo_dump observations before ingest.", file=sys.stderr)
```

Print a confirmation that requires `--yes` if running against a database with >100k existing kbo_dump rows. This is a safety rail — accidental `--truncate-first` against a populated database costs hours of re-ingest.

```python
if args.truncate_first and not args.yes:
    async with pool.acquire() as conn:
        existing = await conn.fetchval("SELECT count(*) FROM observations WHERE source = 'kbo_dump'")
    if existing > 100_000:
        print(f"REFUSE: --truncate-first would delete {existing} rows. Re-run with --yes.", file=sys.stderr)
        return 2
```

### E. Tests

Add to `tests/integration/sources/kbo_dump/test_ingester_scale.py`:

```python
@pytest.mark.slow
async def test_10k_fixture_ingests_under_60_seconds(large_zip, test_db_pool):
    t0 = time.monotonic()
    report = await ingest_zip(large_zip, test_db_pool, month_label="2026-04")
    elapsed = time.monotonic() - t0
    assert elapsed < 60.0, f"10k ingest took {elapsed:.1f}s (limit 60s)"
    assert report.enterprises_processed == 10_000
    assert report.observations_inserted > 30_000   # ~3 obs per enterprise on average


@pytest.mark.slow
async def test_sector_filter_reduces_emissions(large_zip, test_db_pool):
    unfiltered = await ingest_zip(large_zip, test_db_pool, month_label="2026-04", truncate_first=True)
    filtered = await ingest_zip(large_zip, test_db_pool, month_label="2026-04",
                                 sector_filter=["43"], truncate_first=True)
    assert filtered.observations_inserted < unfiltered.observations_inserted
    assert filtered.observations_inserted > 0


@pytest.mark.slow
async def test_city_filter_reduces_emissions(large_zip, test_db_pool):
    unfiltered = await ingest_zip(large_zip, test_db_pool, month_label="2026-04", truncate_first=True)
    filtered = await ingest_zip(large_zip, test_db_pool, month_label="2026-04",
                                 city_filter=["Antwerpen"], truncate_first=True)
    assert 0 < filtered.observations_inserted < unfiltered.observations_inserted


@pytest.mark.slow
async def test_reingest_with_truncate_first_is_idempotent(large_zip, test_db_pool):
    first = await ingest_zip(large_zip, test_db_pool, month_label="2026-04", truncate_first=True)
    second = await ingest_zip(large_zip, test_db_pool, month_label="2026-04", truncate_first=True)
    assert first.observations_inserted == second.observations_inserted

    async with test_db_pool.acquire() as conn:
        count = await conn.fetchval("SELECT count(*) FROM companies_current")
    assert count > 0


@pytest.mark.slow
async def test_reingest_without_truncate_grows_observations(large_zip, test_db_pool):
    await ingest_zip(large_zip, test_db_pool, month_label="2026-04", truncate_first=True)
    async with test_db_pool.acquire() as conn:
        obs_before = await conn.fetchval("SELECT count(*) FROM observations WHERE source='kbo_dump'")
        cc_before = await conn.fetchval("SELECT count(*) FROM companies_current")

    await ingest_zip(large_zip, test_db_pool, month_label="2026-04", truncate_first=False)
    async with test_db_pool.acquire() as conn:
        obs_after = await conn.fetchval("SELECT count(*) FROM observations WHERE source='kbo_dump'")
        cc_after = await conn.fetchval("SELECT count(*) FROM companies_current")

    assert obs_after == 2 * obs_before, "without truncate, observations should double"
    assert cc_after == cc_before, "but companies_current is unchanged (matview resolves duplicates)"
```

These tests are marked `@pytest.mark.slow` so they don't run in the default `not network and not slow` invocation. Run them explicitly:

```bash
uv run pytest -q -m slow tests/integration/sources/kbo_dump/test_ingester_scale.py
```

Also keep the existing `test_ingester.py` from prompt 5 passing — the 5-row synthetic still exercises the same code path, just with `n=5`. No changes needed there unless the API surface of `ingest_zip()` changed (it should not — only internals).

### F. Update `agent_docs/runbook.md`

Append a section:

```
## Real KBO Open Data ZIP — manual smoke

### Download (one-time per month)
1. Log in to https://kbopub.economie.fgov.be/kbo-open-data/login (account joekabar).
2. Download the latest "Aansluiting KBO Open Data Bestand" Full ZIP — refreshed first Sunday of each month.
3. Place at `data/kbo_dump/KboOpenData_<n>_<YYYY>_<MM>_Full.zip`.
   Filename pattern is what the portal gives you; do not rename.

### Full ingest (~30 min)
    uv run be-leads-ingest-kbo --zip data/kbo_dump/KboOpenData_*_Full.zip

Expected: ~2M enterprises, ~10M observations, ~1.2GB Postgres growth on first run.
Subsequent monthly Full re-ingests without `--truncate-first` add another ~1.2GB each.
Use `--truncate-first --yes` if storage is a concern.

### Filtered ingest (~30 sec for one city + one sector)
    uv run be-leads-ingest-kbo \
        --zip data/kbo_dump/KboOpenData_*_Full.zip \
        --sector-nace 43 \
        --city Antwerpen \
        --truncate-first --yes

### Eyeball verification (Bellock)
    docker compose exec pg psql -U leads -d leads \
        -c "SELECT field, value FROM companies_current WHERE kbo_number='0439401387' ORDER BY field;"

Expect ≥3 rows: at minimum founding_date (1989-12-28), name (BELLOCK NV), address.
```

### G. Update CHANGELOG

Under `[Unreleased]`:
```
### Changed
- `kbo_dump` ingester: bulk insert via asyncpg COPY (~100x faster than per-row INSERT).
- `kbo_dump` ingester: removed 24h dedup SELECT — matview resolves duplicates at refresh time.

### Added
- `kbo_dump` CLI: `--month YYYY-MM` (auto-detected from filename), `--sector-nace`, `--city`, `--max-enterprises`, `--truncate-first`, `--yes`.
- `kbo_dump` filter implementation (deferred from prompt 5): two-pass keep-set strategy across activity.csv + address.csv.
- Generated 10k-row fixture for scale tests (`tests/integration/sources/kbo_dump/_generate_large_fixture.py`).
- 5 new scale tests under `@pytest.mark.slow`.
- Runbook section: real-ZIP manual smoke procedure.
```

## Verification — run before stopping

```bash
docker compose up -d pg
uv sync --locked --dev

# Existing suite still passes
uv run pytest -q -m "not network and not slow"

# New slow tests pass
uv run pytest -q -m slow tests/integration/sources/kbo_dump/test_ingester_scale.py

# Static checks
uv run mypy src/scraper
uv run ruff check src/scraper tests
uv run ruff format --check src/scraper tests

# Coverage on kbo_dump
uv run pytest --cov=src/scraper/sources/kbo_dump --cov-fail-under=90 -q \
    tests/unit/sources/kbo_dump tests/integration/sources/kbo_dump

# CLI smoke: dry-run filename auto-detect
uv run be-leads-ingest-kbo --zip /tmp/KboOpenData_99_2026_04_Full.zip --max-enterprises 0 --no-refresh \
    2>&1 | grep -E "month|2026-04" || echo "month auto-detect MISSING"

# CLI smoke: --truncate-first safety rail (should refuse without --yes if >100k rows)
# This one is just a docstring check — skip if test DB is empty
```

## Stop conditions

When green:
1. Print one-line summary: existing test count unchanged (609), new slow tests added (5), coverage on `kbo_dump` ≥90%, 10k-fixture ingest time observed (e.g. "47.3 seconds").
2. Print the verbatim output of these two psql queries against the test DB after the slow tests ran:
   ```bash
   docker compose exec pg psql -U leads -d leads -c \
       "SELECT count(*) AS obs FROM observations WHERE source='kbo_dump';"
   docker compose exec pg psql -U leads -d leads -c \
       "SELECT field, value FROM companies_current WHERE kbo_number='0439401387' ORDER BY field;"
   ```
3. Print verbatim: `Ready for follow-up prompts (real ZIP smoke when downloaded; consolidation debug; UI polish). Commit: git add . && git commit -m "kbo_dump: real-scale refactor + filters (prompt 12)".`
4. End the turn.

## Things you must NOT do

- Do not download a real KBO ZIP. The generated 10k fixture is sufficient.
- Do not add a `dedup_hash` column or schema migration. Matview resolution is the chosen pattern.
- Do not change the `Observation` dataclass shape or the JSONB value contracts. Other sources depend on them.
- Do not modify the matview definition or the `refresh_companies_current()` function.
- Do not modify any other source module (`kbopub_html`, `nbb_authentic`, `goudengids`, `website`, `ddg_brave`) — this prompt is scoped to `kbo_dump`.
- Do not add new runtime dependencies. `asyncpg.copy_records_to_table` is core asyncpg; nothing else is needed.
- Do not implement the SFTP downloader. `downloader.py` stays a stub. The manual portal download is documented in the runbook.
- Do not change `pyproject.toml` dependencies, only the scripts table if a CLI entry changes.
- Do not commit the generated 10k CSVs to git. The `.gitignore` in `tests/golden/kbo_dump/large_10k/` should prevent this — verify it's in place.
- Do not silently allow re-ingest of the same ZIP without `--truncate-first` to be the default behaviour. Add a structlog warning that the operation will create duplicate observations and recommend `--truncate-first` for development.
- Do not change the order of fields in `companies_current` or the field-priority resolution. The matview definition stays as-is.
