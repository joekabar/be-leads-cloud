# Bootstrap Prompt 9 — Skill: `website-analysis` + Source: `website`

> **How to use:** `be-leads/`, Git Bash, fresh `claude` session. Postgres up. Paste from `=== PROMPT ===`.

---

=== PROMPT ===

You are adding the per-company website enrichment source: `website`. Given a website URL (already collected via kbo_dump, kbopub, or goudengids), this fetches the homepage and a few key sub-pages, extracts structured data (JSON-LD), contact info (phones, emails, persons), an activity summary, and a website-age estimate (WHOIS + Wayback Machine), and writes the lot as observations.

This source is **fan-out** — each company hits a different host, so concurrency-15 is acceptable here per the polite-scraping rules (the limiter is per-host).

## Read first

- `CLAUDE.md`
- `.claude/skills/polite-scraping/SKILL.md` (default host: 0.5 rps, concurrency 2 — applies per company website)
- `.claude/skills/provenance-schema/SKILL.md` (sections 5 + 7: contact/person/activity_summary/website_age JSONB shapes)
- `.claude/skills/belgian-phone-validation/SKILL.md`
- `.claude/skills/goudengids-listing/SKILL.md` (synthetic placeholder KBO scheme)
- `src/scraper/lib/http/client.py`, `src/scraper/lib/validators/phone.py`
- `src/scraper/sources/goudengids/transformer.py` (placeholder-KBO transformer pattern — useful when website is found via search and we don't know which KBO it belongs to)
- Project memories at `~/.claude/projects/C--Users-Oxfam-Documents-Saivy-Programs-be-leads/memory/`

## Plan first

`.claude/plans/2026-05-10-website.md`:
- Status: `approved`
- Goal: "Ship the `website-analysis` skill plus `website` source. Given a KBO + website URL, fetches the homepage and best-guess contact page, extracts structured data (JSON-LD LocalBusiness/Organization), phones, emails, contact persons, activity summary, and website age. Emits observations enriching the company record."
- Scope in: skill SKILL.md + references (selectors-heuristics.md, age-heuristics.md, nace-classification.md); source `src/scraper/sources/website/` (fetcher, structured.py, contact_page.py, persons.py, age.py, transformer, ingester, cli); golden HTML fixtures for 5 site archetypes (WordPress, Squarespace, custom with JSON-LD, static HTML, contact page); tests; CLAUDE.md/runbook/CHANGELOG.
- Out of scope: NACE zero-shot classification (deferred — separate prompt or after prompt 11); Wayback CDX integration (this prompt uses domain WHOIS + footer year heuristics; Wayback is a stretch goal); per-company sentiment/quality scoring; PDF parsing (rare on company sites).
- Acceptance: skill loads on website-related prompts; structured-data extractor parses 4 distinct JSON-LD samples correctly (LocalBusiness, Organization, ProfessionalService, with phone/email/openingHours); contact-page discoverer finds NL/FR contact pages via known URL patterns; phone validator integrated; person extractor handles itemtype=Person microdata + role-keyword heuristic; age estimator returns 4-char year string; mypy --strict clean; coverage on `src/scraper/sources/website/` ≥ 85% (network-dependent extractors are hard to cover fully).

## Pre-flight

```bash
docker compose up -d pg
uv run be-leads-migrate
uv run pytest -q -m "not network and not slow"   # 359 tests baseline
```

## What to produce

### A. Skill: `.claude/skills/website-analysis/`

```
.claude/skills/website-analysis/
├── SKILL.md
├── references/
│   ├── selectors-heuristics.md
│   ├── age-heuristics.md
│   └── extraction-priorities.md
└── scripts/
    └── analyze_url.py
```

**SKILL.md frontmatter:**

```yaml
---
name: website-analysis
description: Analyze a company's own website to extract structured business data — phones, emails, contact persons, activity summary, NACE-classification hints, opening hours, and website age. Two-step process: fetch the homepage, then attempt to find and fetch a contact/team page for richer person data. Uses JSON-LD structured data when present; falls back to heuristics for older sites. Use whenever the user mentions website enrichment, company homepage scraping, contact persons, activity summary, website age, JSON-LD, schema.org, or "scrape the company's own site".
allowed-tools: Read, Edit, Bash, WebFetch, Bash(uv run python:*), Bash(uv run pytest:*), Bash(uv run be-leads-enrich-website:*)
---
```

**SKILL.md body**:

1. **When to use.** Any per-company website enrichment.
2. **Three extraction tiers, in order of confidence.**
   - **JSON-LD `<script type="application/ld+json">`**: confidence 1.00. Look for `@type` of `LocalBusiness`, `Organization`, `ProfessionalService`, `Store`, `Restaurant`. Use `telephone`, `email`, `address`, `openingHours`, `description`, `founder/employee` (when typed `Person`).
   - **OpenGraph + meta tags**: confidence 0.85. `og:description`, `description`, `og:site_name`.
   - **HTML heuristics**: confidence 0.50-0.75. Phone numbers from `<a href="tel:">` or text-pattern scan; persons from `itemtype="Person"` microdata OR by role-keyword adjacency (`zaakvoerder|directeur|ceo|manager|sales|gérant` followed by Name Pattern); footer year for website-age fallback.
3. **Contact-page discovery.** Try in order: `/contact`, `/contact-us`, `/team`, `/over-ons`, `/about`, `/medewerkers`, `/wie-zijn-we`, `/notre-equipe`. First HEAD that returns 200 wins. If none: stay on homepage.
4. **Website age.** Try WHOIS (creation_date), then footer year (`©\s*(\d{4})` or `\b(20\d{2})\b`). Wayback CDX is the gold standard but deferred — document as TODO.
5. **Activity summary.** First non-empty match in order: `<meta name="description">`, `<meta property="og:description">`, `<meta name="twitter:description">`, first `<p>` > 60 chars inside `<main>` / `<article>` / `<section>`.
6. **Contact persons.** Skill section 6 ("contact_persons" JSONB shape — `{name, role, source}`). Microdata first, then JOB-keyword adjacency. Max 4 persons per company.
7. **Phones from website.** Always pipe through `validate_phone()`. Skip on InvalidPhoneError. Multiple phones get separate observations.
8. **Rate.** Default polite-scraping rate (0.5 rps per host). Distinct websites = distinct hosts, so concurrency 15 across companies is fine (the limiter is per-host).

**`references/selectors-heuristics.md`** — detailed selector / regex catalog:

```
PHONES:
  - <a href="tel:..."> → strip 'tel:'
  - Regex on visible text: (?:\+32|0032|\+31|0)[0-9 \-\.\/]{7,14}

EMAILS:
  - <a href="mailto:..."> → strip 'mailto:', drop ?subject= and beyond
  - Regex fallback: [a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}

PERSONS (microdata):
  - find_all(attrs={"itemtype": re.compile("Person", re.I)})
  - within each, .find(attrs={"itemprop":"name"})

PERSONS (heuristic):
  - role keywords (lowercased): zaakvoerder, ceo, directeur, manager, sales,
    contact, verantwoordelijke, gérant, gerant, director, founder, oprichter
  - in each <h1-4>, <p>, <span>: if role keyword found, extract names matching
    \b[A-ZÁÉÍÓÚÀÈÙÂÊÎÔÛÄËÏÖÜ][a-záéíóú]+\s[A-ZÁÉÍÓÚ][a-záéíóú]+\b near it

ACTIVITY SUMMARY:
  - <meta name="description"> content
  - <meta property="og:description"> content
  - <meta name="twitter:description"> content
  - main/article/section > p, first with len(text)>60, truncate to 300 chars

CONTACT PAGE LINKS:
  - <a href="...contact...">, <a href="...team...">, <a href="...about...">
  - case-insensitive match in href

OPENING HOURS:
  - JSON-LD openingHours / openingHoursSpecification
  - itemprop="openingHours"
  - No reliable HTML heuristic — skip if not in JSON-LD

CONTACT PHOTOS (optional, skip in prompt 9):
  - <img> with alt/class containing: team, medewerker, contact, ceo, etc.
```

**`references/age-heuristics.md`** — website age detection:

```
PRIORITY 1: WHOIS
  Use python-whois library.
  domain = urlparse(url).netloc.removeprefix('www.')
  w = whois.whois(domain)
  cd = w.creation_date
  if isinstance(cd, list): cd = cd[0]
  return str(cd)[:4]  # 4-char year

PRIORITY 2: Footer year
  text = (soup.find("footer") or soup).get_text()[-1000:]
  years = re.findall(r'©\s*(\d{4})', text)
  if not years:
      years = re.findall(r'\b(20\d{2})\b', text)
  return max(years) if years else None

PRIORITY 3: Wayback CDX (deferred)
  GET https://web.archive.org/cdx/search/cdx?url={domain}&limit=1&output=json
  First-snapshot year. 60 req/min ceiling. Not implemented this prompt.

Return type: 4-char string year (e.g. "2017") or None.
```

**`references/extraction-priorities.md`** — confidence ordering when multiple sources agree/disagree on same field, used by the transformer:

```
For phone observations from website:
  JSON-LD telephone -> confidence 1.00
  href="tel:" link  -> confidence 0.85
  regex on text     -> confidence 0.60

For email observations:
  JSON-LD email     -> confidence 1.00
  href="mailto:"    -> confidence 0.85
  regex             -> confidence 0.50

For persons:
  microdata Person  -> confidence 0.85
  role-keyword heur -> confidence 0.55

For website_age:
  WHOIS             -> confidence 1.00
  footer year       -> confidence 0.70
```

The transformer reads these and stamps each observation appropriately.

**`scripts/analyze_url.py`** — CLI: takes a URL, runs the full extractor, prints a pretty summary. Used for manual dev — hits live website.

### B. Source: `src/scraper/sources/website/`

```
src/scraper/sources/website/
├── __init__.py
├── fetcher.py
├── structured.py     # JSON-LD extractor
├── contact_page.py   # contact-page discoverer + fetcher
├── persons.py        # person extraction (microdata + heuristic)
├── age.py            # WHOIS + footer-year age estimator
├── transformer.py
├── ingester.py
└── cli.py
```

#### fetcher.py

```python
@dataclass(frozen=True, slots=True)
class FetchedPage:
    url: str
    html: str
    status: int
    final_url: str            # post-redirect

async def fetch_page(client: PoliteClient, url: str, *, timeout_s: float = 12.0) -> FetchedPage:
    """Single GET. Normalises URL (prepend https:// if missing scheme).
    Skips on robots-disallowed? — see polite-scraping. Returns even on non-200
    so callers can decide."""
```

URL normalisation: if URL doesn't start with `http`, prepend `https://`. Strip trailing slash before request (some servers redirect-loop on it).

#### structured.py

```python
@dataclass(frozen=True, slots=True)
class JsonLdData:
    type: str                  # "LocalBusiness" | "Organization" | ...
    name: str | None
    telephones: list[str]
    emails: list[str]
    addresses: list[dict[str, str]]    # {streetAddress, postalCode, addressLocality, addressCountry}
    description: str | None
    opening_hours: list[str]
    same_as: list[str]                  # social URLs, useful for cross-validation later
    founders: list[str]
    employees: list[str]

def extract_jsonld(html: str) -> list[JsonLdData]: ...
```

Implementation:
- `BeautifulSoup(html, "lxml")`.
- For each `<script type="application/ld+json">`: try `json.loads(script.string)`.
- A single script may contain a list of objects, or a single object, or an `@graph` array. Flatten all.
- Filter to objects whose `@type` is in `{LocalBusiness, Organization, ProfessionalService, Store, Restaurant, GeneralContractor, HomeAndConstructionBusiness, ElectricalContractor, Plumber, MedicalBusiness, ...}` — accept any subtype of LocalBusiness/Organization.
- Map fields: `telephone` (may be string or list), `email` (same), `address` (dict or list of dicts), `description`, `openingHours` (string OR list OR openingHoursSpecification list — flatten to ["Mo-Fr 09:00-17:00", ...]).
- Tolerate malformed JSON-LD (try/except per script — never crash the page).

#### contact_page.py

```python
async def find_contact_page(
    client: PoliteClient,
    homepage_url: str,
    homepage_html: str,
) -> str | None:
    """Returns absolute URL of the contact page, or None.
    Strategy: scan homepage links for known contact keywords first,
    then try well-known paths (/contact, /team, etc.) via HEAD requests."""
```

Implementation:
1. Parse homepage soup. Find all `<a href>` with case-insensitive match on `contact|team|over-ons|about|medewerkers|wie-zijn-we|notre-equipe|nous-contacter`.
2. If found, resolve relative→absolute via `urljoin`, return first.
3. Otherwise, try HEAD requests to `homepage_url + path` for path in the known list. Return first 200.
4. Return None if none work.

Rate: each HEAD goes through the polite-scraping limiter — typically <5 attempts total.

#### persons.py

```python
@dataclass(frozen=True, slots=True)
class ContactPerson:
    name: str
    role: str | None       # if role-keyword adjacency detected the role
    source: Literal["microdata", "heuristic"]

def extract_persons(html: str) -> list[ContactPerson]:
    """Up to 4 persons via microdata (preferred) or role-keyword heuristic."""
```

Implementation:
1. Microdata: `soup.find_all(attrs={"itemtype": re.compile("Person", re.I)})`. For each, `.find(attrs={"itemprop": "name"})` → name. If `<span itemprop="jobTitle">`, capture role.
2. If microdata empty, heuristic: scan `<h1-4>`, `<p>`, `<span>` for role keywords (skill ref). On match, extract candidate names via the Unicode-capitals regex from `selectors-heuristics.md`. Associate the closest name to the role.
3. Deduplicate by name (preserve order).
4. Cap at 4.

#### age.py

```python
async def estimate_age(url: str, html: str | None = None) -> tuple[str | None, str]:
    """Returns (year_4char_or_None, source_label). source ∈ {'whois', 'footer', 'none'}."""
```

Implementation:
1. WHOIS first. `python-whois.whois(domain)` is **synchronous and slow** — wrap in `asyncio.to_thread()`. Catch all exceptions (whois servers are flaky); return None on any failure.
2. If WHOIS returned None and html is given, parse footer year.
3. Return whichever succeeded with its source label.

Add `python-whois` to dependencies if not already present — check `pyproject.toml` first. If missing, add to runtime deps and run `uv sync`. **Do NOT add a hard dependency on python-whois if it's not in the lockfile** — instead, make WHOIS optional (try-import, fall back to footer-year only) and log a warning.

#### transformer.py

```python
@dataclass
class ExtractedSite:
    url: str
    structured: list[JsonLdData]
    contact_page_url: str | None
    persons: list[ContactPerson]
    activity_summary: str | None
    website_age: tuple[str | None, str]   # (year, source_label)
    phones_found: list[str]                # raw, pre-validation
    emails_found: list[str]

def site_to_observations(
    kbo_number: str,
    extracted: ExtractedSite,
    run_id: UUID,
    snapshot_at: datetime,
) -> list[Observation]:
    """Up to N observations: each phone, each email, persons (one obs per person),
    activity_summary, website_age. Confidence per extraction-priorities.md."""
```

Each emission:
- Source: `website`
- KBO: passed in (real or placeholder from caller)
- `value` JSONB shapes per provenance-schema contract:
  - `phone`: full `validate_phone(...).model_dump()` — call validator, skip on InvalidPhoneError
  - `email`: `{address, is_role_account}` — role detector: name in `{info, contact, sales, hello, support, admin, office}`
  - `activity_summary`: `{text: "...", lang_hint: "nl"|"fr"|"en"|None}` — lang via simple stopword count
  - `function_holder`: same shape as kbopub_html but with role=`null` if heuristic-only, role_canonical=`"contact"` for heuristic mode
  - `website_age`: `{year: "2017", method: "whois"|"footer"}`
- `source_url`: the page URL where the data came from (homepage or contact_page)

#### ingester.py

```python
@dataclass
class WebsiteReport:
    kbos_processed: int
    pages_fetched: int          # 1 homepage + optional 1 contact page per company
    observations_inserted: int
    fetch_failures: int
    duration_s: float

async def ingest_kbos(
    kbo_website_pairs: list[tuple[str, str]],   # (kbo_number, website_url)
    pool: asyncpg.Pool,
    polite_client: PoliteClient,
    *,
    skip_recent_hours: int = 168,    # 7 days — websites change slowly
    concurrent_companies: int = 15,
) -> WebsiteReport: ...
```

Behaviour:
1. Validate KBOs (real or placeholder).
2. 7-day skip per KBO (default — websites don't change daily, save your bandwidth).
3. `asyncio.TaskGroup` fanout: process up to `concurrent_companies` companies in parallel. Each task: fetch homepage → extract structured + activity + persons + age → maybe fetch contact page → re-extract persons → bulk-insert.
4. After all: refresh matview.

Error policy:
- Fetch fails (timeout, DNS, 5xx) → count, continue.
- Robots disallow → count as fetch_failure (we're not bypassing), continue.
- Parse exceptions → log + continue (one bad site shouldn't kill the batch).

#### cli.py

`be-leads-enrich-website`:
- `--kbos-and-websites <file>` (TSV: `kbo<TAB>url` per line)
- `--from-db` (alternative: read KBOs with websites from `companies_current` where field=website)
- `--limit N`
- `--concurrent-companies N` (default 15)
- `--skip-recent-hours N` (default 168)
- `--database-url <DSN>`

Register:
```
be-leads-enrich-website = "scraper.sources.website.cli:cli_main"
```

### C. Golden HTML fixtures

```
tests/golden/website/
├── README.md
├── wordpress_local_business.html        # Has JSON-LD LocalBusiness
├── squarespace_org.html                 # JSON-LD Organization, openingHours
├── custom_no_jsonld.html                # Heuristics only
├── contact_page_with_team.html          # Person microdata
└── french_about_page.html               # FR contact page with heuristic persons
```

Hand-construct, ≤200 lines each, with realistic content:

- `wordpress_local_business.html`:
  - JSON-LD LocalBusiness: name="Bellock", telephone=["+3232361306","+32474123456"], email="info@bellock.be", address={streetAddress:"Lange Van Bloerstraat 116", postalCode:"2060", addressLocality:"Antwerpen", addressCountry:"BE"}, openingHours=["Mo-Fr 08:00-17:00","Sa 09:00-12:00"]
  - Footer: `© 2017 Bellock`
  - Description meta: "Electrical installations and maintenance in Antwerp."
- `squarespace_org.html`:
  - JSON-LD Organization with employee = Person with name "Jan Boonen", jobTitle "Zaakvoerder"
- `custom_no_jsonld.html`:
  - No JSON-LD.
  - `<a href="tel:03 555 12 12">`, `<a href="mailto:hello@example.be">`
  - Footer: `© 2008-2026 Example BV`
  - Activity from `<p>` in main
- `contact_page_with_team.html`:
  - 3 `<div itemtype="https://schema.org/Person">` blocks with name + jobTitle
- `french_about_page.html`:
  - Heuristic case: `<h3>Notre équipe</h3>` followed by `<p>Jean Dupont, Gérant</p>` and `<p>Marie Martin, Responsable</p>`

### D. Tests

```
tests/unit/sources/website/
├── __init__.py
├── test_structured.py
├── test_contact_page.py
├── test_persons.py
├── test_age.py
└── test_transformer.py
tests/integration/sources/website/
├── __init__.py
├── conftest.py
├── test_ingester.py
└── test_cli.py
```

Required cases:

`test_structured.py`:
- WordPress fixture → 1 JsonLdData with name="Bellock", 2 phones, 1 email, 1 address, 2 opening_hours entries.
- Squarespace fixture → 1 JsonLdData with employees=["Jan Boonen"].
- custom_no_jsonld → empty list, no exceptions.
- Malformed JSON-LD script (e.g. trailing comma) → skipped, no crash.
- `@graph` wrapper → flattened correctly.
- `telephone` as string vs as list → both handled.

`test_contact_page.py`:
- WordPress fixture homepage with `<a href="/contact">` → `find_contact_page` returns `https://example.com/contact` (test uses dummy base URL).
- No contact links + mocked HEAD responses → known-path probing works.
- All probes fail → returns None.

`test_persons.py`:
- contact_page_with_team fixture → 3 ContactPerson (source=microdata).
- french_about_page fixture → 2 ContactPerson (source=heuristic), names extracted, roles `Gérant` / `Responsable`.
- 5 microdata persons present → capped at 4.
- No persons → empty list.

`test_age.py`:
- Mock WHOIS via monkeypatch on the to_thread call → returns ("2017", "whois").
- WHOIS raises → falls back to footer year on html.
- Footer "© 2017" → ("2017", "footer").
- No WHOIS + no footer year → (None, "none").

`test_transformer.py`:
- Full ExtractedSite (WordPress data) → emits ≥6 observations: 2 phones, 1 email, 1 address, 1 activity_summary, 1 website_age.
- Phone observations have correct PhoneValidation shape.
- Address observation populated from JSON-LD.
- Email role-account detection: `info@*` → `is_role_account=True`.
- Confidence per extraction-priorities.md (JSON-LD phone = 1.00, heuristic phone = 0.60).
- `kbo_number` propagated correctly (test with both real-KBO and 9-prefix placeholder).

`test_ingester.py` (integration):
- 3 mocked websites → N observations.
- One website returns 500 → counted as fetch_failure, others succeed.
- Re-run within 7 days → 0 new observations.
- `concurrent_companies=2` → assert max 2 in-flight simultaneously (use a counter in respx mock callback).

`test_cli.py`:
- `be-leads-enrich-website --kbos-and-websites <tsv>` → exit 0, JSON report.
- Empty file → exit 0, 0 processed.

### E. Update agent_docs/runbook.md

```
## Website enrichment

### Run by file
    cat > /tmp/sites.tsv <<EOF
    0439401387	https://bellock.be
    0502699332	https://bakk.be
    EOF
    uv run be-leads-enrich-website --kbos-and-websites /tmp/sites.tsv

### Run by DB query
    uv run be-leads-enrich-website --from-db --limit 100

### Rate
0.5 rps per host, concurrency 15 across distinct companies (websites). 100 companies ≈ 1-2 min wall-clock.

### Skip window
7 days by default — websites change slowly. Override with --skip-recent-hours.
```

### F. Update CLAUDE.md

Under "## Per-source knowledge":
```
- Website enrichment rules: `.claude/skills/website-analysis/SKILL.md` (active)
```

### G. Update CHANGELOG

```
### Added
- Skill: `website-analysis` with selectors-heuristics, age-heuristics, extraction-priorities references.
- Source: `website` — fetcher, JSON-LD extractor, contact-page discoverer, person extractor (microdata + heuristic), age estimator (WHOIS + footer), transformer, ingester.
- 5 golden HTML fixtures covering WordPress, Squarespace, custom-no-JSON-LD, person microdata, FR heuristic.
- CLI: `uv run be-leads-enrich-website --kbos-and-websites <file>` or `--from-db --limit N`.
```

### H. Optional dependency: `python-whois`

Check `pyproject.toml`. If `python-whois` is not in the runtime deps, add it:

```toml
dependencies = [
    ...,
    "python-whois>=0.9.5",
]
```

Run `uv lock` and `uv sync --locked --dev`. If `python-whois` fails to install on the user's environment, make the WHOIS path optional (try-import in `age.py`, fall back to footer-only with a logged warning).

## Verification

```bash
docker compose up -d pg
uv sync --locked --dev
uv run pytest -q -m "not network and not slow"
uv run pytest --cov=src/scraper/sources/website --cov-fail-under=85 -q tests/unit/sources/website tests/integration/sources/website
uv run mypy src/scraper
uv run ruff check src/scraper tests
uv run ruff format --check src/scraper tests

# Eyeball: structured-data extractor on WordPress fixture
uv run python -c "
from pathlib import Path
from scraper.sources.website.structured import extract_jsonld
html = Path('tests/golden/website/wordpress_local_business.html').read_text(encoding='utf-8')
data = extract_jsonld(html)
print(f'{len(data)} JSON-LD entities found')
if data:
    d = data[0]
    print(f'  type={d.type}')
    print(f'  name={d.name}')
    print(f'  telephones={d.telephones}')
    print(f'  emails={d.emails}')
    print(f'  opening_hours={d.opening_hours}')
"

# Eyeball: transformer with mocked extracted site
uv run python -c "
from pathlib import Path
from uuid import uuid4
from datetime import datetime
from scraper.sources.website.structured import extract_jsonld
from scraper.sources.website.transformer import ExtractedSite, site_to_observations
html = Path('tests/golden/website/wordpress_local_business.html').read_text(encoding='utf-8')
extracted = ExtractedSite(
    url='https://bellock.be',
    structured=extract_jsonld(html),
    contact_page_url=None,
    persons=[],
    activity_summary='Electrical installations and maintenance in Antwerp.',
    website_age=('2017', 'footer'),
    phones_found=[],
    emails_found=[],
)
obs = site_to_observations('0439401387', extracted, uuid4(), datetime.now())
print(f'{len(obs)} observations')
for o in obs:
    print(f'  {o.field} (conf={o.confidence}): {str(o.value)[:120]}')
"
```

Expect:
- First block: 1 JSON-LD entity with name=Bellock, 2 phones, 1 email, 2 opening hours.
- Second block: ≥5 observations spanning phone(s), email, address, activity_summary, website_age. Each with correct confidence.

## Stop conditions

When green:
1. Print summary: new files, tests passing on website, coverage, plus verbatim output of both `python -c` blocks.
2. Print: `Ready for prompt 10 (skill: search-cross-validation + source: ddg_brave). Commit: git add . && git commit -m "skill: website-analysis + source: website (prompt 9)".`
3. End the turn.

## Things you must NOT do

- Do not hit live websites in any test. All HTTP via respx. `analyze_url.py` is for the user, not tests.
- Do not implement Wayback CDX. Document as TODO in age-heuristics.md but defer the implementation.
- Do not implement NACE zero-shot classification. Out of scope; deferred.
- Do not implement contact-photo extraction. Out of scope.
- Do not implement language detection beyond simple stopword counting for activity_summary lang_hint.
- Do not modify existing sources or http module.
- Do not require Wayback / WHOIS at runtime — make WHOIS optional via try-import.
- Do not blanket-add new dependencies. `python-whois` is acceptable; nothing else.
