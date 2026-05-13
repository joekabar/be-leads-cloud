# Bootstrap Prompt 6 — Source: `kbopub_html` (function holders)

> **How to use:** in `be-leads/`, Git Bash, fresh `claude` session. Postgres up (`docker compose up -d pg`). Paste from `=== PROMPT ===`.

---

=== PROMPT ===

You are adding the second source: `kbopub_html`. This is the only source for **function holders / mandataires / bestuurders** — names of directors and authorized representatives. The KBO Open Data dump does NOT contain this data; it lives only on the kbopub.economie.fgov.be public search detail page (one HTML page per KBO number). This prompt builds a careful, low-rate scraper that takes a list of KBO numbers and writes function-holder observations.

## Read first

- `CLAUDE.md`
- `agent_docs/architecture.md`, `agent_docs/runbook.md`
- `.claude/skills/polite-scraping/SKILL.md` — kbopub host config (0.25 rps, concurrency 1) is the law here
- `.claude/skills/provenance-schema/SKILL.md` — function_holder JSONB shape (section 7): `{"name": "Boonen, Jan", "role": "bestuurder", "since": "2024-03-27"}`
- `.claude/skills/kbo-lookup/SKILL.md` and `.claude/skills/kbo-lookup/references/kbopub-selectors.md`
- `src/scraper/lib/http/` (PoliteClient is what you'll use)
- `src/scraper/db/repositories/observations.py`
- `src/scraper/sources/kbo_dump/transformer.py` — the pattern for row → Observation
- Project memories under `~/.claude/projects/C--Users-Oxfam-Documents-Saivy-Programs-be-leads/memory/`

## Plan first

Create `.claude/plans/2026-05-10-kbopub-html.md`:
- Status: `approved`
- Goal: "Ship the `kbopub_html` source that fetches each KBO's public-search detail page, parses out function holders, and writes them as observations. Filling the one critical data gap left by the Open Data dump."
- Scope in: source module `src/scraper/sources/kbopub_html/` (fetcher, parser, ingester, cli); HTML golden fixtures for 5 real-world test cases; selectors documented in the kbo-lookup skill; tests; CLAUDE.md / runbook / CHANGELOG updates.
- Out of scope: function-holder data cleaning (deduplication of "Boonen Jan" vs "Jan Boonen" — that's an enrichment step); any non-function-holder data (already covered by kbo_dump); NACE codes or VAT activity sub-pages (`toonvestigingps.html`); WAF bypass (kbopub is not behind WAF; if it ever 403s, escalate per polite-scraping rules).
- Acceptance: parser handles 5 golden HTML samples correctly (one with no holders, one with single bestuurder, one with multiple roles, one with French labels, one with old/struck-off entity); rate limiting enforces ≤0.25 rps observed in integration test; per-KBO fetch produces `function_holder` observations matching the JSONB shape contract; idempotent (re-running same KBO produces 0 new observations within 24h); `mypy --strict` clean; coverage on `src/scraper/sources/kbopub_html/` ≥ 90%.

## Pre-flight

```bash
docker compose up -d pg
uv run be-leads-migrate
uv run pytest -q -m "not network and not slow"   # should pass — 184 tests from previous prompts
```

## What to produce

### A. Update the skill: `.claude/skills/kbo-lookup/references/kbopub-selectors.md`

Replace the placeholder with real selectors. The kbopub detail page URL pattern is:

```
https://kbopub.economie.fgov.be/kbopub/toonondernemingps.html?lang={nl|fr}&ondernemingsnummer={KBO}
```

Document the page structure as a table:

| Section header (NL) | Section header (FR) | What it contains |
|---|---|---|
| `Algemeen` | `Général` | Status, juridical form, start date |
| `Functies` | `Fonctions` | **Function holders — what we want** |
| `Ondernemersvaardigheden` | `Aptitudes entrepreneuriales` | Required skills (e.g. electrician licence) |
| `Activiteiten` | `Activités` | NACE-Bel codes |
| `Vestigingseenheden` | `Établissements` | Branches/establishments — link to toonvestigingps.html |

The `Functies` block structure (from wave 1 walkthrough of Bellock):

```html
<tr><td class="I" colspan="4"><h2>Functies</h2></td></tr>
<tr>
  <td class="QL">Bestuurder</td>
  <td class="QL">Boonen, Jan</td>
  <td class="QL"><span class="upd">Sinds 27 maart 2024</span></td>
</tr>
```

Patterns:
- The `Functies` section is identified by `<h2>Functies</h2>` (NL) or `<h2>Fonctions</h2>` (FR).
- Each function-holder is a `<tr>` whose first `<td>` text is one of the known role labels.
- Role label is in the **first** `<td>`; person/entity name is in the **second** `<td>`; "Sinds {date}" appears in a `<span class="upd">` inside the **third** `<td>`.
- A function holder may be a natural person ("Boonen, Jan") OR a legal person ("ACME BV met KBO 0123456789"). For legal-person holders, extract both the name and the linked KBO if present.

Known NL role labels (document the full list; case-sensitive):
- `Bestuurder` (board member)
- `Gedelegeerd bestuurder` (managing director)
- `Zaakvoerder` (manager — used by BV / SRL)
- `Vaste vertegenwoordiger` (permanent representative — for legal-person directors)
- `Voorzitter`, `Ondervoorzitter` (chairman, vice-chairman)
- `Algemeen directeur`, `CEO`, `CFO`, `COO`
- `Vereffenaar` (liquidator — appears for entities being wound up)
- `Commissaris` (auditor)

Known FR equivalents:
- `Administrateur`, `Administrateur délégué`, `Gérant`, `Représentant permanent`, `Président`, `Vice-président`, `Directeur général`, `Liquidateur`, `Commissaire`.

Date parsing: "Sinds 27 maart 2024" → `2024-03-27`. Use the Dutch month dict already in scope (or define a small `MONTHS_NL` constant in this source module).

Edge cases the parser MUST handle:
- No `Functies` section at all → return empty list, no error.
- `Functies` section exists but is empty (just the header row) → return empty list.
- A `<tr>` with `class="I"` (section header marker) followed by `<h2>` is the section anchor — do not treat it as a function-holder row.
- A function holder with NO "Sinds" date → emit observation with `since=None`.
- A name containing commas — `Boonen, Jan` is one person ("Surname, Firstname" format). Don't split on commas.

### B. The source: `src/scraper/sources/kbopub_html/`

Layout:
```
src/scraper/sources/kbopub_html/
├── __init__.py
├── fetcher.py        # async HTTP via PoliteClient
├── parser.py         # BeautifulSoup → typed FunctionHolderRow list
├── transformer.py    # rows → Observation list
├── ingester.py       # orchestrate: list of KBOs → observations
└── cli.py            # be-leads-fetch-kbopub
```

#### fetcher.py

```python
async def fetch_detail_page(
    client: PoliteClient,
    kbo_number: str,
    *,
    lang: Literal["nl", "fr"] = "nl",
) -> str:
    """GET the kbopub detail page HTML for one KBO. Validates KBO via stdnum.
    Returns raw HTML. Raises BlockedError on 403 (escalate per polite-scraping),
    InvalidKboError on bad KBO."""
```

Use `urllib.parse.urlencode` for query params. Don't construct URLs by hand. The `kbo_number` parameter must be stripped of dots/spaces via `stdnum.be.vat.compact()` before insertion; the URL accepts the raw 10 digits.

A 404 from kbopub means the KBO doesn't exist (rare but possible) — raise a typed `KboNotFoundError` (add to `lib/errors.py`) and skip the entity in the ingester.

#### parser.py

```python
@dataclass(frozen=True, slots=True)
class FunctionHolderRow:
    role: str                       # "Bestuurder" | "Zaakvoerder" | ...
    role_canonical: str             # English canonical: "director" | "manager" | ...
    name: str                       # "Boonen, Jan" or "ACME BV"
    is_legal_person: bool
    linked_kbo: str | None          # for legal-person holders
    since: date | None              # parsed from "Sinds 27 maart 2024"
    raw_html: str                   # the original <tr> for forensics
```

```python
def parse_function_holders(html: str) -> list[FunctionHolderRow]: ...
def detect_lang(html: str) -> Literal["nl", "fr"]: ...   # by checking <h1>Gegevens van de geregistreerde entiteit</h1> vs French equivalent
```

Implementation:
1. Use `BeautifulSoup(html, "lxml")`.
2. Find the `<h2>` whose text is "Functies" OR "Fonctions". If absent, return `[]`.
3. From that anchor, walk forward through siblings until you hit the next section anchor (next `<tr class="I">` or `</table>`).
4. For each intermediate `<tr>`, check whether its first `<td>` text matches a known role label. If yes, parse role, name, and "Sinds" date.
5. Map NL/FR role label → canonical English (`role_canonical`):
   - Bestuurder, Administrateur → `director`
   - Gedelegeerd bestuurder, Administrateur délégué → `managing_director`
   - Zaakvoerder, Gérant → `manager`
   - Vaste vertegenwoordiger, Représentant permanent → `permanent_representative`
   - Voorzitter, Président → `chairman`
   - Ondervoorzitter, Vice-président → `vice_chairman`
   - Algemeen directeur, Directeur général → `general_director`
   - CEO → `ceo`
   - CFO → `cfo`
   - COO → `coo`
   - Vereffenaar, Liquidateur → `liquidator`
   - Commissaris, Commissaire → `auditor`
   - Unknown label → `role_canonical=role` (preserve verbatim) and log a structlog warning
6. Detect legal-person holders: if the name contains "met KBO" (NL) or "avec BCE" (FR), OR contains a 10-digit number, OR a known legal-form suffix (BV, NV, SRL, SA, BVBA, SPRL, CVBA, SCRL), set `is_legal_person=True`. Extract the linked KBO if present.

Keep the parser pure: no I/O. Take HTML, return a list. Document selector fragility in a comment block at the top — "if kbopub redesigns its detail page, this is the file to update; see the golden HTML fixtures."

#### transformer.py

```python
def function_holder_to_observation(
    kbo_number: str,
    row: FunctionHolderRow,
    run_id: UUID,
    snapshot_at: datetime,
) -> Observation:
    """Produces a function_holder observation matching the JSONB contract."""
```

The JSONB `value` shape (matching provenance-schema contract):
```json
{
  "name": "Boonen, Jan",
  "role": "bestuurder",
  "role_canonical": "director",
  "since": "2024-03-27",
  "is_legal_person": false,
  "linked_kbo": null
}
```

Confidence per `.claude/skills/provenance-schema/references/confidence.md` for `kbopub` source on `persons` column: 0.95.

`source_url` = the kbopub detail-page URL the row came from. Caller (ingester) constructs and passes it.

#### ingester.py

```python
@dataclass
class KbopubReport:
    kbos_processed: int
    kbos_not_found: int
    function_holders_total: int
    observations_inserted: int
    duration_s: float

async def ingest_kbos(
    kbo_numbers: list[str],
    pool: asyncpg.Pool,
    limiter: HostLimiter,
    *,
    batch_size: int = 50,
    lang: Literal["nl", "fr"] = "nl",
    skip_recent_hours: int = 24,
) -> KbopubReport:
    """For each KBO: check if we have a fresh kbopub observation (within skip_recent_hours)
    and skip if so; otherwise fetch, parse, transform, insert. Records a run in run_log."""
```

Behaviour:
1. Validate each KBO via `stdnum.be.vat.is_valid()`. Skip invalid ones (warn).
2. For each KBO, check the DB: `SELECT 1 FROM observations WHERE kbo_number = $1 AND source = 'kbopub' AND observed_at > NOW() - INTERVAL '$2 hours' LIMIT 1`. Skip if found.
3. Use a single `PoliteClient` instance for the entire batch — limiter enforces 0.25 rps automatically.
4. Fetch → parse → transform → accumulate observations.
5. Insert via `ObservationsRepo.insert_many()` after each `batch_size` (50) KBOs, OR at end. Don't hold all observations in memory for huge batches.
6. After ingest, call `SELECT refresh_companies_current();`.
7. Errors: `KboNotFoundError` → count and continue; `BlockedError` → fail fast (raise to caller, abort batch); other HTTP errors → retry path is handled by `request_with_retry`.

The 24-hour skip is the idempotency guarantee for repeated runs.

#### cli.py

`be-leads-fetch-kbopub` entry point. Argparse:
- `--kbos`: comma-separated list OR `@file.txt` (one KBO per line)
- `--lang`: `nl` (default) or `fr`
- `--skip-recent-hours`: default 24
- `--database-url`: optional, env fallback

In `pyproject.toml` `[project.scripts]`:
```
be-leads-fetch-kbopub = "scraper.sources.kbopub_html.cli:cli_main"
```

### C. Golden HTML fixtures

Layout:
```
tests/golden/kbopub_html/
├── README.md
├── 0439401387_bellock_nl.html              # full real-world page (sanitised: strip personal email if present)
├── 0123456749_no_holders.html              # entity with no Functies section
├── 0234567890_multiple_roles.html          # entity with bestuurder + zaakvoerder + commissaris
├── 0345678901_french.html                  # FR version with Administrateur / Gérant
└── 0456789012_legal_person_holder.html     # entity whose bestuurder is itself a legal person
```

You may **construct minimal HTML manually** that exercises each pattern — do NOT fetch real kbopub pages during this prompt (we haven't tested the rate limiter against live kbopub yet). Each fixture is small (≤200 lines), focused on the Functies block + minimal surrounding structure.

Document each fixture in the README:
- What page state it represents
- Expected parser output (number of holders, roles, dates)
- Any edge case it tests

Critical sanity check: the parser tests assert that the Bellock fixture produces exactly one holder: `Boonen, Jan, role=Bestuurder, role_canonical=director, since=2024-03-27, is_legal_person=False, linked_kbo=None`.

### D. Tests

Layout:
```
tests/unit/sources/kbopub_html/
├── __init__.py
├── test_parser.py            # against golden HTML fixtures
└── test_transformer.py       # FunctionHolderRow → Observation
tests/integration/sources/kbopub_html/
├── __init__.py
├── conftest.py               # reuses the disposable test DB from prompt 3
├── test_ingester.py          # mocked HTTP via respx, real DB
└── test_cli.py               # subprocess CLI smoke
```

Required cases:

`test_parser.py`:
- Bellock fixture → 1 holder, exact values.
- `no_holders.html` → empty list.
- `multiple_roles.html` → 3 holders with distinct role_canonical values.
- `french.html` → uses Administrateur / Gérant labels; role_canonical = director / manager.
- `legal_person_holder.html` → `is_legal_person=True`, `linked_kbo` extracted.
- A fixture with an unknown role label (e.g. "Erevoorzitter") → kept verbatim in `role` and `role_canonical`, warning logged (assert on caplog).
- Missing "Sinds" date → `since=None`, no error.

`test_transformer.py`:
- Round-trip produces an Observation with: correct kbo_number; field=`function_holder`; source=`kbopub`; confidence=0.95; value matches JSONB contract; source_url matches expected URL pattern.

`test_ingester.py` (integration):
- Mock `fetch_detail_page` via `respx` to return golden HTML for 3 KBOs.
- First run: inserts N observations matching expected count.
- Second run within 24h: 0 new observations (idempotency).
- Force `skip_recent_hours=0`: re-inserts.
- Mocked 403 response: `BlockedError` raised, batch aborts, exit code propagates.
- Mocked 404: counted as `kbos_not_found`, batch continues.

`test_cli.py` (integration):
- `--kbos 0439401387` with mocked HTTP → exit 0, report JSON printed.
- `--kbos @missing.txt` → exit 2 with clear error.
- `--kbos 0000000000` (bad checksum) → counted as invalid, exit 0 if other KBOs succeeded.

Rate-limiter assertion: in `test_ingester.py`, use `time.monotonic()` around a 5-KBO batch. With 0.25 rps + concurrency 1, 5 fetches should take ≥ 16 seconds wall clock (5 / 0.25 - first-token-free = 16). Allow 14s lower bound for safety. **Skip this on Windows** if asyncio sleep granularity makes it flaky — mark as `@pytest.mark.slow` and skip in default test runs but document expected timing.

### E. Update runbook.md

```
## Function holder enrichment (kbopub)

### Manual run for one KBO
    uv run be-leads-fetch-kbopub --kbos 0439401387

### Batch
    echo -e "0439401387\n0502699332\n0212037309" > /tmp/kbos.txt
    uv run be-leads-fetch-kbopub --kbos @/tmp/kbos.txt

### Rate
0.25 req/s, concurrency 1 — enforced by polite-scraping. 1000 KBOs ≈ 70 minutes wall-clock.

### When kbopub blocks
A 403 from kbopub is unusual. If observed:
1. Stop the batch immediately (the ingester aborts on BlockedError).
2. Wait 30 minutes; the block usually clears.
3. If persistent: lower rps to 0.1 in `.claude/skills/polite-scraping/references/per-host.toml`.
4. If still blocked: see Imperva cookie warm-up section (added in prompt 8).
```

### F. Update CLAUDE.md

Under "## Per-source knowledge" leave the kbo-lookup line in place. Function holders are still in that skill's scope — kbopub_html is the *implementation*, not a new knowledge domain.

### G. Update CHANGELOG

Under `[Unreleased]`:
```
### Added
- Source: `kbopub_html` — fetches the kbopub public-search detail page per KBO and writes function-holder observations.
- 5 golden HTML fixtures covering: single holder, no holders, multiple roles, French version, legal-person holder.
- CLI: `uv run be-leads-fetch-kbopub --kbos <list>`.
- Selectors reference in `.claude/skills/kbo-lookup/references/kbopub-selectors.md` (no longer placeholder).
```

## Verification

```bash
docker compose up -d pg
uv sync --locked --dev
uv run pytest -q -m "not network and not slow"     # full suite, including new kbopub_html
uv run pytest --cov=src/scraper/sources/kbopub_html --cov-fail-under=90 -q tests/unit/sources/kbopub_html tests/integration/sources/kbopub_html
uv run mypy src/scraper
uv run ruff check src/scraper tests
uv run ruff format --check src/scraper tests

# End-to-end with mocked HTTP — the ingester test_ingester.py already does this.
# We don't hit live kbopub from this prompt.

# Print the parser output for Bellock fixture for eyeball check:
uv run python -c "
from pathlib import Path
from scraper.sources.kbopub_html.parser import parse_function_holders
html = Path('tests/golden/kbopub_html/0439401387_bellock_nl.html').read_text()
for h in parse_function_holders(html):
    print(h)
"
```

The last `python -c` block must print one `FunctionHolderRow` matching:
```
FunctionHolderRow(role='Bestuurder', role_canonical='director', name='Boonen, Jan', is_legal_person=False, linked_kbo=None, since=datetime.date(2024, 3, 27), raw_html='...')
```

## Stop conditions

When green:
1. Print one-line summary: number of new files, tests passing on kbopub_html, coverage %, and the Bellock parser output verbatim.
2. Print verbatim: `Ready for prompt 7 (skill: nbb-financials + source: nbb_authentic). Commit: git add . && git commit -m "source: kbopub_html (prompt 6)".`
3. End the turn.

## Things you must NOT do

- Do not hit live kbopub. All HTTP goes through `respx` mocks. We've not load-tested the rate limiter against the real host yet; that's a separate manual step in prompt 11's smoke test.
- Do not add a NACE parser. Activity codes are already in the Open Data dump. The kbopub detail page also has them but we don't double-source what kbo_dump already provides — that's wasted load on a rate-sensitive host.
- Do not add a `vestigingseenheden` (establishments) parser. Establishments are in `establishment.csv` in the dump.
- Do not modify `src/scraper/sources/kbo_dump/`. Stable.
- Do not modify the `PoliteClient` or limiter. They're already correct.
- Do not add new runtime dependencies. `beautifulsoup4`, `lxml`, `httpx`, `asyncpg`, `python-stdnum` are all in the lockfile.
- Do not silence the "unknown role label" warning. It's a feature — when kbopub adds a new role label, we want to know.
- Do not implement person-deduplication. "Boonen, Jan" appearing on two different KBOs is two observations, not one. Deduplication is a downstream concern.
