# Bootstrap Prompt 2 — Skill: `polite-scraping`

> **How to use:** in your existing `be-leads/` directory, in a Git Bash terminal inside VS Code, run `claude` (or `claude --resume` to continue the previous session). Paste everything below the `=== PROMPT ===` line. When it stops, review and commit, then move to prompt 3.

---

=== PROMPT ===

You are adding the first custom skill to the `be-leads` repository: `polite-scraping`. This skill is foundational — every subsequent source (KBO, NBB, goudengids, websites, search) will reference it. Do nothing outside the scope listed here.

## Read first

Before doing anything, read these files to ground yourself:
- `CLAUDE.md`
- `agent_docs/architecture.md`
- `.claude/plans/_template.md`
- `.claude/settings.json` (review the hooks section)

## Plan first

Create `.claude/plans/2026-05-10-polite-scraping.md` from the template with:
- Status: `approved` (you self-approve here so the TDD hook unblocks; the user has already seen this prompt)
- Goal: "Ship the `polite-scraping` skill plus the supporting Python module `src/scraper/lib/http/` (client, limiter, retry, robots) it documents, with full test coverage for the limiter, retry, and robots logic."
- Scope in: skill SKILL.md + supporting files; `src/scraper/lib/http/` module; `src/scraper/lib/errors.py` (typed exceptions used by retry); tests.
- Out of scope: any source-specific code (no goudengids, no kbo, no nbb); no Playwright integration (deferred to the goudengids prompt); no caching layer (deferred).
- Acceptance: skill file exists with valid YAML frontmatter; `src/scraper/lib/http/limiter.py`, `retry.py`, `robots.py`, `client.py` all importable; tests in `tests/unit/lib/http/` cover ≥90% of those four modules; `mypy --strict` clean; one integration test (marked `network`) hits `https://example.com/` and asserts polite behaviour.

## What to produce

### A. The skill: `.claude/skills/polite-scraping/`

Directory layout:
```
.claude/skills/polite-scraping/
├── SKILL.md
├── references/
│   ├── per-host.toml
│   ├── headers.md
│   └── status-codes.md
└── scripts/
    └── check_robots.py
```

**`SKILL.md` — frontmatter exactly:**

```yaml
---
name: polite-scraping
description: Apply rate limiting, exponential backoff with jitter, robots.txt compliance, Retry-After honoring, and per-host concurrency limits to all outbound HTTP. Defines token-bucket defaults per host (goudengids, kbopub, NBB CBSO, generic websites) and the rules for when to escalate from httpx to Playwright. Use whenever the user adds an HTTP call, sees 429/503/403 errors, asks about rate limits, modifies anything in src/scraper/lib/http/, or builds a new source module under src/scraper/sources/. Always consult the per-host TOML before guessing a rate.
allowed-tools: Read, Edit, Bash(uv run python:*), Bash(uv run pytest:*)
---
```

**`SKILL.md` body** — six sections, each ≤15 lines, no fluff:

1. **When to use** — one paragraph reiterating the trigger conditions.
2. **Per-host defaults** — points to `references/per-host.toml`. Quick table summary in markdown:

   | Host | rps | concurrency | notes |
   |---|---|---|---|
   | goudengids.be | 0.3 | 1 | Imperva — bursts ban IP |
   | pagesdor.be | 0.3 | 1 | same parent |
   | kbopub.economie.fgov.be | 0.25 | 1 | license forbids systematic download; reserve for function-holder lookups |
   | ws.cbso.nbb.be | 1.0 | 2 | requires registered API key (NBB Authentic Data Query, free) |
   | api.search.brave.com | 1.0 | 1 | free tier 2k/month |
   | duckduckgo.com | 0.3 | 1 | even this rate-limits in 2026 |
   | web.archive.org (CDX) | 0.8 | 1 | 60 req/min hard ceiling |
   | default | 0.5 | 2 | per host, distinct hosts can run in parallel |

