---
name: search-cross-validation
description: Cross-validate company information using free search engines. Primary engine is Brave Search API (free tier 2k queries/month, requires BRAVE_SEARCH_API_KEY); fallback is DuckDuckGo via the `ddgs` Python library (no key, rate-limited). Use whenever the user wants to confirm a company's website, disambiguate a placeholder KBO, check whether a phone number appears alongside a company name on the open web, or score the "evidence of existence" of a Belgian SME. The skill classifies each result URL into official_website | directory | social | news | other and emits LOW-confidence (0.50-0.55) observations — these are evidence signals, never authority.
allowed-tools: Read, Edit, Bash, WebFetch(domain:api.search.brave.com), WebFetch(domain:duckduckgo.com), Bash(uv run python:*), Bash(uv run pytest:*), Bash(uv run be-leads-search-validate:*)
---

## When to use

Use this skill whenever you:
- Cross-validate a phone number, website, or name claim from another source (goudengids, kbopub)
- Resolve a placeholder KBO (9-prefix) to a potential real company
- Confirm a company's official website from the open web
- Check whether a phone number appears alongside a company name on the open web

Never use search results as the authoritative source for a fact. These observations vote,
they don't decide. See confidence priors in section 4.

## Two engines, priority order

### 1. Brave Search API (primary, ≥95% of queries)

Brave is used first. Cleaner JSON, predictable rate limits, no anti-bot friction.
See `references/engines.md` for full API spec and response shape.

- Free tier: 2 000 queries / month, 1 qps, no card required
- Register at https://api.search.brave.com/app
- Set `BRAVE_SEARCH_API_KEY` in `.env`

### 2. DuckDuckGo via `ddgs` library (fallback only)

Used when Brave is unavailable or quota-exhausted. The `ddgs` library is synchronous;
wrap every call in `asyncio.to_thread()`. Rate-limits aggressively — practical ceiling
100–200 queries per day before sustained blocks.

- No key required
- On `RatelimitException`: sleep 60 s, retry once; on second failure raise `DdgRateLimitedError`
- See `references/engines.md` for library usage pattern

## Confidence priors

| Source | Prior | Notes |
|--------|-------|-------|
| brave  | 0.55  | clean JSON, predictable |
| ddg    | 0.50  | baseline evidence only |

Recency decay applies (as in provenance-schema skill §4).
Cross-source consensus boost (×1.1) when same URL appears in both engines for the same query.

## Result classification

Five buckets — see `references/result-classification.md` for full rules.

| Bucket | Action |
|--------|--------|
| `official_website` | emit `website` observation at source confidence |
| `directory` | store in `cross_validation` summary only |
| `social` | store in `cross_validation.social_links` list |
| `news` | increment `cross_validation.news_mentions` count |
| `other` | ignored |

Classification order: **social → directory → news → official_website → other**.
A result on facebook.com/bellock is social, not official_website, even though "bellock"
appears in the URL.

## Query templates

See `references/query-templates.md` for the three patterns.
Default (batch): Template 1 — `"{name}" {city}`. Templates 2 and 3 are on-demand only.

## Rate limits

| Host | rps | concurrency |
|------|-----|-------------|
| api.search.brave.com | 1.0 | 1 |
| duckduckgo.com | 0.3 | 1 |

Enforced by the polite-scraping skill via per-host TOML.

## What NOT to do

- **Don't query Google.** Even via DDG or Brave, never scrape google.com.
- **Don't query Bing.** The API was retired August 2025.
- **Don't store snippets verbatim.** Store only URL + title — search engines copyright snippets.
- **Don't escalate to paid SerpAPI / ScrapingBee.** Out of scope.
- **Don't use search results as authority.** Confidence 0.50–0.55, full stop.
- **Don't paginate Brave** (`offset > 0`). Burns quota.
- **Don't implement query expansion or synonyms.** Out of scope.
