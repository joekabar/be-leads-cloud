# Bootstrap Prompt 8 — Skill: `goudengids-listing` + Source: `goudengids`

> **How to use:** `be-leads/`, Git Bash, fresh `claude` session. Postgres up. **Playwright Chromium must be installed** — `uv run playwright install chromium` first if you haven't. Paste from `=== PROMPT ===`.

---

=== PROMPT ===

You are adding the discovery source: `goudengids`. This scrapes search-result listing pages from goudengids.be (and its French sibling pagesdor.be) to find new companies that don't yet appear in the KBO Open Data dump (newly registered) or which need contact-info enrichment beyond what KBO/NBB provide. The host is behind **Imperva Cloud WAF (cookie tier)** — naive `httpx.get()` returns 403 after 1-3 requests. The fix is a Playwright cookie warm-up pattern: render the homepage with a headless browser, harvest the `incap_ses_*` and `visid_incap_*` cookies, transfer them to an httpx session, then use httpx for all subsequent paginated fetches.

This is the highest-risk prompt because of the WAF. All tests use mocked HTTP — no live goudengids hits.

## Read first

- `CLAUDE.md`
- `.claude/skills/polite-scraping/SKILL.md` — sections 2 (per-host: goudengids 0.3 rps, Imperva note) and 6 (escalate-to-Playwright triggers)
- `.claude/skills/provenance-schema/SKILL.md`
- `.claude/skills/kbo-lookup/SKILL.md`
- `src/scraper/lib/http/client.py` (PoliteClient — you'll extend it)
- `src/scraper/lib/validators/phone.py`
- `src/scraper/sources/kbopub_html/parser.py` (BeautifulSoup pattern)
- `agent_docs/runbook.md`
- Project memories at `~/.claude/projects/C--Users-Oxfam-Documents-Saivy-Programs-be-leads/memory/`

## Plan first

Create `.claude/plans/2026-05-10-goudengids.md`:
- Status: `approved`
- Goal: "Ship the `goudengids-listing` skill plus `goudengids` source. Discovers companies by sector × city via the listing pages of goudengids.be and pagesdor.be, parses each result card into a typed row, validates contact info, and writes observations. Implements Imperva-cookie warm-up via Playwright, then switches to httpx for the per-page fetches."
- Scope in: skill SKILL.md + references (selectors.md, imperva-bypass.md, sectors.toml); source `src/scraper/sources/goudengids/` (warmup, fetcher, parser, transformer, ingester, cli); golden HTML fixtures for 3 listing-page states + 2 detail-page states; tests; CLAUDE.md/runbook/CHANGELOG updates.
- Out of scope: the **detail-page deep scan** (per-company website-derived fields like activity_summary, photos, contact-page persons) — that's prompt 9 (`website` source); residential proxy rotation (prompt 11 or beyond if needed); pagesdor.be tests beyond a one-line URL-builder check (NL is the primary directory).
- Acceptance: warmup module returns valid Imperva cookies for an httpx session in <30s on first call; fetcher correctly handles "no results" and "last page" termination; parser handles 3 listing-page golden HTMLs; transformer emits `name`, `phone`, `address`, `website`, optional `email` observations per result card; idempotency via dedup-on-(name+postal_code+source) within 24h (goudengids may not give us a KBO number on the listing page); `mypy --strict` clean; coverage on `src/scraper/sources/goudengids/` ≥ 85% (warmup is harder to cover; allow lower threshold here than other sources).

## Pre-flight

```bash
docker compose up -d pg
uv run be-leads-migrate
uv run playwright install chromium    # installs browser binary; ~150 MB, one-time
uv run pytest -q -m "not network and not slow"   # 295 tests baseline
```

If `playwright install` fails (corporate network etc.), Claude Code must report it and stop. The warmup module is mandatory.

## What to produce

### A. Skill: `.claude/skills/goudengids-listing/`

```
.claude/skills/goudengids-listing/
├── SKILL.md
├── references/
│   ├── selectors.md
│   ├── imperva-bypass.md
│   └── sectors.toml
└── scripts/
    └── probe_listing.py
```

**SKILL.md frontmatter:**

```yaml
---
name: goudengids-listing
description: Scrape sector × city listing pages on goudengids.be (NL) and pagesdor.be (FR) for company discovery. Host is behind Imperva Cloud WAF (cookie tier, not reese84 — verified). Pattern is two-phase: warm up cookies via Playwright headless Chromium against the homepage, then transfer cookies to httpx for paginated listing fetches at 0.3 rps. Each result card yields name, phone, address, optional email/website, optional KBO. Use whenever the user mentions goudengids, pagesdor, golden pages, gouden gids, listing page, company directory, sector search, or "find me companies in <city>".
allowed-tools: Read, Edit, Bash, WebFetch(domain:goudengids.be), WebFetch(domain:pagesdor.be), Bash(uv run python:*), Bash(uv run pytest:*), Bash(uv run be-leads-discover-goudengids:*), mcp__playwright__*
---
```

**SKILL.md body** sections:

1. **When to use.** Discovery (new companies); contact enrichment (extra phones, websites). NOT for canonical company facts — KBO Open Data wins for those.
2. **URL structure.** `https://www.goudengids.be/zoeken/{sector_slug}/{city_slug}/{page}/`. Both slugs lowercase, hyphenated. Examples: `/zoeken/electriciens/antwerpen/1/`. Pagesdor mirror: `https://www.pagesdor.be/recherche/{sector_slug_fr}/{city_slug}/{page}/`.
3. **Imperva pattern.** Pointer to `references/imperva-bypass.md`. Two-phase: warmup (~3s with Playwright) → cookie transfer → httpx for the rest. Re-warm every 30-60 min OR on any 403 (whichever first).
4. **Listing structure.** Each search result is a `<li data-small-result='{...JSON...}'>`. The JSON contains `title`, `href`, `phone`, `logo`. The `<li>` body also contains a `tel:` dropdown (additional phone numbers), `data-yext` spans for address, and a `utm_source=fcrmedia` link for the company's website. Selectors documented in `references/selectors.md`.
5. **Pagination.** Path-based `/1/` `/2/` etc. Max ~25 pages per sector. Stop when listing returns 0 cards or the page renders a "geen resultaten" empty state.
6. **Sector slugs.** `references/sectors.toml` contains the canonical NL→FR mapping. Do NOT invent slugs — use only the documented ones.
7. **Rate.** 0.3 rps + concurrency 1 from `per-host.toml`. **Imperva penalises bursts harder than sustained low rate** — never batch concurrent goudengids requests, even within the same source.
8. **What NOT to scrape from goudengids.** Founding date, KBO number, employees, financials — use the dedicated authoritative sources (kbo_dump / kbopub_html / nbb_authentic). Goudengids ≠ authority for those.

**`references/selectors.md`** — the actual CSS/BeautifulSoup selectors:

```
Result card root:                li[data-small-result]
JSON blob:                       attribute data-small-result (parse as JSON)
  -> title                       company name
  -> href                        link to detail page on goudengids
  -> phone                       primary phone (E.164-ish, no spaces)
  -> logo                        image URL (often hosted on i.fcrmedia.com)

All phones (dropdown):           a[href^="tel:"]
Website:                         a[href*="utm_source=fcrmedia"]
Address street:                  span[data-yext=street]
Address postal code:             span[data-yext=postal-code]
Address city-district:           span[data-yext=city-district]
Address city:                    span[data-yext=city]
Short description:               div.result-item__description (~300 chars)

"No results" state:              presence of .empty-state or text "geen resultaten"
"Last page" state:               page returns 0 li[data-small-result]
```

KBO number is NOT reliably present on the listing card. Sometimes shown on detail page — but prompt 8 doesn't scrape detail pages (prompt 9 does). So leave KBO as `None` from goudengids; the consolidation step (prompt 11) matches goudengids rows to KBO rows by (name, postal_code, city).

**`references/imperva-bypass.md`** — the warmup recipe:

1. Launch `playwright.chromium` headless with these args: `--disable-blink-features=AutomationControlled`.
2. New context: `user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"`, `locale="nl-BE"`, `viewport={"width": 1280, "height": 720}`.
3. `add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")` — removes one of the easiest WAF signals.
4. `page.goto("https://www.goudengids.be/", wait_until="domcontentloaded", timeout=30000)`.
5. Wait for a known DOM marker (e.g. the search input) to confirm WAF challenge passed.
6. Harvest cookies via `context.cookies()`. Filter to those with `name` matching `^(incap_ses_|visid_incap_|nlbi_|reese84)`. Return them as a list of `httpx.Cookies` entries.
7. Cookies typically live 30-60 min; re-warm proactively at 25 min OR on first 403.

Document: if `nlbi_` or `reese84` cookies appear, that's a stronger Imperva tier — the warmup may need additional steps (mouse movement, scroll). Not implemented in prompt 8; documented as a future hardening step.

Document fallbacks if warmup fails:
- Playwright launch error → bubble up; the user might need to `playwright install` first or fix proxy.
- Page navigation times out → retry once with a fresh context; on second failure, raise `WarmupFailedError`.

**`references/sectors.toml`** — the NL→FR sector slug map. Include the 65 sectors from the previous app.py (you have it in the project notes). Format:

```toml
[transport]
nl_slug = "transport"
fr_slug = "transports"
display = "Transport — General"
emoji = "🚚"

[road_freight]
nl_slug = "transportbedrijven"
fr_slug = "entreprises-de-transport"
display = "Road Freight"
emoji = "🚛"
```

Continue for all 65 sectors. Use lowercase slugs (the goudengids URL is case-insensitive but lowercase is canonical). NL slugs come from the existing app.py SECTOR_MAP keys; FR slugs from pagesdor's equivalent URLs — if you don't know the FR slug for a given sector, leave it as an empty string and add a `# TODO: verify FR slug` comment. We'll fill in FR later.

**`scripts/probe_listing.py`** — ≤40 lines. Reads `sector_slug` and `city_slug` from argv. Does warmup + fetches page 1. Prints number of cards found and the first card's JSON. Used for manual dev. Hits live goudengids — should be run sparingly.

### B. Source: `src/scraper/sources/goudengids/`

```
src/scraper/sources/goudengids/
├── __init__.py
├── warmup.py          # Playwright cookie harvester
├── fetcher.py         # post-warmup httpx fetches
├── parser.py          # HTML → typed ListingCardRow
├── transformer.py     # ListingCardRow → Observation list
├── ingester.py        # orchestrate full pipeline
└── cli.py             # be-leads-discover-goudengids
```

#### warmup.py

```python
@dataclass(frozen=True, slots=True)
class WarmupResult:
    cookies: list[httpx.Cookies]
    obtained_at: datetime
    ttl_minutes: int = 25     # refresh at 25 min, before typical expiry

class WarmupFailedError(ScraperError): ...

async def warmup_cookies(
    domain: str = "goudengids.be",
    *,
    timeout_s: float = 30.0,
) -> WarmupResult: ...

def is_expired(result: WarmupResult, *, now: datetime | None = None) -> bool: ...
```

Implementation must use the `async_playwright()` async API (not `sync_playwright`). The browser must close cleanly in a `finally` block. Add a structlog info log on success with cookie names harvested.

#### fetcher.py

```python
@dataclass(frozen=True, slots=True)
class ListingPage:
    url: str
    html: str
    cards_found: int
    is_last_page: bool

class GoudengidsFetcher:
    """httpx session pre-loaded with warmup cookies. Auto-refreshes cookies on 403."""

    def __init__(self, polite_client: PoliteClient): ...

    async def warm(self) -> None:
        """Initial cookie warmup. Must be called before any fetch_page."""

    async def fetch_page(
        self,
        sector_slug: str,
        city_slug: str,
        page: int,
        *,
        lang: Literal["nl", "fr"] = "nl",
    ) -> ListingPage:
        """Single listing page. On 403, attempts ONE re-warm + retry; second 403 raises BlockedError."""
```

The `polite_client` enforces rate. The fetcher just adds cookie management on top.

URL builder:
- nl: `f"https://www.{domain}/zoeken/{sector_slug.lower()}/{city_slug.lower().replace(' ', '-')}/{page}/"`
- fr: `f"https://www.{domain}/recherche/{sector_slug.lower()}/{city_slug.lower().replace(' ', '-')}/{page}/"`

City slug: trim whitespace, replace internal spaces with hyphens, lowercase. "Sint-Niklaas" stays "sint-niklaas"; "Brussel Stad" becomes "brussel-stad". Test cases for both.

#### parser.py

```python
@dataclass(frozen=True, slots=True)
class ListingCardRow:
    name: str
    detail_url: str               # absolute URL on goudengids.be
    phones: list[str]             # all phones from tel: dropdown (primary first)
    website: str | None
    email: str | None             # rarely present on listing card; usually None
    address_street: str | None
    address_postal_code: str | None
    address_city: str | None
    description: str | None        # short snippet (~300 chars)
    logo_url: str | None
    raw_card_html: str            # for forensics

def parse_listing_page(html: str, domain: str = "goudengids.be") -> list[ListingCardRow]: ...

def is_empty_results_page(html: str) -> bool:
    """Detects the 'geen resultaten' / 'no results' empty state."""
```

Implementation:
- Use BeautifulSoup with `"lxml"` parser.
- Find all `li[data-small-result]`. For each, parse the JSON attribute.
- Extract phones via `li.select('a[href^="tel:"]')` — strip the `tel:` prefix, normalize via simple regex (no `validate_phone` here — that's the transformer's job).
- Address spans via `data-yext` attributes.
- Website via `a[href*="utm_source=fcrmedia"]` — strip query string.
- `email`: scan for `a[href^="mailto:"]` (often absent on listing pages).
- `detail_url`: absolute. If JSON `href` is relative, prefix `https://www.{domain}`.

#### transformer.py

```python
def card_to_observations(
    card: ListingCardRow,
    run_id: UUID,
    snapshot_at: datetime,
) -> list[Observation]:
    """Emit observations: name, phone (each phone), website, address, email if present.

    Because goudengids listings don't include KBO numbers, the `kbo_number` of each
    Observation is a SYNTHETIC placeholder formed by hashing (normalized_name, postal_code).
    The consolidation pass in prompt 11 reconciles these placeholders against real KBOs.
    Use the prefix '99' (invalid KBO checksum) so they never collide with real KBOs.
    """
```

**Synthetic KBO placeholder**: this needs careful design. Real KBO numbers start with `0` or `1`. We use `9` to make them obviously invalid. Format: `f"9{abs(hash((normalized_name, postal_code))) % 10**9:09d}"`. Resulting 10-digit string starts with `9`, ensures collision-resistance within a run.

Document this in `provenance-schema` skill (read the existing skill — if the synthetic-placeholder pattern is not yet documented there, ADD a section).

In the observations themselves:
- `source = "goudengids"`
- `confidence`: phone 0.85, website 0.85, name 0.85, address 0.80, email 0.80 (from confidence.md goudengids row)
- `source_url`: the `detail_url` from the card
- `value` JSONB shapes match `provenance-schema` SKILL.md section 7

Phone observations: call `validate_phone()` for each phone. Skip emit on `InvalidPhoneError` (warn-log, count, don't crash). Each unique valid phone becomes a separate observation.

Address normalisation: combine `address_street`, `address_postal_code`, `address_city` into the standard `address` JSONB shape (`{"street", "postal_code", "city", "country": "BE"}`). Skip if street is missing.

#### ingester.py

```python
@dataclass
class GoudengidsReport:
    sector: str
    city: str
    pages_scanned: int
    cards_found: int
    cards_with_phone: int
    cards_with_website: int
    observations_inserted: int
    placeholders_created: int
    duration_s: float

async def ingest_sector_city(
    sector_slug: str,
    city_slug: str,
    pool: asyncpg.Pool,
    fetcher: GoudengidsFetcher,
    *,
    max_pages: int = 25,
    lang: Literal["nl", "fr"] = "nl",
    skip_recent_hours: int = 24,
) -> GoudengidsReport: ...
```

Behaviour:
1. Validate sector_slug exists in `sectors.toml` (else `ValueError`).
2. Validate city_slug isn't empty.
3. Call `fetcher.warm()` once at the start.
4. Loop pages 1..max_pages:
   - `fetch_page(...)` → if `is_last_page` or `cards_found == 0`, break.
   - Parse + transform each card.
   - Optionally check 24h skip: for each placeholder KBO, check `observations` table for a recent `source='goudengids'` row — skip the card if present. (Cheap because placeholder KBO is deterministic.)
   - Bulk-insert observations in batches of 200.
5. After all pages: refresh matview.
6. Return report.

Error policy: `BlockedError` after re-warm → log + abort ingest, return partial report; HTTP errors handled by polite-scraping retry; `InvalidPhoneError` → skip individual phone, don't fail card.

#### cli.py

`be-leads-discover-goudengids`:
- `--sector <slug>` (required, must be in sectors.toml)
- `--city <name>` (required)
- `--lang nl|fr` (default nl, also switches domain to pagesdor.be when fr)
- `--max-pages N` (default 25)
- `--skip-recent-hours N` (default 24)
- `--database-url <DSN>` (env fallback)

Register in `pyproject.toml`:
```
be-leads-discover-goudengids = "scraper.sources.goudengids.cli:cli_main"
```

### C. Golden HTML fixtures

```
tests/golden/goudengids/
├── README.md
├── listing_antwerpen_electriciens_page1.html      # 12 cards, has all field types
├── listing_brugge_bakkers_page2.html              # 6 cards, fewer fields
├── listing_no_results.html                         # empty state, "geen resultaten"
├── listing_french_liege_plombiers.html             # FR variant via pagesdor structure
└── card_legal_person_holder.html                   # NOT used by parser tests; placeholder
```

Hand-construct minimal HTML that exercises the selectors. Reference the Bellock card data from the project notes:

- One card with full data: name="Bellock", href="/bedrijf/Antwerpen/L389732/Bellock/", phone="+3232361306", website="https://www.bellock.be?utm_source=fcrmedia&...", street="Lange Van Bloerstraat 116", postal=2060, city="Antwerpen", description="Electrotechnical installer since 1989".
- One card with multiple phones in the dropdown (e.g. landline + mobile).
- One card missing website (very common).
- One card with French-only address (street_fr style, no NL).
- One card whose phone fails validation (e.g. `123` — should be skipped by transformer but parser preserves it raw).

The empty-results fixture renders the "no results found" template. The parser's `is_empty_results_page` must return True.

### D. Tests

```
tests/unit/sources/goudengids/
├── __init__.py
├── test_warmup.py           # mocks playwright; tests cookie filter logic
├── test_parser.py
└── test_transformer.py
tests/integration/sources/goudengids/
├── __init__.py
├── conftest.py
├── test_fetcher.py           # respx + cookie injection
├── test_ingester.py          # full pipeline against test DB
└── test_cli.py
```

Required cases:

`test_warmup.py`:
- Mock `async_playwright` via a stand-in (the `playwright.async_api.Playwright` interface). Test:
  - `warmup_cookies` returns a `WarmupResult` with `obtained_at` close to now.
  - Cookie filter keeps `incap_ses_*`, `visid_incap_*`, drops unrelated cookies (e.g. `_ga`).
  - `is_expired(result, now=result.obtained_at + 26min)` is True; `now=result.obtained_at + 20min` is False.
  - Playwright launch failure → `WarmupFailedError`.

`test_parser.py`:
- 12 cards from antwerpen_electriciens fixture → 12 `ListingCardRow` objects.
- Bellock card exact match: name, phones=["+3232361306"], website starts with "https://www.bellock.be", street="Lange Van Bloerstraat 116", postal_code="2060", city="Antwerpen".
- Card with multi-phone dropdown → all phones in `.phones` list, primary first.
- Empty-results fixture → `is_empty_results_page == True`, `parse_listing_page == []`.
- French Liège fixture → cards parsed correctly with FR address pattern.

`test_transformer.py`:
- Bellock card → observations: 1 name, 1 phone (validated → fixed_line Antwerp), 1 website, 1 address. Each observation: source=goudengids, confidence per skill, kbo_number starts with "9".
- Card with invalid phone → phone observation NOT emitted; warning logged; name/address still emit.
- All placeholder KBOs across multiple cards are unique (assert no collisions within the fixture set).
- Placeholder KBO is deterministic: same (name, postal_code) → same KBO across two invocations.

`test_fetcher.py`:
- Mock `warm()` to return a fixed cookie list; assert those cookies are present on subsequent `fetch_page` requests via respx.
- 403 on first fetch → fetcher calls `warm()` again, retries, succeeds → returns ListingPage.
- Two consecutive 403s → raises BlockedError.

`test_ingester.py`:
- Use respx to mock 3 listing pages: page 1 (10 cards), page 2 (10 cards), page 3 (0 cards / empty state).
- Run `ingest_sector_city("electriciens", "antwerpen", pool, fetcher)`. Assert: pages_scanned == 3, cards_found == 20, observations_inserted ≥ 60.
- Re-run within 24h → 0 new observations.
- Force `skip_recent_hours=0` → re-inserts.

`test_cli.py`:
- `be-leads-discover-goudengids --sector electriciens --city antwerpen --max-pages 2` with mocked HTTP → exit 0, JSON report on stdout.
- Invalid sector slug → exit 2 with clear error listing the available sectors.

### E. Update agent_docs/runbook.md

```
## Goudengids / pagesdor discovery

### Initial setup
    uv run playwright install chromium     # ~150 MB, one-time

### Discover a sector × city
    uv run be-leads-discover-goudengids --sector electriciens --city antwerpen --max-pages 10

### Rate
0.3 req/s, concurrency 1. 10 pages × ~20 cards = ~200 leads per run, ~35 seconds wall-clock
(plus 3-5s warmup).

### When goudengids blocks
- A 403 triggers an automatic re-warmup + retry. If the second attempt also 403s, the
  ingester aborts cleanly with a BlockedError.
- If blocks become consistent: stop using the cli for an hour, then resume.
- If still blocked after multiple hours: consider rotating to a residential proxy
  (BrightData / Oxylabs IPs are not on Imperva's denylist; datacenter IPs are).
  See `.claude/skills/goudengids-listing/references/imperva-bypass.md` for the planned
  proxy injection point (not implemented in prompt 8).

### Cookie hygiene
Cookies live ~30-60 min. The fetcher auto-refreshes at 25 min. Do NOT cache cookies across
process restarts — start fresh each run.
```

### F. Update CLAUDE.md

Under "## Per-source knowledge":
```
- Goudengids / pagesdor scraping rules: `.claude/skills/goudengids-listing/SKILL.md` (active)
```

Under "## Anti-patterns":
```
- Concurrent goudengids requests. The host's WAF penalises bursts harder than sustained low rate. Always concurrency 1.
```

### G. Update `provenance-schema` skill (if needed)

Read `.claude/skills/provenance-schema/SKILL.md`. If it does not yet document the synthetic-placeholder-KBO pattern (KBO numbers starting with `9` are placeholders for sources without authoritative numbers), add a short section:

```
## Synthetic placeholder KBOs

Sources without authoritative KBO numbers (goudengids listing pages, search engines)
emit observations under a synthetic placeholder KBO formed as:
    f"9{abs(hash((normalized_name, postal_code))) % 10**9:09d}"

Real KBOs start with `0` or `1` and pass mod-97 checksum. Placeholders start with `9` and
fail checksum, so they cannot collide with real entities.

The consolidation pass (`src/scraper/pipeline/consolidate.py`, prompt 11) maps placeholders
to real KBOs by (name, postal_code, city) fuzzy match. Until consolidation, placeholder
observations remain queryable but live in a separate "candidate" tier.
```

### H. Update CHANGELOG

```
### Added
- Skill: `goudengids-listing` with selectors.md, imperva-bypass.md, sectors.toml (65 sectors).
- Source: `goudengids` — Playwright warmup + httpx-based listing scraper for goudengids.be / pagesdor.be.
- Synthetic placeholder KBO scheme (9-prefix) for sources without authoritative numbers.
- 4 golden HTML fixtures (antwerpen full, brugge sparse, no-results, FR).
- CLI: `uv run be-leads-discover-goudengids --sector <slug> --city <name>`.
```

## Verification

```bash
docker compose up -d pg
uv sync --locked --dev
uv run playwright install chromium    # idempotent if already installed
uv run pytest -q -m "not network and not slow"
uv run pytest --cov=src/scraper/sources/goudengids --cov-fail-under=85 -q tests/unit/sources/goudengids tests/integration/sources/goudengids
uv run mypy src/scraper
uv run ruff check src/scraper tests
uv run ruff format --check src/scraper tests

# Eyeball: parse the antwerpen fixture and print Bellock's row
uv run python -c "
from pathlib import Path
from scraper.sources.goudengids.parser import parse_listing_page
html = Path('tests/golden/goudengids/listing_antwerpen_electriciens_page1.html').read_text(encoding='utf-8')
cards = parse_listing_page(html)
print(f'{len(cards)} cards found')
bellock = next((c for c in cards if 'Bellock' in c.name), None)
if bellock:
    print(f'  name={bellock.name}')
    print(f'  phones={bellock.phones}')
    print(f'  website={bellock.website}')
    print(f'  address={bellock.address_street}, {bellock.address_postal_code} {bellock.address_city}')
else:
    print('  Bellock card NOT FOUND in fixture')
"

# Eyeball: transform the same card and print the placeholder KBO
uv run python -c "
from pathlib import Path
from uuid import uuid4
from datetime import datetime
from scraper.sources.goudengids.parser import parse_listing_page
from scraper.sources.goudengids.transformer import card_to_observations
html = Path('tests/golden/goudengids/listing_antwerpen_electriciens_page1.html').read_text(encoding='utf-8')
cards = parse_listing_page(html)
bellock = next(c for c in cards if 'Bellock' in c.name)
obs = card_to_observations(bellock, uuid4(), datetime.now())
for o in obs:
    print(f'{o.kbo_number} {o.field}: {o.value}')
"
```

The first block must print Bellock's full address line. The second must show:
- The same 10-digit placeholder KBO starting with `9` on every line (deterministic from name+postal).
- 4 observations: name, phone, website, address.
- The phone observation's value matches the validated PhoneValidation shape from prompt 4.

## Stop conditions

When green:
1. Print one-line summary: new files, tests passing on goudengids, coverage %.
2. Print the verbatim output of the two `python -c` blocks (Bellock card parse + observations emit).
3. Print: `Ready for prompt 9 (skill: website-analysis + source: website). Commit: git add . && git commit -m "skill: goudengids-listing + source: goudengids (prompt 8)".`
4. End the turn.

## Things you must NOT do

- Do not hit live goudengids in any test. All HTTP via respx. The probe_listing.py script is for the user, not tests.
- Do not skip the Playwright warmup. The whole point of this source is to have a working Imperva bypass.
- Do not implement detail-page scraping. That's the `website` source in prompt 9.
- Do not use sync Playwright (`sync_playwright`). The whole codebase is async; mixing breaks the event loop.
- Do not add residential proxy support. Document the injection point but defer the implementation.
- Do not add user-agent rotation. The skill specifies `chrome-only` UA pool; pick one and stick with it.
- Do not increase concurrency above 1 for goudengids. The WAF will punish you.
- Do not modify existing sources or the http module.
- Do not add new runtime dependencies. `playwright` is already in `[project.optional-dependencies] dev`.
