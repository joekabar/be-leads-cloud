# Bootstrap Prompt 7 — Skill: `nbb-financials` + Source: `nbb_authentic`

> **How to use:** `be-leads/`, Git Bash, fresh `claude` session. Postgres up. Paste from `=== PROMPT ===`.

---

=== PROMPT ===

You are adding revenue/profit/employees data via the NBB CBSO (Centrale voor Balansen / Centrale des Bilans) public REST API. This is the ONE place to get authoritative annual financial data for Belgian companies — free, registered, JSON API. Mandatory for companies that file abbreviated/full annual accounts (most legal persons with ≥1 employee or above small-company thresholds).

This prompt builds a clean async client + ingester. You do NOT need a working API key during this prompt — all tests use recorded fixtures. The key registration is documented in the runbook for the user to do separately.

## Read first

- `CLAUDE.md`
- `.claude/skills/polite-scraping/SKILL.md` (ws.cbso.nbb.be: 1.0 rps, concurrency 2)
- `.claude/skills/provenance-schema/SKILL.md` (sections 5 + 7: financial field naming and JSONB shape)
- `.claude/skills/kbo-lookup/SKILL.md` (KBO validation patterns)
- `src/scraper/sources/kbo_dump/transformer.py` and `src/scraper/sources/kbopub_html/transformer.py` (transformer patterns)
- `src/scraper/db/fields.py` (`is_financial_field` for `revenue_<YYYY>` etc.)
- `agent_docs/runbook.md`
- Project memories

## Plan first