3. **Token bucket** — one-paragraph algorithm pointer to `src/scraper/lib/http/limiter.py`. Mention that `acquire()` is async, blocks until a slot is free, and is per-host keyed on the URL netloc.
4. **Backoff with jitter** — formula: `delay = min(60, base * 2**attempt) + uniform(0, jitter)` with `base=1.0, jitter=0.3, max_attempts=5`. Retry only on 429/503/504. Honour `Retry-After` (both seconds-int and HTTP-date forms). **Never retry on 403** — escalate.
5. **Status-code playbook** — table referencing `references/status-codes.md`.
6. **Escalate-to-Playwright triggers** — three conditions:
   - HTML <500 bytes containing `incapsula|imperva|captcha|toegang geweigerd|pardon our interruption`
   - 3 consecutive 403s on the same host within 10 minutes
   - Detail page known to be JS-rendered with no XHR alternative

**`references/per-host.toml`** — exact structure:

```toml
[default]
rps = 0.5
concurrency = 2
timeout_s = 12.0
user_agent_pool_id = "browser-mix"

["goudengids.be"]
rps = 0.3
concurrency = 1
timeout_s = 15.0
user_agent_pool_id = "chrome-only"
notes = "Imperva Cloud WAF (cookie tier). Cookie warm-up via Playwright every 30-60 min."

["pagesdor.be"]
rps = 0.3
concurrency = 1
timeout_s = 15.0
user_agent_pool_id = "chrome-only"
notes = "Same parent (FCR Media) as goudengids.be."

["kbopub.economie.fgov.be"]
rps = 0.25
concurrency = 1
timeout_s = 15.0
user_agent_pool_id = "browser-mix"
notes = "FPS Economy explicitly forbids systematic download. Reserve for per-company function holder lookups only."

["ws.cbso.nbb.be"]
rps = 1.0
concurrency = 2
timeout_s = 20.0
user_agent_pool_id = "api-client"
notes = "Authentic Data Query — requires NBB CBSO subscription key (free product, registration required)."

["api.search.brave.com"]
rps = 1.0
concurrency = 1
timeout_s = 10.0
user_agent_pool_id = "api-client"
notes = "Free tier: 2000 queries/month, 1 qps."

["duckduckgo.com"]
rps = 0.3
concurrency = 1
timeout_s = 10.0
user_agent_pool_id = "browser-mix"
notes = "Use ddgs library; rate-limits aggressively even at low volume."

["web.archive.org"]
rps = 0.8
concurrency = 1
timeout_s = 30.0
user_agent_pool_id = "identifying"
notes = "CDX API. 60 req/min hard ceiling. Use a contact-bearing UA."
```

**`references/headers.md`** — one section per `user_agent_pool_id`. Pools:
- `browser-mix`: 3 realistic UAs (Chrome 134 Win64, Firefox 130 Win64, Safari 18 macOS).
- `chrome-only`: 3 Chrome UAs (different versions, different OSes). Important for goudengids — Imperva flags non-Chrome UAs more aggressively.
- `api-client`: a single identifying UA in the form `be-leads/0.1 (+https://example.invalid)`.
- `identifying`: `be-leads/0.1 (contact@example.invalid)` — used for archive.org per their request.

Also document required headers per pool (Accept-Language `nl-BE,nl;q=0.9,fr;q=0.5,en;q=0.3`, Accept-Encoding `gzip, deflate, br`, DNT, Connection, etc.).

**`references/status-codes.md`** — table:

| Code | Action | Reason |
|---|---|---|
| 200 | proceed | success |
| 301/302/303/307/308 | follow (max 5 hops) | normal redirects |
| 304 | use cache | not modified |
| 400 | fail (no retry) | client error, won't fix on retry |
| 401 | fail (no retry) | auth error — fix credentials |
| 403 | **stop, escalate** | likely WAF block, retrying makes it worse |
| 404 | fail (no retry) | resource doesn't exist |
| 410 | fail (no retry) | resource permanently gone |
| 429 | retry with backoff, honour Retry-After | rate limit |
| 500 | retry once | transient server error |
| 502/504 | retry with backoff | gateway / timeout |
| 503 | retry with backoff, honour Retry-After | service unavailable |

