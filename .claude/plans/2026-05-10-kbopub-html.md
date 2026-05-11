# Plan: kbopub_html source (prompt 6)

**Status: approved**

## Goal

Ship the `kbopub_html` source that fetches each KBO's public-search detail page, parses out
function holders, and writes them as observations. Filling the one critical data gap left by
the Open Data dump.

## Scope in

- Source module `src/scraper/sources/kbopub_html/` (fetcher, parser, transformer, ingester, cli)
- HTML golden fixtures for 5 real-world test cases
- Selectors documented in the kbo-lookup skill
- Tests (unit + integration)
- CLAUDE.md / runbook / CHANGELOG updates

## Out of scope

- Function-holder data cleaning (deduplication of "Boonen Jan" vs "Jan Boonen" — enrichment step)
- Any non-function-holder data (already covered by kbo_dump)
- NACE codes or VAT activity sub-pages (toonvestigingps.html)
- WAF bypass (kbopub is not behind WAF; if it ever 403s, escalate per polite-scraping rules)

## Acceptance criteria

- Parser handles 5 golden HTML samples correctly (one with no holders, one with single
  bestuurder, one with multiple roles, one with French labels, one with old/struck-off entity
  / legal-person holder)
- Rate limiting enforces ≤0.25 rps observed in integration test (marked slow, skipped on Windows)
- Per-KBO fetch produces `function_holder` observations matching the JSONB shape contract
- Idempotent: re-running same KBO produces 0 new observations within 24h
- `mypy --strict` clean
- Coverage on `src/scraper/sources/kbopub_html/` ≥ 90%
