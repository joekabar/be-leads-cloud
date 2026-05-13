# Plan: Pipeline Orchestrator + Scoring Engine + Streamlit UI + E2E Smoke Test

**Status:** approved  
**Date:** 2026-05-13

## Goal

Ship the pipeline orchestrator, consolidation pass (placeholder→real KBO fuzzy match), scoring engine (recency decay + cross-source consensus boost), Streamlit UI, and an end-to-end smoke test that runs the full pipeline against the synthetic kbo_dump fixture and verifies Bellock emerges with phone/address/founding_date/website/financials/directors all populated and correctly scored.

## Scope in

- `src/scraper/scoring/` — confidence.py, ranking.py
- `src/scraper/pipeline/` — orchestrator.py, consolidate.py, run.py, cli.py
- `src/scraper/ui/` — app.py, data.py, components/
- `scripts/smoke_e2e.py`
- Tests: unit/scoring, unit/pipeline, integration/pipeline, unit/ui
- CHANGELOG, CLAUDE.md, runbook, provenance-schema skill extension

## Scope out

- Smart-refresh scheduler (job queue + cron — deferred)
- Residential-proxy injection
- Advanced fuzzy-match beyond Levenshtein-on-normalized-name + postal-code match
- NACE-based sector validation
- Multi-tenant UI auth

## Acceptance

- `uv run be-leads-pipeline --sector electriciens --city antwerpen --use-fixture` runs cleanly
- `companies_current` has ≥1 row for Bellock (KBO 0439401387) with ≥6 distinct fields
- Streamlit UI imports and starts without error
- All new tests pass; coverage on pipeline + scoring ≥ 85%
- `mypy --strict` clean on new modules

## Source ordering (fixed)

1. kbo_dump — canonical spine
2. goudengids — discovery + placeholder KBOs
3. kbopub_html — function holders (real KBOs only)
4. nbb_authentic — financials (real KBOs only, key optional)
5. website — enrichment (per website URL in companies_current)
6. ddg_brave — cross-validation for placeholder KBOs
7. consolidate — placeholder→real KBO merge
8. matview refresh
