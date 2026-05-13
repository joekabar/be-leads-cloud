# Bootstrap Prompt 10 — Skill: `search-cross-validation` + Source: `ddg_brave`

> **How to use:** `be-leads/`, Git Bash, fresh `claude` session. Postgres up. Brave Search API key optional — paste from `=== PROMPT ===`.

---

=== PROMPT ===

You are adding the cross-validation source: `ddg_brave`. Given a company name + city (typically from a goudengids placeholder, or from a website-source observation lacking a real KBO), query free search engines, parse the top results, and emit observations that either confirm or disconfirm what other sources claim. This is the "is the phone number you see on goudengids actually associated with this company on the open web?" step.

Two engines, used in this priority order:
1. **Brave Search API** — free tier 2k queries/month, 1 qps. Requires `BRAVE_SEARCH_API_KEY`. Authoritative, clean JSON.
2. **DuckDuckGo** — via the `ddgs` library (PyPI: `ddgs`, the maintained successor to `duckduckgo-search`). No key. Aggressively rate-limited even at low volume — used only as a fallback when Brave is unavailable or quota-exhausted.

Tests are entirely mocked. No live search hits.

## Read first

- `CLAUDE.md`
- `agent_docs/architecture.md`, `agent_docs/runbook.md`
- `.claude/skills/polite-scraping/SKILL.md` — Brave 1.0 rps + concurrency 1, DDG 0.3 rps + concurrency 1
- `.claude/skills/provenance-schema/SKILL.md` — confidence priors for `brave` and `ddg` (0.50–0.55 — these sources are evidence-of-existence, NOT authority)
- `.claude/skills/website-analysis/SKILL.md` — how the consolidation step uses cross-source signals
- `.claude/skills/goudengids-listing/SKILL.md` — synthetic placeholder KBO scheme (you'll reuse it)
- `src/scraper/lib/http/client.py`
- `src/scraper/sources/goudengids/transformer.py` (placeholder-KBO pattern)
- Project memories at `~/.claude/projects/C--Users-Oxfam-Documents-Saivy-Programs-be-leads/memory/`

## Plan first

`.claude/plans/2026-05-10-ddg-brave.md`:
- Status: `approved`
- Goal: "Ship the `search-cross-validation` skill plus `ddg_brave` source. Given (company name, city) tuples, queries Brave Search API (primary) and DuckDuckGo (fallback), parses top-N organic results, classifies them as official-website / directory / social / other, and emits low-confidence observations that the consolidation pass uses to vote on website ownership and disambiguate placeholder KBOs."
- Scope in: skill SKILL.md + references (engines.md, result-classification.md, query-templates.md); source `src/scraper/sources/ddg_brave/` (brave_client, ddg_client, parser, transformer, ingester, cli); 6 mocked JSON fixtures (Brave responses) + 4 mocked HTML fixtures (DDG HTML); tests; CLAUDE.md/runbook/CHANGELOG.
- Out of scope: paid Brave tiers; SerpAPI / ScrapingBee escalation; Google CSE (out of free tier scope); SearXNG self-hosted (overkill); image/news verticals; LLM-based result reranking.
- Acceptance: skill loads on search-related prompts; Brave client builds correct request with `X-Subscription-Token` header; DDG client uses `ddgs` library async API; result classifier separates `official_website | directory | social | news | other` with rules in `references/result-classification.md`; transformer emits `website` observations at confidence 0.55 (Brave) / 0.50 (DDG) plus a `cross_validation` observation summarising the search hit count; idempotency via 7-day skip; mypy --strict clean; coverage on `src/scraper/sources/ddg_brave/` ≥ 85% (search APIs are I/O-bound, network mocking is tricky for full coverage).

## Pre-flight

```bash
docker compose up -d pg
uv run be-leads-migrate
uv run pytest -q -m "not network and not slow"   # 444 baseline (or 359 if prompt 9 isn't in)
```

## What to produce

### A. Skill: `.claude/skills/search-cross-validation/`

```
.claude/skills/search-cross-validation/
├── SKILL.md
├── references/
│   ├── engines.md
│   ├── result-classification.md
│   └── query-templates.md
└── scripts/
    └── probe_search.py
```

**SKILL.md frontmatter:**

```yaml
---
name: search-cross-validation
description: Cross-validate company information using free search engines. Primary engine is Brave Search API (free tier 2k queries/month, requires BRAVE_SEARCH_API_KEY); fallback is DuckDuckGo via the `ddgs` Python library (no key, rate-limited). Use whenever the user wants to confirm a company's website, disambiguate a placeholder KBO, check whether a phone number appears alongside a company name on the open web, or score the "evidence of existence" of a Belgian SME. The skill classifies each result URL into official_website | directory | social | news | other and emits LOW-confidence (0.50-0.55) observations — these are evidence signals, never authority.
allowed-tools: Read, Edit, Bash, WebFetch(domain:api.search.brave.com), WebFetch(domain:duckduckgo.com), Bash(uv run python:*), Bash(uv run pytest:*), Bash(uv run be-leads-search-validate:*)
---
```

**SKILL.md body** sections:

1. **When to use.** Cross-validation of any other source's claim; resolving placeholder KBOs; confirming website ownership; "does this phone appear with this name on the web?"
2. **Two engines, priority order.**
   - **Brave Search API** first: cleaner, JSON, predictable rate limits. Free tier: 2000 queries/month, 1 qps, no card required, register at `https://api.search.brave.com/app`. Used for ≥95% of queries.
   - **DuckDuckGo** as fallback only: HTML parsing via the `ddgs` library; rate-limits aggressively (5-10 queries before throttling); use when Brave is down, quota-exhausted, or for queries Brave returns no results for.
3. **Confidence priors.** Brave: 0.55. DDG: 0.50. Recency decay applies (search results staler than 30 days lose value). Cross-source consensus boost (×1.1) when same URL appears in both engines for the same query.
4. **Result classification.** Pointer to `references/result-classification.md`. Five buckets: `official_website` (domain matches company name, .be TLD preferred), `directory` (goudengids, pagesdor, kompass, europages, etc.), `social` (facebook, linkedin, instagram, etc.), `news` (article URLs), `other`. Only `official_website` and `directory` produce observations; the others are stored in the `cross_validation` JSONB summary only.
5. **Query templates.** Pointer to `references/query-templates.md`. Three patterns: `"{name}" {city}`, `"{name}" {city} site:.be`, `"{name}" {phone}` (when phone known). Run the first by default; the others on demand.
6. **Rate.** Brave 1.0 rps + concurrency 1. DDG 0.3 rps + concurrency 1. Both enforced by polite-scraping skill via `per-host.toml`.
7. **What NOT to do.**
   - Don't query Google. Even via DDG or Brave, never scrape `google.com` — instant block.
   - Don't query Bing. The API was retired in August 2025; no replacement.
   - Don't store snippets verbatim. Search engines copyright them; store only URL + parsed title.
   - Don't escalate to paid SerpAPI / ScrapingBee. Out of scope; if you hit the quota, document the gap.
   - Don't use search results as authority. They are evidence signals, never canonical.

**`references/engines.md`** — operational specs:

```
## Brave Search API
Base URL: https://api.search.brave.com/res/v1/web/search
Auth: header `X-Subscription-Token: <key>`
Required headers:
  Accept: application/json
  Accept-Encoding: gzip
Query params:
  q          (string, required)         the search query
  count      (int, default 10, max 20)  number of results
  offset     (int, default 0)           for pagination — DO NOT USE (quota waste)
  country    (string, default ALL)      pass "BE" for Belgian-biased results
  search_lang (string, default en)      pass "nl" or "fr" for Dutch/French biasing
  safesearch  (string, default moderate) keep default
  freshness   (string)                   omit for our use case
  result_filter (string, default web)    keep default
Free tier limits:
  - 2,000 queries per month
  - 1 query per second
  - No card required for signup
  - HTTP 429 when over QPS; HTTP 403 when monthly quota exhausted
Response shape (Brave 2026):
  {
    "type": "search",
    "web": {
      "type": "search",
      "results": [
        {
          "type": "search_result",
          "title": "string",
          "url": "https://...",
          "is_source_local": false,
          "description": "string (snippet — do NOT store)",
          "language": "nl",
          "profile": {"name": "...", "long_name": "..."},
          "family_friendly": true
        },
        ...
      ]
    }
  }
We parse only: title, url, language. Description discarded.

## DuckDuckGo (via `ddgs` Python library)
Library: `ddgs` on PyPI (NOT `duckduckgo-search` — that name was deprecated; both work but `ddgs` is the maintained one).
Usage pattern:
  from ddgs import DDGS
  with DDGS() as ddg:
      results = ddg.text(query, max_results=10, region="be-nl", safesearch="moderate")
Result shape:
  [{"title": "string", "href": "https://...", "body": "snippet"}, ...]
Rate limit observed: requests fail with RatelimitException after 5-10 requests in a short window.
Mitigations:
  - Wait 60s between requests (we use 0.3 rps = 3.3s spacing, safer)
  - Rotate User-Agent (ddgs handles internally if `proxy=` is set; we don't use proxies)
  - On RatelimitException: sleep 60s, retry once; on second RatelimitException, fail this query, continue.
The ddgs library is SYNCHRONOUS. Wrap its calls in asyncio.to_thread().
```

**`references/result-classification.md`** — the classifier rules:

```
## Bucket: official_website
Heuristic: domain (stripped of www., port, path) matches the company name normalised.
Normalisation: lowercase, strip diacritics, strip spaces/dashes/dots, strip common Belgian legal-form suffixes (bv, nv, sa, sprl, srl, bvba, cvba, scrl, comm.v., commv).

Examples:
  Bellock → official: bellock.be, bellock-elektriciteit.be, bellockantwerpen.be ✓
  Bellock → NOT official: bellock.facebook.com, bellockcars.com (different company on .com TLD without strong signal)

Tie-breakers when multiple plausible matches:
  1. .be TLD wins over .com / .eu / others
  2. shorter domain wins
  3. https wins over http (sanity)

## Bucket: directory
Domain in the closed list (from goudengids-listing skill's SKIP_DOMAINS plus a few search-specific):
  goudengids, pagesdor, goldenpages, kbo, kompass, europages, trustlocal,
  companyweb, bizzy, trendstop.knack, opencorporates, dnb, theorg,
  freightnet, panjiva, exporthub, b2bhint, namesdir, radaris, cybo,
  marketinsider, glassdoor, indeed

## Bucket: social
Domain in:
  facebook, linkedin, instagram, twitter, x.com, youtube, tiktok,
  pinterest, vimeo, foursquare, snapchat

## Bucket: news
Path contains `/article/`, `/nieuws/`, `/actualite/`, OR domain in:
  vrt, hln, demorgen, standaard, tijd, knack, lalibre, lesoir, rtbf, sudinfo

## Bucket: other
Everything else. Includes Wikipedia (encyclopedia, not company info per se),
forums, blog posts, government portals.

## Per-bucket action
official_website  → emit `website` observation (confidence per source)
directory         → emit `cross_validation` JSONB summary entry only (NOT a website obs)
social            → store in cross_validation.social_links list
news              → store in cross_validation.news_mentions count
other             → ignored
```

**`references/query-templates.md`**:

```
## Template 1 (default): name+city
  Brave: `"{name}" {city}` country=BE search_lang={nl|fr based on detected source language}
  DDG:   `"{name}" {city}` region=be-{nl|fr}

## Template 2 (on-demand): name+city+site:.be
  Brave: `"{name}" {city} site:.be`
  DDG:   `"{name}" {city} site:.be`
Use when template 1 returns 0 results or when the user is looking specifically
for the official .be presence.

## Template 3 (on-demand): name + phone
  Brave: `"{name}" "{phone_e164_no_spaces}"`
  DDG:   `"{name}" "{phone_pretty}"`
Use to validate that a phone number is associated with the company name on the
open web. Strong evidence when ≥2 results from independent domains contain both.

## Query budgeting
Brave free tier = 2000/month ≈ 65/day. For one-sector-one-city runs of
~50 companies, budget 1.5 queries/company (1 default + 0.5 conditional).
That allows ~43 company runs per day without DDG fallback. DDG plugged in
beyond that.

## Name normalisation in queries
Always wrap name in double quotes: `"Bellock"` (Brave respects this).
Strip legal-form suffixes from the QUOTED name (not from city/extra terms).
City is unquoted: `Antwerpen` not `"Antwerpen"`.
```

**`scripts/probe_search.py`** — small CLI that takes name+city, runs one Brave query if `BRAVE_SEARCH_API_KEY` is set, falls back to DDG otherwise, prints classified results. Used for manual dev. ≤40 lines.

### B. Source: `src/scraper/sources/ddg_brave/`

```
src/scraper/sources/ddg_brave/
├── __init__.py
├── brave_client.py       # async Brave Search API client
├── ddg_client.py         # ddgs library async wrapper (asyncio.to_thread)
├── parser.py             # JSON / HTML → typed SearchResult list
├── classifier.py         # SearchResult → bucket
├── transformer.py        # SearchResult list → Observation list
├── ingester.py           # orchestrate per-(name,city) lookup
└── cli.py                # be-leads-search-validate
```

#### brave_client.py

```python
class BraveAuthError(ScraperError): ...
class BraveQuotaExhausted(ScraperError): ...      # 403 from Brave
class BraveRateLimited(ScraperError): ...          # 429 from Brave

class BraveClient:
    def __init__(
        self,
        polite_client: PoliteClient,
        subscription_key: str,
        *,
        country: str = "BE",
    ) -> None: ...

    async def search(
        self,
        query: str,
        *,
        count: int = 10,
        search_lang: Literal["nl", "fr", "en"] = "nl",
    ) -> dict[str, Any]:
        """Returns raw Brave JSON payload. Raises BraveQuotaExhausted on 403."""
```

Implementation:
- Build query params via `urllib.parse.urlencode`.
- Headers: `Accept: application/json`, `Accept-Encoding: gzip`, `X-Subscription-Token: {key}`.
- Route via `polite_client` so the per-host limiter applies (`api.search.brave.com`).
- Map status codes: 401 → BraveAuthError, 403 → BraveQuotaExhausted, 429 → BraveRateLimited (allow retry one level up).

#### ddg_client.py

```python
class DdgRateLimitedError(ScraperError): ...

class DdgClient:
    def __init__(self, region: str = "be-nl") -> None: ...

    async def search(
        self,
        query: str,
        *,
        max_results: int = 10,
    ) -> list[dict[str, str]]:
        """Wraps `ddgs.DDGS.text` in asyncio.to_thread. Returns list of {title, href, body}.
        Raises DdgRateLimitedError on ddgs RatelimitException."""
```

Implementation:
- Import `ddgs` lazily (so the test suite doesn't crash if it isn't installed yet — though it should be in the lockfile).
- Use `asyncio.to_thread()` to wrap the synchronous `DDGS.text()` call.
- On `ddgs.exceptions.RatelimitException`, sleep 60s and retry once; on second failure raise `DdgRateLimitedError`.
- Set `region="be-nl"` for NL queries, `"be-fr"` for FR.

Add `ddgs` to runtime dependencies in `pyproject.toml` if not already present. Check first; don't blindly add.

#### parser.py

```python
@dataclass(frozen=True, slots=True)
class SearchResult:
    title: str
    url: str
    domain: str              # parsed netloc, lowercased, www. stripped
    language: str | None
    engine: Literal["brave", "ddg"]

def parse_brave(payload: dict[str, Any]) -> list[SearchResult]: ...
def parse_ddg(results: list[dict[str, str]]) -> list[SearchResult]: ...
```

Implementation:
- Brave: walk `payload["web"]["results"]`, extract title/url/language.
- DDG: each dict has `title`, `href`, `body`. Discard body. Map `href` to url.
- Both: parse domain via `urllib.parse.urlparse`, lowercase, strip `www.`.

#### classifier.py

```python
@dataclass(frozen=True, slots=True)
class ClassifiedResult:
    result: SearchResult
    bucket: Literal["official_website", "directory", "social", "news", "other"]

DIRECTORY_DOMAINS: frozenset[str] = frozenset({...})  # from result-classification.md
SOCIAL_DOMAINS: frozenset[str] = frozenset({...})
NEWS_DOMAINS: frozenset[str] = frozenset({...})

def normalize_name(name: str) -> str:
    """Lowercase, strip diacritics via unicodedata.normalize NFD then ascii encode,
    strip spaces/dashes/dots, strip common Belgian legal-form suffixes."""

def classify(
    result: SearchResult,
    company_name: str,
) -> ClassifiedResult: ...
```

Order of classification checks: `social` → `directory` → `news` → `official_website` (if domain stem matches normalized name) → `other`.

This order is intentional: a result on facebook.com containing the company name should go in `social`, not `official_website`.

#### transformer.py

```python
@dataclass(frozen=True, slots=True)
class SearchCrossValidation:
    """Summary across all classified results for one (name, city) query."""
    query: str
    engine: Literal["brave", "ddg"]
    official_websites: list[str]       # URLs, deduplicated
    directory_hits: list[str]
    social_links: list[str]
    news_mentions: int                  # count only
    total_results: int
    snapshot_at: datetime

def query_to_observations(
    kbo_number: str,
    company_name: str,
    query: str,
    engine: Literal["brave", "ddg"],
    results: list[ClassifiedResult],
    run_id: UUID,
    snapshot_at: datetime,
) -> list[Observation]: ...
```

Behaviour:
- For each `official_website` in `results`: emit one `website` observation. JSONB shape: `{"url": "...", "tld": "be", "via_search": True, "search_engine": "brave"}`. Confidence: 0.55 (Brave) or 0.50 (DDG).
- Emit ONE summary `cross_validation` observation regardless of result count. JSONB shape:
  ```json
  {
    "query": "Bellock Antwerpen",
    "engine": "brave",
    "total_results": 8,
    "official_websites_count": 1,
    "directory_hits_count": 3,
    "social_links_count": 2,
    "news_mentions": 0,
    "first_official_website": "https://bellock.be",
    "snapshot_at": "2026-05-12T15:30:00Z"
  }
  ```
  Confidence: 0.55 (Brave) / 0.50 (DDG). Field name: `cross_validation`.
- Update `provenance-schema/SKILL.md` section 7 to add the `cross_validation` field type — read that skill first and append a JSONB shape entry, not just edit the source.

Source: `"brave"` or `"ddg"`. Source URL: the search-results URL (Brave doesn't publish a stable one, so use `https://api.search.brave.com/res/v1/web/search?q={quoted}`).

The KBO passed in may be a real KBO OR a 9-prefix placeholder (when cross-validating an unattributed result). Both are valid.

#### ingester.py

```python
@dataclass
class SearchValidationReport:
    queries_processed: int
    brave_queries: int
    ddg_queries: int
    brave_quota_exhausted: bool
    observations_inserted: int
    websites_confirmed: int
    duration_s: float

async def validate_companies(
    company_inputs: list[tuple[str, str, str]],  # (kbo_number, company_name, city)
    pool: asyncpg.Pool,
    polite_client: PoliteClient,
    *,
    brave_client: BraveClient | None,
    ddg_client: DdgClient | None,
    skip_recent_hours: int = 168,    # 7 days
    use_ddg_fallback: bool = True,
) -> SearchValidationReport: ...
```

Behaviour per company:
1. 7-day skip check (any `brave` OR `ddg` observation within window → skip).
2. Try Brave first if `brave_client` is set. On `BraveQuotaExhausted`: mark report flag, stop using Brave for rest of batch.
3. If Brave returned 0 results OR Brave is unavailable: try DDG (only if `use_ddg_fallback=True` and `ddg_client` is set).
4. Classify, transform, accumulate.
5. Bulk insert every 50 observations.
6. After batch: refresh matview.

Use template 1 (`"{name}" {city}`) by default. Template 2 and 3 are exposed in the CLI for ad-hoc runs but not in the default batch flow (preserve query quota).

#### cli.py

`be-leads-search-validate`:
- `--inputs <file>` (TSV: `kbo<TAB>name<TAB>city` per line)
- `--from-db` (alternative: pulls candidates from `companies_current` where source=goudengids AND kbo_number starts with '9' — placeholder needing resolution)
- `--limit N`
- `--engine brave|ddg|auto` (default auto: brave→ddg fallback)
- `--template 1|2|3` (default 1)
- `--skip-recent-hours N` (default 168)
- `--brave-key K` (or env `BRAVE_SEARCH_API_KEY`)
- `--database-url <DSN>`

Register in `pyproject.toml`:
```
be-leads-search-validate = "scraper.sources.ddg_brave.cli:cli_main"
```

### C. Fixtures

```
tests/golden/ddg_brave/
├── README.md
├── brave_bellock_antwerpen.json          # 8 results: 1 official, 3 directory, 2 social, 0 news, 2 other
├── brave_bakk_brugge.json                 # 5 results: 1 official, 2 directory, 0 social, 1 news, 1 other
├── brave_no_results.json                  # web.results = []
├── brave_quota_exhausted.json             # status 403 simulated payload
├── brave_legal_form_suffix.json           # Company "Acme BV" → official site "acme.be" — must match
├── brave_ambiguous_name.json              # 2 candidates, longer .com vs shorter .be — .be wins
├── ddg_bellock_html.json                  # ddgs-style list-of-dicts return for Bellock
└── ddg_ratelimit.json                     # simulates RatelimitException — fixture is empty list with metadata
```

Hand-construct the JSON. Realistic values:

- `brave_bellock_antwerpen.json`:
  - results[0]: title="Bellock - Elektriciteit Antwerpen", url="https://www.bellock.be/", language="nl"
  - results[1]: title="Bellock op Goudengids", url="https://www.goudengids.be/bedrijf/Antwerpen/L389732/Bellock/"
  - results[2]: title="Bellock | Pages d'Or", url="https://www.pagesdor.be/societe/..."
  - results[3]: title="Bellock - Kompass", url="https://be.kompass.com/c/bellock/..."
  - results[4]: title="Bellock - Facebook", url="https://www.facebook.com/bellock.electriciteit/"
  - results[5]: title="Bellock - LinkedIn", url="https://www.linkedin.com/company/bellock/"
  - results[6]: title="Antwerpse elektriciens vergeleken", url="https://elektriciensblog.example/antwerpen/", language="nl"
  - results[7]: title="Buurt-Wikipedia: Lange Van Bloerstraat", url="https://nl.wikipedia.org/wiki/Lange_Van_Bloerstraat"

- `brave_legal_form_suffix.json`: company "Acme BV" with results[0] url="https://www.acme.be/" — classifier must strip the "BV" suffix from "Acme BV" before comparing to "acme.be".

- `brave_ambiguous_name.json`: company "Mediapro" with results[0]="https://www.mediapro.com/" and results[1]="https://www.mediapro.be/" — .be MUST win per tie-breaker rules.

- `ddg_bellock_html.json`: stored as JSON for test simplicity, format matches what `ddgs.DDGS.text()` returns (list of `{"title","href","body"}`).

### D. Tests

```
tests/unit/sources/ddg_brave/
├── __init__.py
├── test_parser.py
├── test_classifier.py
└── test_transformer.py
tests/integration/sources/ddg_brave/
├── __init__.py
├── conftest.py
├── test_brave_client.py        # respx-mocked Brave
├── test_ddg_client.py          # monkeypatched ddgs
├── test_ingester.py            # full flow against test DB
└── test_cli.py
```

Required cases:

`test_parser.py`:
- `parse_brave(brave_bellock_antwerpen.json)` → 8 SearchResult, domains stripped of www., language preserved.
- `parse_brave(brave_no_results.json)` → empty list, no error.
- `parse_ddg(ddg_bellock_html.json)` → list with correct domains.
- Brave payload missing `web` key → empty list, warn-logged.

`test_classifier.py`:
- Bellock fixture, company name "Bellock":
  - bellock.be → `official_website`
  - goudengids.be → `directory`
  - facebook.com → `social`
  - elektriciensblog.example → `other`
  - nl.wikipedia.org → `other`
- Legal-form suffix: company "Acme BV", domain "acme.be" → `official_website`.
- Ambiguous: company "Mediapro", domains "mediapro.com" + "mediapro.be" → BOTH classify as official_website (transformer dedups and picks by tie-breakers). Test the classifier returns both as `official_website`.
- Social-before-official ordering: a result on `facebook.com/bellock.electriciteit` does NOT classify as official_website even though "bellock" is in the URL — must be social.
- Diacritic normalisation: company "Bückens & Zoon", domain "buckens-zoon.be" → `official_website` (NFD diacritic strip).
- Empty company name → ValueError.

`test_transformer.py`:
- Bellock results → 1 `website` observation (the .be one) + 1 `cross_validation` summary observation. Total 2.
- Confidence on website: 0.55 (Brave) / 0.50 (DDG).
- Synthetic placeholder KBO accepted as kbo_number input.
- The `cross_validation` JSONB has correct counts: official_websites_count=1, directory_hits_count=3, social_links_count=2, news_mentions=0.
- No results → 1 `cross_validation` observation (counts all zero), 0 `website` observations.

`test_brave_client.py`:
- Mock 200 response → returns the parsed dict.
- Mock 401 → `BraveAuthError`.
- Mock 403 → `BraveQuotaExhausted`.
- Mock 429 → `BraveRateLimited` raised (caller decides retry).
- Verify request headers include `X-Subscription-Token` and `Accept: application/json`.
- Verify URL contains `q=` URL-encoded, `country=BE`, `count=10`.

`test_ddg_client.py`:
- Monkeypatch `ddgs.DDGS.text` to return the fixture list → DdgClient returns the same list.
- Monkeypatch to raise `RatelimitException` → first call sleeps 60s (use `monkeypatch.setattr(asyncio, "sleep", AsyncMock())` to skip real wait), retries once, succeeds.
- Second consecutive `RatelimitException` → raises `DdgRateLimitedError`.

`test_ingester.py`:
- 5 mocked (name, city) inputs → N observations, 5 cross_validation summaries.
- Brave quota exhausted after 2nd query → switches to DDG for remaining 3, report flag set.
- `use_ddg_fallback=False` + Brave exhausted → batch stops cleanly.
- Re-run within 7 days → 0 new observations.
- One input with empty results → 0 website observations + 1 cross_validation observation.

`test_cli.py`:
- `--inputs <tsv>` with mocked HTTP → exit 0, report on stdout.
- `--engine ddg` forces DDG-only path.
- `--from-db` flag pulls placeholder KBOs from the test DB.

### E. Update agent_docs/runbook.md

```
## Brave Search API — registration

1. Go to https://api.search.brave.com/app
2. Sign up (no credit card required for the free tier).
3. Create a subscription: "Data for Search" → free 2k/month.
4. Copy the subscription key.
5. Add to .env:
       BRAVE_SEARCH_API_KEY=<key>
6. Verify:
       uv run python .claude/skills/search-cross-validation/scripts/probe_search.py "Bellock" "Antwerpen"

## Quota budgeting
Free tier: 2000 queries / month ≈ 65 / day average.
One default ingest run of 50 companies in one sector × city ≈ 50-75 Brave queries.
That's ~25 sector-city runs per month on Brave alone. Beyond that, DDG fallback engages.

## DuckDuckGo fallback
No registration. Rate-limited aggressively — practical ceiling 100-200 queries per day
before sustained blocks. Use only when Brave is exhausted or unavailable.

## Cross-validation invocation
    # by file
    echo -e "0439401387\tBellock\tAntwerpen" > /tmp/cv.tsv
    uv run be-leads-search-validate --inputs /tmp/cv.tsv

    # from DB (placeholder KBOs from goudengids)
    uv run be-leads-search-validate --from-db --limit 50
```

### F. Update CLAUDE.md

Under "## Per-source knowledge":
```
- Search cross-validation rules: `.claude/skills/search-cross-validation/SKILL.md` (active)
```

Under "## Anti-patterns":
```
- Treating search-engine observations as authority. They are evidence signals (confidence 0.50-0.55), never canonical. Never write code that resolves conflicts by trusting a search hit over KBO/NBB/goudengids.
```

### G. Update .env.example

Activate (keep value blank):
```
BRAVE_SEARCH_API_KEY=
```

### H. Update CHANGELOG

```
### Added
- Skill: `search-cross-validation` with engines.md, result-classification.md, query-templates.md.
- Source: `ddg_brave` — Brave Search API client (primary) + DuckDuckGo via `ddgs` library (fallback). Per-result classifier into official_website / directory / social / news / other.
- New observation field type: `cross_validation` (summary of one search query's classified results).
- 8 mocked fixtures (Brave JSON + DDG list responses).
- CLI: `uv run be-leads-search-validate --inputs <file>` or `--from-db --limit N`.
- .env.example: BRAVE_SEARCH_API_KEY entry activated.
```

### I. Update `provenance-schema` skill

Read `.claude/skills/provenance-schema/SKILL.md`. Append to section 5 ("What field means") the `cross_validation` field name. Append to section 7 (JSONB shapes) the cross_validation JSONB structure documented above.

ALSO: add `cross_validation` to the `ALLOWED_FIELDS` frozenset in `src/scraper/db/fields.py`. AND add `"brave"` and `"ddg"` to `ALLOWED_SOURCES` in `src/scraper/db/sources.py` IF they are not already there (they should be — check first). Don't blindly add; verify.

## Verification

```bash
docker compose up -d pg
uv sync --locked --dev
uv run pytest -q -m "not network and not slow"
uv run pytest --cov=src/scraper/sources/ddg_brave --cov-fail-under=85 -q tests/unit/sources/ddg_brave tests/integration/sources/ddg_brave
uv run mypy src/scraper
uv run ruff check src/scraper tests
uv run ruff format --check src/scraper tests

# Eyeball: classifier on Bellock fixture
uv run python -c "
import json
from pathlib import Path
from scraper.sources.ddg_brave.parser import parse_brave
from scraper.sources.ddg_brave.classifier import classify

payload = json.loads(Path('tests/golden/ddg_brave/brave_bellock_antwerpen.json').read_text())
results = parse_brave(payload)
for r in results:
    c = classify(r, 'Bellock')
    print(f'  {c.bucket:18s} {r.domain:40s} {r.title[:50]}')
"

# Eyeball: transformer + summary observation
uv run python -c "
import json
from pathlib import Path
from uuid import uuid4
from datetime import datetime
from scraper.sources.ddg_brave.parser import parse_brave
from scraper.sources.ddg_brave.classifier import classify
from scraper.sources.ddg_brave.transformer import query_to_observations

payload = json.loads(Path('tests/golden/ddg_brave/brave_bellock_antwerpen.json').read_text())
results = parse_brave(payload)
classified = [classify(r, 'Bellock') for r in results]
obs = query_to_observations('0439401387', 'Bellock', '\"Bellock\" Antwerpen', 'brave', classified, uuid4(), datetime.now())
print(f'{len(obs)} observations emitted')
for o in obs:
    print(f'  {o.field} (conf={o.confidence}): {str(o.value)[:140]}')
"
```

Expected:
- First block: 8 lines, one per result, showing each domain's classification. Specifically:
  - `official_website` for `bellock.be`
  - `directory` for `goudengids.be`, `pagesdor.be`, `be.kompass.com`
  - `social` for `facebook.com`, `linkedin.com`
  - `other` for the blog and Wikipedia
- Second block: 2 observations — 1 `website` (Bellock URL, confidence 0.55) and 1 `cross_validation` (summary with counts).

## Stop conditions

When green:
1. Print summary: new files, tests passing on ddg_brave, coverage, verbatim output of both `python -c` blocks.
2. Print: `Ready for prompt 11 (pipeline + scoring + Streamlit UI). Commit: git add . && git commit -m "skill: search-cross-validation + source: ddg_brave (prompt 10)".`
3. End the turn.

## Things you must NOT do

- Do not hit live Brave or live DDG. Tests use respx for Brave and monkeypatched `ddgs.DDGS.text` for DDG.
- Do not query Google or Bing. Both are out — Google blocks, Bing API retired August 2025.
- Do not store snippet/description text. Title + URL only.
- Do not treat search results as authoritative. Confidence is 0.50-0.55, full stop.
- Do not implement SerpAPI / ScrapingBee escalation. Out of scope.
- Do not paginate Brave (offset > 0). Burns quota.
- Do not implement query expansion / synonyms. Out of scope.
- Do not modify existing sources or http module.
- Do not let DDG's synchronous library block the event loop. Always wrap in `asyncio.to_thread()`.
- Do not add `ddgs` as a dev dependency. It belongs in runtime deps because the source uses it.
