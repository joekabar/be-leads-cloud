# Plan: goudengids-listing skill + goudengids source

**Status:** approved
**Date:** 2026-05-10
**Prompt:** 8

## Goal

Ship the goudengids-listing skill plus goudengids source. Discovers companies by sector × city
via the listing pages of goudengids.be and pagesdor.be, parses each result card into a typed
row, validates contact info, and writes observations. Implements Imperva-cookie warm-up via
Playwright, then switches to httpx for the per-page fetches.

## Scope in

- Skill `SKILL.md` + references (`selectors.md`, `imperva-bypass.md`, `sectors.toml`) and `scripts/probe_listing.py`
- Source `src/scraper/sources/goudengids/` (warmup, fetcher, parser, transformer, ingester, cli)
- Golden HTML fixtures for 3 listing-page states + 1 FR variant
- Unit tests + integration tests
- CLAUDE.md / runbook / CHANGELOG updates
- Synthetic placeholder KBO scheme documented in provenance-schema skill
- `Observation._validate_kbo` relaxed to allow 10-digit strings starting with `9`

## Scope out

- Detail-page deep scan (prompt 9 / website source)
- Residential proxy rotation (prompt 11+)
- pagesdor.be tests beyond URL-builder check
- User-agent rotation (chrome-only pool, one UA)

## Acceptance criteria

- warmup module returns valid Imperva cookies for an httpx session in <30s on first call
- fetcher correctly handles "no results" and "last page" termination
- parser handles 4 golden HTML fixtures (antwerpen full, brugge sparse, no-results, FR)
- transformer emits name/phone/address/website/email observations per card
- idempotency via dedup on (placeholder_kbo, source) within 24h
- `mypy --strict` clean; coverage on `src/scraper/sources/goudengids/` ≥ 85%

## Files changed

### New
- `.claude/skills/goudengids-listing/SKILL.md`
- `.claude/skills/goudengids-listing/references/selectors.md`
- `.claude/skills/goudengids-listing/references/imperva-bypass.md`
- `.claude/skills/goudengids-listing/references/sectors.toml`
- `.claude/skills/goudengids-listing/scripts/probe_listing.py`
- `src/scraper/sources/goudengids/__init__.py`
- `src/scraper/sources/goudengids/warmup.py`
- `src/scraper/sources/goudengids/fetcher.py`
- `src/scraper/sources/goudengids/parser.py`
- `src/scraper/sources/goudengids/transformer.py`
- `src/scraper/sources/goudengids/ingester.py`
- `src/scraper/sources/goudengids/cli.py`
- `tests/golden/goudengids/README.md`
- `tests/golden/goudengids/listing_antwerpen_electriciens_page1.html`
- `tests/golden/goudengids/listing_brugge_bakkers_page2.html`
- `tests/golden/goudengids/listing_no_results.html`
- `tests/golden/goudengids/listing_french_liege_plombiers.html`
- `tests/unit/sources/goudengids/__init__.py`
- `tests/unit/sources/goudengids/test_warmup.py`
- `tests/unit/sources/goudengids/test_parser.py`
- `tests/unit/sources/goudengids/test_transformer.py`
- `tests/integration/sources/goudengids/__init__.py`
- `tests/integration/sources/goudengids/conftest.py`
- `tests/integration/sources/goudengids/test_fetcher.py`
- `tests/integration/sources/goudengids/test_ingester.py`
- `tests/integration/sources/goudengids/test_cli.py`

### Modified
- `src/scraper/db/models.py` — allow 9-prefix placeholder KBOs
- `pyproject.toml` — add `be-leads-discover-goudengids` entry point
- `CLAUDE.md` — add goudengids skill reference + anti-pattern
- `agent_docs/runbook.md` — add goudengids section
- `CHANGELOG.md` — add entry
- `.claude/skills/provenance-schema/SKILL.md` — add synthetic placeholder KBO section