**`scripts/check_robots.py`** — small CLI that takes a URL and prints whether the configured user agent is allowed and any Crawl-Delay. Uses `urllib.robotparser` from stdlib. ≤30 lines. Used during ad-hoc dev.

### B. The Python module: `src/scraper/lib/http/`

Files (each ≤120 lines, type-hinted, async-first):

```
src/scraper/lib/
├── __init__.py
├── errors.py
└── http/
    ├── __init__.py
    ├── client.py
    ├── limiter.py
    ├── retry.py
    └── robots.py
```

**`src/scraper/lib/errors.py`** — typed exception hierarchy:

```python
class ScraperError(Exception): ...
class HttpError(ScraperError):
    def __init__(self, status: int, url: str, message: str) -> None: ...
class RateLimitedError(HttpError): ...   # 429
class BlockedError(HttpError): ...        # 403 — caller must NOT retry
class TransientServerError(HttpError): ... # 500/502/503/504
class TerminalServerError(HttpError): ...  # other 5xx
class RetriesExhaustedError(ScraperError): ...
class RobotsDisallowedError(ScraperError): ...
```

**`src/scraper/lib/http/limiter.py`** — async per-host token bucket:

```python
@dataclass
class HostConfig:
    rps: float
    concurrency: int
    timeout_s: float
    user_agent_pool_id: str

class HostLimiter:
    def __init__(self, configs: dict[str, HostConfig], default: HostConfig) -> None: ...
    async def acquire(self, host: str) -> None: ...
    def config_for(self, host: str) -> HostConfig: ...
```

Implementation: per-host `asyncio.Semaphore(concurrency)` for concurrent slots, plus a token-bucket refill at `rps` tokens/sec. Use `asyncio.Lock` to guard bucket state. Reset the bucket lazily on `acquire`.

Provide a module-level `load_from_toml(path: Path) -> HostLimiter` that reads `references/per-host.toml` (the skill's file). The path is configurable; default reads from the skill location.

**`src/scraper/lib/http/retry.py`** — async retry decorator that maps httpx response/exception to the typed errors above. Backoff = `min(60.0, 1.0 * 2**attempt) + random.uniform(0, 0.3)`. Max 5 attempts. Honour `Retry-After` if present. Retry on `RateLimitedError | TransientServerError | httpx.TimeoutException | httpx.NetworkError`. Never retry on `BlockedError`.

```python
async def request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    max_attempts: int = 5,
    base_delay: float = 1.0,
    jitter: float = 0.3,
    **kwargs: Any,
) -> httpx.Response: ...
```

**`src/scraper/lib/http/robots.py`** — async robots.txt fetcher with caching:

```python
class RobotsCache:
    def __init__(self, client: httpx.AsyncClient, ttl_s: int = 3600) -> None: ...
    async def can_fetch(self, url: str, user_agent: str) -> bool: ...
    async def crawl_delay(self, url: str, user_agent: str) -> float | None: ...
```

Implementation: fetch `https://{host}/robots.txt`, parse with `urllib.robotparser`, cache per host with TTL. On 404/timeout, default to allow=true and crawl_delay=None.

**`src/scraper/lib/http/client.py`** — the public async API used by every source:

```python
async def get_polite_client(
    limiter: HostLimiter,
    robots: RobotsCache,
) -> AsyncIterator[PoliteClient]: ...

class PoliteClient:
    """Wraps httpx.AsyncClient with limiter + robots check + retry."""
    async def get(self, url: str, **kwargs: Any) -> httpx.Response: ...
    async def post(self, url: str, **kwargs: Any) -> httpx.Response: ...
    # ... same shape as httpx.AsyncClient.{verb} for the verbs we use.
```

Behaviour of `PoliteClient.get(url)`:
1. Parse host from URL.
2. `await robots.can_fetch(url, ua)` — raise `RobotsDisallowedError` if false.
3. `await limiter.acquire(host)`.
4. Sleep `crawl_delay` if any.
5. `await request_with_retry(...)` with the host's timeout and configured headers (UA from the host's pool, picked deterministically per session, plus Accept-Language/Encoding from `headers.md`).
6. Map response to typed errors per status-codes.md.

