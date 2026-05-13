# be-leads — Project Handoff Summary

Status checkpoint after prompt 9 lands. Paste this into a new Claude chat to resume seamlessly.

---

## Project context

`be-leads` is a Belgian B2B company scraper. Multi-source provenance database in Postgres with Streamlit UI. Repo: `C:/Users/Oxfam/Documents/Saivy/Programs/be-leads`.

**Operator profile:** Joe (user `Oxfam` on Windows 11 + VS Code + Git Bash). Direct, technical, no pleasantries. Project is for testing purposes — no legal/compliance scaffolding required.

**Stack:** Python 3.12 via uv, asyncio everywhere, httpx + asyncpg + BeautifulSoup + Pydantic v2 + Streamlit. Postgres 16 in docker compose. pytest + mypy --strict + ruff. TDD enforced by hooks (jq-based bash scripts).

**Workflow:** 11-prompt bootstrap sequence, each prompt is a one-shot Claude Code paste that ships a skill + source + tests + CLI. Each prompt commits separately.

## Progress

11 commits, ~440 tests, ~10000 lines of code. Foundation done through website enrichment. Three prompts left.

### Completed

| # | Commit | What | Tests | Coverage |
|---|---|---|---|---|
| 1 | `fbd5497` | Scaffold (pyproject, hooks, docker compose, ADR-0001 Postgres-only) | 1 | — |
| 2 | `b1d7a64` | Skill `polite-scraping` + `lib/http/` (limiter, retry, client) | +17 | 93% |
| 3 | `ea9b37c` | Skill `provenance-schema` + DB layer (4 tables + matview + migrations) | +71 | 91% |
| 4 | `9c0f169` | Skill `belgian-phone-validation` + `lib/validators/phone.py` | +27 | 100% |
| 5 | `fb99537` | Skill `kbo-lookup` + source `kbo_dump` (Open Data ZIP ingester) | +85 | 91% |
| 6 | `a9308c8` | Source `kbopub_html` (function holders / bestuurders) | +57 | 98% |
| 7 | `c279e09` | Skill `nbb-financials` + source `nbb_authentic` (REST API) | +54 | ≥90% |
| 8 | `5134c0e` | Skill `goudengids-listing` + source `goudengids` (Imperva-bypass) | +64 | 93% |
| 9 | (pending) | Skill `website-analysis` + source `website` (JSON-LD + heuristics + WHOIS) | +178 | 85% |

Also two doc commits: `9659c5d` (jq tooling), `b210d63` (prompt 2 deviation notes).

### Remaining

| # | Description | Estimated effort |
|---|---|---|
| 10 | Skill `search-cross-validation` + source `ddg_brave` (search-engine cross-checks) | 20-30 min |
| 11 | Pipeline + scoring + Streamlit UI (consolidation, sector × city smoke test) | 45-90 min |

## Key architectural decisions (locked in, do not revisit)

1. **Append-only observations.** No UPDATE on `observations` or `companies_current`. Multi-source provenance via separate observation rows. Materialised view `companies_current` recomputes via `refresh_companies_current()` function (CONCURRENTLY with unique index `(kbo_number, field)`).

2. **Per-host rate limits via TOML.** Goudengids 0.3 rps + concurrency 1 (Imperva-protected), kbopub 0.25 rps + concurrency 1, NBB CBSO 1.0 rps + concurrency 2, generic websites 0.5 rps + concurrency 2 (concurrency is per-host; fan-out across distinct hosts can run 15+ parallel).

3. **Confidence priors per source** (from `.claude/skills/provenance-schema/references/confidence.md`):
   - kbo_dump: 0.95-1.00, kbopub: 0.85-1.00, nbb_authentic: 1.00, goudengids: 0.80-0.85, website: 0.50-1.00 (JSON-LD 1.00, heuristic 0.50-0.60), ddg/brave: 0.50-0.55
   - Recency decay: `confidence * 0.99**days_since_obs` clamped `[0.30, 1.00]`
   - Consensus boost: `min(1.0, base * 1.1)` per cross-source agreement on same `(kbo, field, value)`

4. **No legal compliance scaffolding.** No robots.txt runtime check (deferred per user instruction prompt 2). No LIA, no opt-out, no transparency text. Testing-only context — user has separate legal advice.

5. **Synthetic placeholder KBOs** for sources without authoritative numbers (goudengids, search). Format: `f"9{abs(hash((normalized_name, postal_code))) % 10**9:09d}"`. Real KBOs start with `0` or `1`; placeholders start with `9` and fail mod-97 checksum, ensuring no collision. Consolidation pass in prompt 11 maps placeholders to real KBOs via fuzzy (name, postal_code, city) matching.

6. **TDD enforcement by hooks**, not honour-system. `.claude/hooks/tdd_gate.sh` blocks Write/Edit on `src/scraper/**` unless `tests/**` is also modified in the same change, AND blocks unless `.claude/plans/*.md` contains a plan with `Status: approved|in-progress`. Hooks require `jq` (installed via chocolatey).

7. **`stdnum.be.vat` for KBO validation** (mod-97 checksum, supports legacy `0xxx` and modern `1xxx`). `phonenumbers` for phone parsing. Never reimplement.

8. **Tests against disposable Postgres database.** `tests/integration/conftest.py` creates `leads_test_<timestamp>`, runs migrations, drops at teardown. Never points at dev `leads` DB.

## Environment

