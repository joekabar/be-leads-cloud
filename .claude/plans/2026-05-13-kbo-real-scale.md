# Plan: KBO Real-Scale Refactor (Prompt 12)

**Status:** approved

## Goal
Refactor `kbo_dump` ingester for production scale (2M enterprises, ~10M observations) on 8GB RAM in <30 min. Switch bulk insert to asyncpg COPY, implement deferred sector/city filters, add CLI flags for development cycles, document real-ZIP manual smoke.

## Scope in
- Refactor `ingester.py` insert path to asyncpg binary COPY (~100× faster)
- Remove per-batch `SELECT`-before-insert dedup (matview resolves duplicates)
- Implement two-pass keep-set filter logic (was deferred in prompt 5)
- New `ingest_zip` params: `month_label`, `max_enterprises`, `truncate_first`
- New CLI flags: `--month YYYY-MM`, `--sector-nace`, `--city`, `--max-enterprises`, `--truncate-first`, `--yes`
- Generated 10k-row fixture (`_generate_large_fixture.py`), cached to disk, seeded
- 5 new scale integration tests (`@pytest.mark.slow`)
- Runbook: real-ZIP manual smoke section
- CHANGELOG entries

## Scope out
- SFTP automated downloader (stub remains)
- `dedup_hash` column or schema migration (matview is sufficient)
- Changes to other sources (kbopub_html, nbb_authentic, goudengids, website, ddg_brave)
- Matview definition or `refresh_companies_current()` changes

## Acceptance criteria
1. Existing 608-test suite stays green after changes
2. New 10k-fixture ingest completes in <60 seconds (marked slow)
3. `sector_filter=['43'] + city_filter=['Antwerpen']` produces strictly fewer observations than unfiltered
4. Re-ingesting 10k fixture with `truncate_first=True` produces same `companies_current` count as first ingest
5. `mypy --strict` clean; coverage on `src/scraper/sources/kbo_dump/` stays ≥ 90%

## Key decisions
- **No dedup at insert time**: re-ingesting same ZIP without `--truncate-first` adds ~250MB of duplicate observations. Matview resolves via `DISTINCT ON`. Document in docstring + structlog warning.
- **asyncpg binary COPY**: `copy_records_to_table` — ~50k rows/sec vs ~500 rows/sec for per-row INSERT.
- **Two-pass filter**: pass 1 reads activity.csv + address.csv to build keep-set; pass 2 emits only matching entities. Memory: ~30MB worst case for full Belgium.
- **`test_ingest_idempotent` updated**: dedup removal changes the expected behavior. Test is updated to assert re-ingest creates duplicate observations (not 0).
- **`large_zip` fixture upgraded** from 50-enterprise to 10k-enterprise (cached to disk for speed).