`.claude/plans/2026-05-10-nbb-authentic.md`:
- Status: `approved`
- Goal: "Ship `nbb-financials` skill plus `nbb_authentic` source that calls the NBB CBSO REST API for one company, parses the returned filings reference, extracts revenue/profit/employees per year, and writes financial observations."
- Scope in: skill SKILL.md + references (api-spec.md, field-mapping.md); source module `src/scraper/sources/nbb_authentic/` (client, parser, transformer, ingester, cli); CLI `uv run be-leads-fetch-nbb --kbos <list>`; recorded JSON fixtures via `pytest-recording` (cassettes mode) — but record-then-edit-by-hand into static fixture files for stability (we don't want CI to depend on cassette replay infra).
- Out of scope: the actual XBRL document parsing (we use the `/references` JSON endpoint which gives us deposit metadata + parsed key figures, not the full filing XBRL); financial ratio calculations; year-over-year deltas (downstream).
- Acceptance: client constructs valid auth headers; parser handles 3 fixture cases (company with 3 years of accounts, company with 1 year, company that never filed); transformer emits `revenue_<YYYY>` / `profit_<YYYY>` / `employees_<YYYY>` observations with correct JSONB shape; idempotency via 24h skip; mypy --strict clean; coverage ≥90%.

## Pre-flight

```bash
docker compose up -d pg
uv run be-leads-migrate
uv run pytest -q -m "not network and not slow"   # 241 tests passing baseline
```

## API contract (the truth, document it carefully)

**Base URL**: `https://ws.cbso.nbb.be`
**Product**: "Authentic Data Query" (this is the free product; "Other Data Query" exists separately for fee-based bulk)
**Auth**: two headers required on every request:
- `NBB-CBSO-Subscription-Key: <key>` — from API Management portal after subscription
- `X-Request-Id: <uuid4>` — per-request unique ID; server uses for traceability

**Endpoints actually used:**

1. `GET /authentic/legalEntity/{enterpriseNumber}/references` — returns metadata about all filings (deposits) for one entity.
2. `GET /authentic/legalEntity/{enterpriseNumber}/references/{referenceNumber}/accountingData` — returns the parsed key figures for one specific filing (revenue, profit, employees, etc.).

The `enterpriseNumber` path parameter is the 10-digit KBO WITHOUT dots (e.g. `0439401387`).

**Response shape for `/references`** (sanitised from public docs — this is what we expect):
```json
{
  "references": [
    {
      "referenceNumber": "2024-00000148",
      "depositDate": "2024-09-12",
      "exerciseStart": "2023-01-01",
      "exerciseEnd": "2023-12-31",
      "modelType": "MICRO",
      "language": "NL",
      "depositType": "DEPOSIT",
      "filingMethod": "STRUCTURED"
    },
    ...
  ]
}
```

**Response shape for `/accountingData`** — varies by `modelType`. Key fields we care about (mapped from XBRL element IDs, NBB's API returns these as JSON keys):

| JSON key | Field name | Notes |
|---|---|---|
| `code_70` or `code_700` | revenue (Omzet) | "Omzet" / "Chiffre d'affaires" — MICRO firms often null |
| `code_9904` | profit_loss_after_tax | "Te bestemmen winst (verlies) van het boekjaar" |
| `code_9087` or `code_1000` | employees_fte_avg | "Gemiddeld personeelsbestand in voltijdse equivalenten" |
| `code_99001` | exercise_end | redundancy with /references; useful as cross-check |

**Caveat (very important)**: small/micro filings often have NULL revenue. NBB MICRO model legally requires only abbreviated balance sheet; many entities don't disclose revenue. The transformer must handle NULL gracefully and NOT emit a null-valued observation.

**Empty-filings case**: `GET /references` returns `{"references": []}` for KBOs that never filed. Handle as "no observations to emit," not an error.

## What to produce

### A. Skill: `.claude/skills/nbb-financials/`

```
.claude/skills/nbb-financials/
├── SKILL.md
├── references/
│   ├── api-spec.md
│   ├── field-mapping.md
│   └── filing-types.md
└── scripts/
    └── probe.py
```

**SKILL.md frontmatter:**

```yaml
---
name: nbb-financials
description: Fetch annual financial data (revenue, profit, employees by year) from the NBB CBSO Authentic Data REST API. Free product; one subscription key per developer; identifies callers via NBB-CBSO-Subscription-Key + per-request UUID. Use whenever the user mentions revenue, omzet, chiffre d'affaires, profit, EBIT, employees by year, balansen, comptes annuels, NBB filings, annual accounts, CBSO, BNB, or financial enrichment. Always uses the /authentic/legalEntity/{KBO}/references endpoint first, then /accountingData per reference.
allowed-tools: Read, Edit, Bash, WebFetch(domain:ws.cbso.nbb.be), WebFetch(domain:consult.cbso.nbb.be), Bash(uv run python:*), Bash(uv run pytest:*), Bash(uv run be-leads-fetch-nbb:*)
---
```

**SKILL.md body** sections:

1. **When to use.** Any financial enrichment task.
2. **Two-call dance.** Always `/references` first, then `/accountingData` for each reference you want.
3. **Auth.** Two headers. The key comes from API Management portal at https://api-portal.nbb.be (after sign-up + subscribing to "Authentic Data Query"). UUID per request via `uuid.uuid4()`.
4. **Rate.** 1.0 rps with concurrency 2 from `per-host.toml`. Do not exceed — the portal has soft limits documented at "fair use."
5. **Field mapping.** Pointer to `references/field-mapping.md`. Two main fields per year: revenue (`code_70`), profit (`code_9904`), employees (`code_9087`). MICRO entities often have null revenue — handle gracefully.
6. **Filing types.** Pointer to `references/filing-types.md`. Document `MICRO | ABBREVIATED | FULL | CONSOLIDATED` and which fields are reliably populated in each.
7. **Idempotency.** 24h skip per KBO (same pattern as kbopub_html).
8. **NULL handling.** Skip emit when value is null. Don't create observations for fields the company didn't disclose — that conflates "not reported" with "reported as zero."

**`references/api-spec.md`** — the full API contract you'll implement. Worked example with the Bellock KBO `0439401387`:
- Request: `GET https://ws.cbso.nbb.be/authentic/legalEntity/0439401387/references` with both auth headers.
- Expected response: 1 or more references over the company's history (since 1989).
- Then: `GET https://ws.cbso.nbb.be/authentic/legalEntity/0439401387/references/2024-00000148/accountingData`.

Document error responses: 401 (bad key), 403 (key expired), 404 (KBO not registered), 429 (rate limited; honour Retry-After per polite-scraping skill), 503 (NBB service down — retry per polite-scraping).

**`references/field-mapping.md`** — the XBRL/JSON-key to canonical-field mapping table above, plus precedence rules:
- For revenue, prefer `code_700` (full schema) over `code_70` (abbreviated) if both present.
- For profit, `code_9904` is the canonical "result for the year after tax."
- For employees, `code_9087` is the average FTE; `code_1000` is total staff costs (don't use as employee count).

Annotate units. Revenue / profit are in EUR (no centimes — integers). Employees is decimal FTE (one decimal place common, e.g. `12.5`).

**`references/filing-types.md`** — short reference (≤60 lines):
- `MICRO`: introduced 2016. Small entities (≤350k balance sheet, ≤700k turnover, ≤10 FTE). Revenue often optional / null.
- `ABBREVIATED` (verkort/abrégé): mid-size. Revenue required.
- `FULL` (volledig/complet): large or listed. All fields.
- `CONSOLIDATED`: parent companies. Use parent's own filing for parent-level data; consolidated is downstream.

**`scripts/probe.py`** — ≤30 lines. Reads `NBB_CBSO_API_KEY` from env, calls `/references` for one hardcoded KBO (default `0439401387`), prints raw JSON. Used for manual dev — confirms the user's API key works without needing to run the full ingester.

### B. Source: `src/scraper/sources/nbb_authentic/`

```
src/scraper/sources/nbb_authentic/
├── __init__.py
├── client.py         # async HTTP wrapper with NBB-specific auth headers
├── parser.py         # JSON → typed dataclasses
├── transformer.py    # rows → Observation list
├── ingester.py       # orchestrate
└── cli.py
```

#### client.py

```python
class NbbClient:
    def __init__(
        self,
        polite_client: PoliteClient,
        subscription_key: str,
    ) -> None: ...

    async def get_references(self, kbo_number: str) -> list[ReferenceRow]: ...
    async def get_accounting_data(self, kbo_number: str, reference_number: str) -> dict[str, Any]: ...
```

Adds `NBB-CBSO-Subscription-Key` and `X-Request-Id: <uuid4()>` headers per call. Uses the PoliteClient underneath — the per-host limiter handles rate. On 404 raises typed `NbbNotFoundError`; on 401 raises `NbbAuthError`.

The KBO must be compacted via `stdnum.be.vat.compact()` before URL insertion.

#### parser.py

```python
@dataclass(frozen=True, slots=True)
class ReferenceRow:
    reference_number: str
    deposit_date: date
    exercise_start: date
    exercise_end: date
    model_type: Literal["MICRO", "ABBREVIATED", "FULL", "CONSOLIDATED", "OTHER"]
    language: str
    deposit_type: str
    filing_method: str

@dataclass(frozen=True, slots=True)
class FilingData:
    reference_number: str
    exercise_year: int
    revenue: int | None       # EUR, None = not reported
    profit_loss: int | None
    employees_fte: float | None
    model_type: str

def parse_references(payload: dict[str, Any]) -> list[ReferenceRow]: ...
def parse_accounting_data(reference: ReferenceRow, payload: dict[str, Any]) -> FilingData: ...
```

The accounting parser picks fields per `field-mapping.md` precedence rules. Tolerant of missing keys (treat as None).

`exercise_year` is derived from `exercise_end.year`.

#### transformer.py

```python
def filing_to_observations(
    kbo_number: str,
    filing: FilingData,
    run_id: UUID,
    snapshot_at: datetime,
) -> list[Observation]:
    """Up to 3 observations per filing: revenue_YYYY, profit_YYYY, employees_YYYY.
    Skips fields whose value is None."""
```

JSONB shape per field (matches provenance-schema contract):
```json
{
  "value": 30326,
  "currency": "EUR",
  "filing_ref": "2024-00000148",
  "model_type": "MICRO"
}
```

For employees:
```json
{
  "value": 12.5,
  "filing_ref": "2024-00000148",
  "model_type": "MICRO"
}
```

Confidence: 1.00 for nbb_authentic on financial fields (the source is authoritative — it IS the official register).

`source_url`: `https://ws.cbso.nbb.be/authentic/legalEntity/{kbo}/references/{ref}/accountingData`.

#### ingester.py

```python
@dataclass
class NbbReport:
    kbos_processed: int
    kbos_not_found: int
    references_total: int
    observations_inserted: int
    duration_s: float

async def ingest_kbos(
    kbo_numbers: list[str],
    pool: asyncpg.Pool,
    nbb_client: NbbClient,
    *,
    skip_recent_hours: int = 24,
    years_back: int | None = None,    # if set, only emit obs whose exercise_year >= current_year - years_back
) -> NbbReport: ...
```

Per KBO:
1. Validate KBO via stdnum.
2. Check 24h skip (any nbb_authentic observation within window → skip).
3. `get_references(kbo)`.
4. Optionally filter references by `years_back`.
5. For each reference: `get_accounting_data(...)` → `parse_accounting_data(...)` → `filing_to_observations(...)`.
6. Accumulate. Bulk-insert in batches of 100 observations.
7. After all KBOs: refresh matview.

Error policy:
- `NbbNotFoundError` → count and continue.
- `NbbAuthError` → fail fast, abort batch.
- `RateLimitedError` → handled by PoliteClient retry path.

#### cli.py

`be-leads-fetch-nbb`:
- `--kbos <list|@file>`
- `--years-back N` (optional)
- `--skip-recent-hours N` (default 24)
- `--subscription-key K` (or env `NBB_CBSO_API_KEY`)

In `pyproject.toml`:
```
be-leads-fetch-nbb = "scraper.sources.nbb_authentic.cli:cli_main"
```

### C. Fixtures (static JSON, NOT VCR cassettes)

Layout:
```
tests/golden/nbb_authentic/
├── README.md
├── 0439401387_references.json              # 3 historical filings
├── 0439401387_accounting_2024-00000148.json  # one full filing
├── 0439401387_accounting_2023-00000119.json
├── 0439401387_accounting_2022-00000091.json
├── 0502699332_references_single.json       # 1 filing only
├── 0502699332_accounting_2024-00012345.json # MICRO, revenue null
├── 9999999991_references_empty.json        # { "references": [] }
└── 0212037309_accounting_no_employees.json # ABBREVIATED with employees null
```

Hand-construct the JSON. Use values consistent with reality:
- `0439401387` (Bellock): 3 filings 2022/2023/2024. Each `accountingData` has `code_70` = revenue (e.g. 285000, 312000, 340000), `code_9904` = profit (e.g. 18000, 22000, 30326), `code_9087` = employees (e.g. 3.2, 3.5, 4.0). modelType ABBREVIATED.
- `0502699332`: 1 MICRO filing, revenue NULL, profit `8500`, employees `1.5`.
- `9999999991`: empty references.
- `0212037309`: 1 ABBREVIATED filing, revenue `45000`, employees NULL.

The fixtures must be valid against the parsers — eyeball each one for missing required fields.

### D. Tests

```
tests/unit/sources/nbb_authentic/
├── test_parser.py
└── test_transformer.py
tests/integration/sources/nbb_authentic/
├── conftest.py
├── test_client.py            # respx-mocked HTTP; verifies headers, error mapping
├── test_ingester.py          # respx + real DB
└── test_cli.py
```

Required cases:

`test_parser.py`:
- 3-references Bellock JSON → 3 ReferenceRow objects with correct types.
- Empty references → `[]`, no error.
- Accounting data with all fields → FilingData populated.
- Accounting data with revenue NULL → `revenue=None`.
- Accounting data missing employees key entirely → `employees_fte=None`.
- Accounting data with full schema (`code_700` AND `code_70` present) → prefers `code_700`.

`test_transformer.py`:
- Filing with revenue=285000, profit=18000, employees=3.2 → 3 observations.
- Filing with revenue=None → 2 observations (skip revenue), value JSONB shape correct for the 2 emitted.
- All-null filing → 0 observations.
- The `revenue_YYYY` field name matches the exercise_year.
- Confidence is exactly 1.00.

`test_client.py`:
- Mock with respx; assert request headers contain `NBB-CBSO-Subscription-Key: <value>` and a UUID-shaped `X-Request-Id`.
- 401 response → `NbbAuthError`.
- 404 response → `NbbNotFoundError`.
- 429 → respx replay 429 then 200, verify retry happened (delegated to retry module; here just assert eventual success).

`test_ingester.py`:
- 3 KBOs, all with mocked responses → N observations inserted.
- Re-run within 24h → 0 new observations.
- One KBO returns 404 → counted, batch continues.
- `years_back=2` → only emits observations for exercise_year ≥ current_year-2. Use a fixed `freeze_time` or pass a `today` parameter; do NOT use real `date.today()` in tests.

`test_cli.py`:
- `--kbos 0439401387 --subscription-key dummy` with mocked HTTP → exit 0, JSON report on stdout.
- Missing key → exit 2 with clear error.

### E. Update agent_docs/runbook.md

```
## NBB CBSO Authentic Data — registration

1. Visit https://api-portal.nbb.be
2. Create account, verify email.
3. Subscribe to the product "Authentic Data Query" (FREE).
4. Copy the Subscription Key from "Profile → Subscriptions."
5. Add to .env:
        NBB_CBSO_API_KEY=<your_key>
6. Verify:
        uv run python .claude/skills/nbb-financials/scripts/probe.py

Activation note: subscriptions are typically active within minutes, sometimes
takes 1-2 hours. If `/references` returns 401 after 24h, contact api-portal
support via the portal (their address rotates; do not put it in the repo).

## NBB rate
1.0 rps, concurrency 2 — enforced by polite-scraping skill. Batch of 1000 KBOs:
~17 min wall-clock (2 references × 1 accounting call avg per KBO).
```

### F. Update .env.example

Uncomment / activate (keep value blank):
```
NBB_CBSO_API_KEY=
```

### G. Update CLAUDE.md

Under "## Per-source knowledge":
```
- NBB financials rules: `.claude/skills/nbb-financials/SKILL.md` (active)
```

### H. Update CHANGELOG

```
### Added
- Skill: `nbb-financials` with api-spec, field-mapping, filing-types references.
- Source: `nbb_authentic` — async REST client + parser + ingester for NBB CBSO Authentic Data API.
- 8 static JSON fixtures covering 3-year, 1-year, empty, and null-field cases.
- CLI: `uv run be-leads-fetch-nbb --kbos <list>`.
- .env.example: NBB_CBSO_API_KEY entry activated.
```

## Verification

```bash
docker compose up -d pg
uv sync --locked --dev
uv run pytest -q -m "not network and not slow"
uv run pytest --cov=src/scraper/sources/nbb_authentic --cov-fail-under=90 -q tests/unit/sources/nbb_authentic tests/integration/sources/nbb_authentic
uv run mypy src/scraper
uv run ruff check src/scraper tests
uv run ruff format --check src/scraper tests

# Eyeball: feed the Bellock 3-filing fixtures through the transformer
uv run python -c "
import json
from pathlib import Path
from uuid import uuid4
from datetime import datetime
from scraper.sources.nbb_authentic.parser import parse_references, parse_accounting_data
from scraper.sources.nbb_authentic.transformer import filing_to_observations

base = Path('tests/golden/nbb_authentic')
refs = parse_references(json.loads((base / '0439401387_references.json').read_text()))
print(f'{len(refs)} references')
all_obs = []
for r in refs:
    acc = json.loads((base / f'0439401387_accounting_{r.reference_number}.json').read_text())
    filing = parse_accounting_data(r, acc)
    obs = filing_to_observations('0439401387', filing, uuid4(), datetime.now())
    all_obs.extend(obs)
print(f'{len(all_obs)} observations total')
for o in all_obs:
    print(f'  {o.field}: {o.value}')
"
```

The last block must print:
- `3 references`
- ≥6 observations total (3 years × at least 2 fields per year)
- Each observation a `revenue_YYYY`, `profit_YYYY`, or `employees_YYYY`

## Stop conditions

When green:
1. Print summary: new files, tests passing on nbb_authentic, coverage, plus the verbatim output of the Bellock fixture pipeline (the `len(all_obs)` line and the first 3 `o.field: o.value` lines).
2. Print: `Ready for prompt 8 (skill: goudengids-listing + source: goudengids). Commit: git add . && git commit -m "skill: nbb-financials + source: nbb_authentic (prompt 7)".`
3. End the turn.

## Things you must NOT do

- Do not hit the live NBB API. All tests use mocked HTTP. (The probe.py script is for the user, not for tests.)
- Do not parse XBRL files. We use the API's parsed `/accountingData` endpoint, not the raw XBRL deposits.
- Do not emit observations for null values. "Not reported" is a distinct state from "reported as zero" and conflating them poisons analytics.
- Do not assume `code_70` is always present. The mapping table has precedence; respect it.
- Do not add a `consult.cbso.nbb.be` HTML scraper. The Authentic Data API covers the same data programmatically; HTML scraping of consult.cbso would be fragile and duplicate.
- Do not implement consolidated-filing parent lookup. Out of scope.
- Do not modify `src/scraper/lib/http/` or other sources.
- Do not add `pytest-recording` cassettes. Use static JSON fixtures only — they're version-controlled, diffable, and don't depend on replay infrastructure.