- Windows 11, Git Bash as default VS Code terminal (NOT PowerShell — bash hooks won't work)
- Python 3.12 via `uv` (system Python 3.14 is sidestepped)
- Docker Desktop with Postgres 16 in `be-leads-pg-1` at localhost:5432
- `jq` (chocolatey), Node.js 24, git 2.51
- Playwright Chromium installed (~150 MB at `~/AppData/Local/ms-playwright/`)

## API access status

- **KBO Open Data**: no account yet, no email confirmation received. Synthetic mini-ZIP fixture is sufficient for development. Real-world ingestion deferred to post-bootstrap.
- **NBB CBSO**: production keys ACTIVE for three products — Extracts, Authentic Archive Data, Authentic Data. Subscription `CLIENT-000605-SUB-000672`. Primary key for "Authentic Data" goes in `.env` as `NBB_CBSO_API_KEY=...`. Production endpoint: `ws.cbso.nbb.be`. UAT endpoint: `ws.uat2.cbso.nbb.be`.
- **Brave Search API**: not registered yet. Free tier 2k queries/month. Needed for prompt 10.
- **DuckDuckGo**: no key needed (via `ddgs` Python library). Rate-limited aggressively even at low volume.

## Pre-prompt-10 checklist

Before pasting prompt 10:

1. `git log --oneline` shows 11 commits (last: `skill: website-analysis + source: website (prompt 9)`)
2. `docker compose ps` shows `pg` healthy
3. Fresh `claude` session (not `--resume` — cleaner)
4. Confirm `.claude/settings.json` has been widened: previous session was prompting on every `Bash(python -c ...)` and `Bash(uv ...)` invocation, which kills flow. The patch is in chat history; not yet applied. Recommend applying before prompt 10 starts.

## Project memories (auto-persisted by Claude Code)

Location: `~/.claude/projects/C--Users-Oxfam-Documents-Saivy-Programs-be-leads/memory/`

Files:
- `MEMORY.md` — index
- `project_scaffold.md` — prompt 1 architecture decisions
- `feedback_polite_scraping_scope.md` — three prompt 2 deviations (no kbopub licence note, kbopub for KBO numbers too, no runtime robots.txt)
- `project_provenance.md` — prompt 3 schema decisions
- `project_phone.md` — prompt 4 validator (077-length fix)
- `project_kbo_dump.md` — prompt 5 architecture
- `project_kbopub.md` — prompt 6 parser
- `project_nbb.md` — prompt 7 client
- `project_goudengids.md` — prompt 8 Playwright/Imperva pattern
- `project_website.md` — prompt 9 fetcher gotcha (PoliteClient timeout already wired)

Every new Claude Code session reads these on startup — context inherited automatically.

## Discipline rules (have caught real bugs)

After every prompt, before letting Claude Code declare "ready for next":
1. Run `git log --oneline` to confirm commit landed
2. Run `uv run pytest -q -m "not network and not slow" 2>&1 | tail -5` to confirm test count
3. Run the per-prompt "eyeball" check (one `uv run python -c "..."` invocation that parses a golden fixture and prints the parsed structure)
4. Compare output against expected values. Specifically Bellock (KBO 0439401387) should reproduce on every prompt's golden fixture:
   - phone: `+3232361306` → fixed_line, region "Antwerp-Sint-Niklaas"
   - address: "Lange Van Bloerstraat 116, 2060 Antwerpen"
   - founding date: `1989-12-28`
   - directors: "Boonen, Jan" sinds 2024-03-27

This caught the 077-length bug in prompt 4 and would have caught field-shape regressions in 5, 6, 8.

## Open items / tech debt

- **Pydantic enum serialization unverified**: `PhoneType` enum in JSONB values — may store as `"PhoneType.FIXED_LINE"` (bad) instead of `"fixed_line"` (good). Check via `psql` query at first real ingestion.
- **`RuntimeWarning: coroutine '_run' was never awaited`** in some test output. Async fixture bug, doesn't affect correctness. Worth a cleanup pass after prompt 11.
- **Wayback CDX integration deferred** in prompt 9. Documented TODO in `age-heuristics.md`.
- **NACE zero-shot classification deferred**. Recommended path: `MoritzLaurer/bge-m3-zeroshot-v2.0` for industry compatibility, mapping to NACEBEL 2025 codes from Statbel XLSX. Out of scope for the 11-prompt sequence.
- **Settings.json permissioning**: still prompts for many Bash patterns. Patch in chat history widens this — apply before prompt 10.

## How to resume in new chat

Paste this entire file as your first message. Then paste prompt 10 when it's drafted.

For prompt 10:
- Skill `search-cross-validation` covering Brave Search API (free tier) + DuckDuckGo (via `ddgs` library, no key)
- Source `ddg_brave` queries by `"company name" city` and parses results for website + phone confirmation
- Used for cross-validating ambiguous goudengids placeholders before consolidation
- Synthetic placeholder KBO scheme reused
- 8 mocked fixture cases

For prompt 11 (the final integration):
- Pipeline orchestrator: schedules sources in dependency order (kbo_dump → kbopub_html → nbb_authentic → goudengids → website → ddg_brave)
- Consolidation pass: maps placeholder KBOs (9-prefix) to real KBOs via fuzzy match
- Scoring: applies recency decay + consensus boost; recomputes companies_current matview
- Streamlit UI: sector × city picker, run trigger, live progress, CSV download
- End-to-end smoke test: pick electricians in Antwerpen, run full pipeline, expect Bellock present with full data