Use `httpx.AsyncClient(http2=True, follow_redirects=True, timeout=...)` underneath. The client is async-context-manager-friendly: `async with get_polite_client(...) as pc: await pc.get(url)`.

### C. Tests

Layout:
```
tests/unit/lib/http/
├── __init__.py
├── test_limiter.py
├── test_retry.py
├── test_robots.py
└── test_client.py
tests/integration/
└── test_polite_client_live.py
```

Coverage targets:
- `test_limiter.py` — rps capping (acquire 5 tokens, assert ≥4 seconds elapsed for rps=1.0); concurrency cap; load_from_toml round-trip with a tmp TOML file; default fallback when host not in config.
- `test_retry.py` — uses `respx` to mock httpx. Cases: 200 first try; 429 then 200; 503 thrice then 200; 403 → BlockedError immediately, no retry; Retry-After header honored (both `5` and HTTP-date); 5xx exhausted → RetriesExhaustedError.
- `test_robots.py` — mocks robots.txt response with `respx`. Cases: allow when robots.txt absent (404); deny when User-agent: * Disallow: /; cache hit on second call; TTL expiry.
- `test_client.py` — wires limiter + robots + retry. Verifies one request goes through end-to-end against `respx`-mocked endpoint; verifies disallowed URL raises RobotsDisallowedError before HTTP fires.
- `test_polite_client_live.py` — `@pytest.mark.network`; hits `https://example.com/` once and asserts `200`. Skipped in CI.

Use `pytest-asyncio` auto mode. Keep tests fast (<5 s total for non-network).

Where helpful, use a `respx_mock` fixture pattern; do not import respx at module top-level if it complicates type checking.

### D. Wire into CLAUDE.md

Add one line under "## Per-source knowledge":
```
- Polite scraping rules: `.claude/skills/polite-scraping/SKILL.md` (active)
```

### E. Update CHANGELOG

Add under `[Unreleased]`:
```
### Added
- Skill: `polite-scraping` with per-host TOML, headers, and status-code reference.
- Module `src/scraper/lib/http/` (client, limiter, retry, robots) and `lib/errors.py`.
- Tests: 4 unit modules + 1 network-marked integration test.
```

## Verification — run before stopping

```
uv run pytest -q -m "not network"
uv run pytest --cov=src/scraper/lib --cov-fail-under=90 -q -m "not network"
uv run mypy src/scraper
uv run ruff check src/scraper tests
uv run ruff format --check src/scraper tests
uv run python -m scraper.lib.http.limiter --help    # must not crash; just imports
```

## Stop conditions

When all green:
1. Print one-line summary: number of new files, total tests passing, coverage % on `src/scraper/lib/http/`.
2. Print verbatim: `Ready for prompt 3 (provenance schema + DB migrations). Commit: git add . && git commit -m "skill: polite-scraping (prompt 2)".`
3. End the turn. Do not start prompt 3 work.

## Things you must NOT do

- Do not create source modules (`src/scraper/sources/...`). Sources come later.
- Do not add Playwright code. The Imperva-cookie pattern is documented in the skill but the implementation lives in the goudengids prompt.
- Do not add a caching layer (`hishel` or similar). Deferred.
- Do not add database code. The provenance schema is prompt 3.
- Do not modify `pyproject.toml` to add new dependencies — `httpx`, `respx`, `pytest-recording` are already in the lockfile.
- Do not skip writing tests first. The TDD hook will block you anyway, but the spirit matters: tests in this PR fail before the implementation lands, then pass after.
