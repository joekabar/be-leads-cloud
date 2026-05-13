# Bootstrap Prompt 5 — Skill: `kbo-lookup` + Source: `kbo_dump`

> **How to use:** in `be-leads/`, Git Bash terminal, fresh `claude` session. Postgres must be running (`docker compose up -d pg`). You should have a registered KBO Open Data account, but you do NOT need to have downloaded the actual ZIP. This prompt builds the ingester and tests it against a synthetic mini-ZIP fixture. Paste from `=== PROMPT ===` to the end.

---

=== PROMPT ===

You are shipping the canonical-company table foundation: the `kbo-lookup` skill and the first source module, `kbo_dump`. After this prompt, the project can ingest the KBO Open Data daily ZIP (full or update file) into Postgres as a stream of `Observation` rows, all tagged with `source=kbo_dump`. This is the single largest prompt in the sequence — budget 30–60 minutes.

## Read first

- `CLAUDE.md`
- `agent_docs/architecture.md`, `agent_docs/data-model.md`, `agent_docs/runbook.md`
- `.claude/skills/polite-scraping/SKILL.md`, `.claude/skills/provenance-schema/SKILL.md`, `.claude/skills/belgian-phone-validation/SKILL.md`
- `src/scraper/db/models.py` (Observation contract)
- `src/scraper/db/fields.py` and `sources.py`
- `src/scraper/db/repositories/observations.py` (insert_many is the bulk path you'll use)
- `src/scraper/lib/validators/phone.py` (you'll call validate_phone on contact rows)
- Project memories under `~/.claude/projects/C--Users-Oxfam-Documents-Saivy-Programs-be-leads/memory/`

## Plan first

Create `.claude/plans/2026-05-10-kbo-dump.md` from the template:
- Status: `approved`
- Goal: "Ship the `kbo-lookup` skill (covers Open Data and kbopub) plus the `kbo_dump` source that ingests a KBO Open Data ZIP (full or update) into the observations table with full provenance."
- Scope in: skill SKILL.md + references (open-data-schema.md, kbopub-selectors.md placeholder, samples/); source module `src/scraper/sources/kbo_dump/` (downloader, parser, ingester); CLI `uv run be-leads-ingest-kbo --zip <path>`; tests with a synthetic mini-ZIP fixture; updates to CLAUDE.md / runbook / CHANGELOG.
- Out of scope: kbopub HTML scraping (only the skill REFERENCES it; the implementation comes in prompt 6); function-holder enrichment; the smart-refresh scheduler.
- Acceptance: skill loads on KBO-related prompts; ingester processes a 50-row synthetic ZIP into ≥200 observations (multi-field per company) tagged `source=kbo_dump`; idempotent on re-ingest (same ZIP twice produces no duplicates); supports both `Full` and `Update` ZIPs; `mypy --strict` clean; coverage on `src/scraper/sources/kbo_dump/` ≥ 90%; integration test inserts to the disposable test DB and verifies `companies_current` refresh works.

## Pre-flight

```bash
docker compose up -d pg
docker compose ps                          # pg must be (healthy)
uv run be-leads-migrate                    # schema must be at version 2
```

## What to produce

### A. The skill: `.claude/skills/kbo-lookup/`

Layout:
```
.claude/skills/kbo-lookup/
├── SKILL.md
├── references/
│   ├── open-data-schema.md
│   ├── kbopub-selectors.md
│   ├── checksum.md
│   └── samples/
│       └── README.md             # placeholder; HTML samples come in prompt 6
└── scripts/
    └── validate_kbo.py
```

**`SKILL.md` frontmatter:**

```yaml
---
name: kbo-lookup
description: Interact with the Belgian KBO/CBE registry. Covers the FREE daily KBO Open Data ZIP (bulk canonical company facts; download from kbopub.economie.fgov.be/kbo-open-data) and the kbopub HTML public-search detail page (the only place function holders / mandataires / bestuurders live). Validates 10-digit enterprise numbers via stdnum.be.vat (mod-97 checksum); supports both legacy 0xxx and modern 1xxx prefixes. Use whenever the user mentions KBO, CBE, BCE, BTW, ondernemingsnummer, numéro d'entreprise, kbopub, KBO Open Data, mandataires, bestuurders, or anything that looks like a 10-digit Belgian company number.
allowed-tools: Read, Edit, Bash, WebFetch(domain:kbopub.economie.fgov.be), WebFetch(domain:economie.fgov.be), Bash(uv run python:*), Bash(uv run pytest:*), Bash(uv run be-leads-ingest-kbo:*), Bash(uv run be-leads-validate-kbo:*)
---
```

**`SKILL.md` body** — sections:

1. **When to use.** Any time you parse, validate, store, or look up a KBO number; any time you ingest from the Open Data ZIP; any time you scrape a kbopub detail page (prompt 6).
2. **Two paths, two purposes.**
   - **Open Data dump (free, daily, free email registration):** canonical bulk source. Updated daily. CSVs inside a ZIP. The `kbo_dump` source ingests this into observations.
   - **kbopub HTML public search:** the **only** source for function holders / mandataires / bestuurders. Rate-limited; reserved for per-company enrichment lookups (prompt 6).
3. **Checksum.** Use `stdnum.be.vat.is_valid()` / `compact()` / `validate()`. Never roll your own. Algorithm summary in `references/checksum.md`. Modern numbers may start with `1` (not just `0`).
4. **Open Data schema.** Point to `references/open-data-schema.md` — that file documents `enterprise.csv`, `establishment.csv`, `denomination.csv`, `address.csv`, `contact.csv`, `activity.csv`, `branch.csv`, `code.csv`, `meta.csv`.
5. **Field → observation mapping.** Document which Open Data row produces which `field` value:
   - `enterprise.csv` row → `name` (from denomination), `founding_date` (from StartDate), `status` (always "active" in this snapshot)
   - `address.csv` → `address` (one observation per address)
   - `contact.csv` rows → `phone`, `email`, `website` (one observation per row, classified by ContactType)
   - `activity.csv` → `nace_code` (one observation per row)
6. **kbopub anti-block notes.** Document the planned approach for prompt 6 (Playwright-cookie pattern via polite-scraping skill, rates from `per-host.toml`).
7. **CLI.** Two commands documented:
   - `uv run be-leads-validate-kbo "0439.401.387"` — quick checksum check
   - `uv run be-leads-ingest-kbo --zip <path.zip>` — ingest a Full or Update ZIP

**`references/open-data-schema.md`** — document every CSV's columns with types, primary keys, foreign keys, and Belgian-specific gotchas:

- **CSV characteristics**: comma delimiter, double-quote text qualifier, dot decimal, `dd-mm-yyyy` dates, NULL = empty between adjacent commas.
- **`meta.csv`** — `Variable, Value` pairs. Known keys: `SnapshotDate`, `ExtractTimestamp`, `ExtractType` (`Full` or `Update`), `ExtractNumber`, `Version`.
- **`code.csv`** — code dictionary. Columns: `Category, Code, Language (DE|EN|FR|NL), Description`.
- **`enterprise.csv`** — columns: `EnterpriseNumber, Status (always AC=active), JuridicalSituation, TypeOfEnterprise (1=legal person, 2=natural person), JuridicalForm, JuridicalFormCAC, StartDate`.
- **`establishment.csv`** — `EstablishmentNumber, StartDate, EnterpriseNumber`.
- **`denomination.csv`** — `EntityNumber, Language, TypeOfDenomination, Denomination`.
- **`address.csv`** — `EntityNumber, TypeOfAddress, CountryNL, CountryFR, Zipcode, MunicipalityNL, MunicipalityFR, StreetNL, StreetFR, HouseNumber, Box, ExtraAddressInfo, DateStrikingOff`.
- **`contact.csv`** — `EntityNumber, EntityContact (3-char code), ContactType (5-char: TEL, EMAIL, WEB), Value`.
- **`activity.csv`** — `EntityNumber, ActivityGroup, NaceVersion (2003|2008|2025), NaceCode, Classification`.
- **`branch.csv`** — `Id, StartDate, EnterpriseNumber`.

Document the **Update file** mechanic: each table has `_delete.csv` and `_insert.csv`. To apply: delete rows whose EntityNumber appears in delete file, then insert rows from insert file. Code.csv is full (not differential) in update files.

What's NOT in the dump (caveat): **function holders / mandataires** are not in any of these tables. They're only on kbopub HTML.

**`references/kbopub-selectors.md`** — placeholder for prompt 6. Just a header and a TODO note. Real selectors come when we scrape that site.

**`references/checksum.md`** — short doc. Algorithm: `int(first8) % 97 == 97 - int(last2)`. Worked example with KBO `0439401387`. Belgium expanded allocation to allow leading `1` as well as `0`. Use `stdnum.be.vat`, do not reimplement.

**`scripts/validate_kbo.py`** — CLI: takes a number, calls `stdnum.be.vat.is_valid()`, prints result. ≤20 lines.

### B. Python module: `src/scraper/sources/kbo_dump/`

Layout:
```
src/scraper/sources/
├── __init__.py
└── kbo_dump/
    ├── __init__.py
    ├── parser.py           # CSV → typed rows
    ├── transformer.py      # rows → Observation list
    ├── ingester.py         # orchestrates: ZIP → DB
    ├── downloader.py       # SFTP / portal stub (deferred; placeholder + auth instructions)
    └── cli.py              # be-leads-ingest-kbo entry point
```

#### parser.py

Dataclasses (frozen, slots) mirroring the CSV schemas:

```python
@dataclass(frozen=True, slots=True)
class EnterpriseRow:
    enterprise_number: str       # canonicalized 10 digits, no dots
    status: str
    juridical_situation: str
    type_of_enterprise: str      # "1" or "2"
    juridical_form: str | None
    juridical_form_cac: str | None
    start_date: date | None

@dataclass(frozen=True, slots=True)
class AddressRow:
    entity_number: str
    type_of_address: str
    zipcode: str | None
    municipality_nl: str | None
    municipality_fr: str | None
    street_nl: str | None
    street_fr: str | None
    house_number: str | None
    box: str | None

@dataclass(frozen=True, slots=True)
class ContactRow:
    entity_number: str
    contact_type: str            # TEL | EMAIL | WEB
    value: str

@dataclass(frozen=True, slots=True)
class DenominationRow:
    entity_number: str
    language: str
    type_of_denomination: str    # 001 = legal name, 002 = abbreviation, 003 = commercial name
    denomination: str

@dataclass(frozen=True, slots=True)
class ActivityRow:
    entity_number: str
    activity_group: str
    nace_version: str            # "2003" | "2008" | "2025"
    nace_code: str
    classification: str          # MAIN | SECO | AUXI
```

Functions:

```python
def parse_meta(zip_path: Path) -> dict[str, str]:
    """Read meta.csv as key/value pairs. Returns {} if missing."""

def iter_enterprises(zip_path: Path) -> Iterator[EnterpriseRow]:
    """Yield rows from enterprise.csv (Full) or enterprise_insert.csv (Update)."""

def iter_addresses(zip_path: Path) -> Iterator[AddressRow]: ...
def iter_contacts(zip_path: Path) -> Iterator[ContactRow]: ...
def iter_denominations(zip_path: Path) -> Iterator[DenominationRow]: ...
def iter_activities(zip_path: Path) -> Iterator[ActivityRow]: ...

def detect_extract_type(zip_path: Path) -> Literal["Full", "Update"]:
    """Reads meta.csv ExtractType, falls back to filename pattern."""
```

Implementation rules:
- Use `zipfile.ZipFile` + `csv.DictReader` with `quoting=csv.QUOTE_ALL`.
- Parse dates with `datetime.strptime(s, "%d-%m-%Y").date()` — note Belgian date format.
- Normalize enterprise numbers via `stdnum.be.vat.compact()` on every row.
- Empty-string fields become `None`.
- Stream rows lazily (`yield`), never load entire CSVs into memory. The full enterprise.csv is ~250 MB / ~2M rows — must work on machines with 8 GB RAM.

#### transformer.py

Pure functions that map rows to `Observation` objects. No DB access, no I/O.

```python
def enterprise_to_observations(
    row: EnterpriseRow, run_id: UUID
) -> list[Observation]:
    """Produce founding_date and status observations."""

def denomination_to_observation(
    row: DenominationRow, run_id: UUID
) -> Observation | None:
    """Only type_of_denomination=001 (legal name) becomes a 'name' observation.
    002 (abbreviation) and 003 (commercial name) are stored as separate 'name' obs
    with the value JSONB including 'type': 'commercial' or 'abbreviation'."""

def address_to_observation(
    row: AddressRow, run_id: UUID
) -> Observation | None:
    """Produce one 'address' observation. Use NL fields preferentially,
    fall back to FR. Skip if no street."""

def contact_to_observation(
    row: ContactRow, run_id: UUID
) -> Observation | None:
    """TEL → 'phone' (calls validate_phone, skip on InvalidPhoneError),
    EMAIL → 'email', WEB → 'website'."""

def activity_to_observation(
    row: ActivityRow, run_id: UUID
) -> Observation | None:
    """Produce 'nace_code' observation. Skip if classification != MAIN
    AND prefer the latest NaceVersion present for that entity (caller handles
    dedup; transformer just produces one obs per row)."""
```

Each observation:
- `kbo_number` = the row's EntityNumber compacted (10 digits)
- `source` = `"kbo_dump"`
- `confidence` = per `references/confidence.md` priors (e.g. phone=0.95, name=1.00 for legal name, etc.)
- `value` JSONB shaped per `provenance-schema` SKILL.md section 7
- `raw_value` = the original raw string field
- `source_url` = `None` (no per-row URL in a bulk dump)
- `observed_at` = the snapshot date from `meta.csv` (caller passes it in)

The phone transformer must call `validate_phone()` from prompt 4. If `InvalidPhoneError` is raised, log a structlog warning with `kbo_number` and the raw value, and skip (don't crash the whole ingest). Track these skips in a counter returned to the ingester for the run summary.

#### ingester.py

Orchestrates the full pipeline:

```python
@dataclass
class IngestReport:
    extract_type: Literal["Full", "Update"]
    snapshot_date: date
    enterprises_processed: int
    observations_inserted: int
    phones_invalid_skipped: int
    duration_s: float

async def ingest_zip(
    zip_path: Path,
    pool: asyncpg.Pool,
    *,
    batch_size: int = 5000,
    sector_filter: list[str] | None = None,
    city_filter: list[str] | None = None,
) -> IngestReport:
    """Stream the ZIP through transformers and bulk-insert via ObservationsRepo.insert_many.
    Records a run in run_log. Idempotent: re-running the same ZIP must not duplicate observations."""
```

**Idempotency strategy**: this is the single most important design point. Two acceptable patterns; pick **A**:

- **Pattern A (chosen)** — before insert, check `observations` for the same `(kbo_number, field, value, source)` tuple within the last 24h. If present, skip. This is cheap when batched (one `SELECT ... WHERE (kbo_number, field, value::text, source) IN (...)`).
- Pattern B — synthesise a deterministic `dedup_hash` column. Rejected (schema migration just for ingestion).

For Update ZIPs: process `_delete.csv` first by writing a `status='delete_marker'` observation (so history is preserved — we do NOT delete observations physically). Then process `_insert.csv` as normal. The `companies_current` matview refresh resolves to the latest valid observation.

Wait — `status='delete_marker'` for the entity, not the field. Let me restate: when an `enterprise_delete.csv` row indicates EnterpriseNumber X is no longer active, write one observation: `(kbo_number=X, field='status', value={"value":"deleted","reason":"open_data_update"}, source='kbo_dump')`. This is the cleanest path that respects append-only.

After all inserts, call `SELECT refresh_companies_current();` once (not concurrent for the first run; CONCURRENTLY for subsequent).

**Optional filters** (defer the filter implementation if it adds risk — at minimum accept the parameters and document them as TODO if the streaming filter is hard):

- `sector_filter`: list of 2-digit NACE codes; an enterprise is kept only if any activity row's `nace_code` starts with one of these.
- `city_filter`: list of municipality strings (case-insensitive); an enterprise is kept only if any address row's `municipality_nl` OR `municipality_fr` matches.

If filtering is implemented: two-pass (first pass collects entity numbers that match; second pass emits observations only for them). Acceptable to load matched entity numbers into a `set[str]` in memory — even 50k matches is ≤5 MB.

#### downloader.py

A placeholder + clear instructions. **Do not** implement the actual SFTP / portal HTTP login in this prompt — it's procedurally gated (account approval, possibly SFTP request via email) and we don't have a working account guaranteed yet.

The module exports:

```python
class KboDumpDownloader:
    """Stub. Real downloader to be implemented when SFTP access is granted."""
    def __init__(self, settings: Settings): ...
    async def download_latest_full(self, dest: Path) -> Path:
        raise NotImplementedError(
            "Manual: log in to https://kbopub.economie.fgov.be/kbo-open-data/login, "
            "download the latest Full ZIP, save to data/kbo_dump/. "
            "Once SFTP access is granted, implement async download here."
        )
    async def download_latest_update(self, dest: Path) -> Path: ...
```

Add a section to `agent_docs/runbook.md` documenting the manual download path and the SFTP-request email.

#### cli.py

`be-leads-ingest-kbo` entry point. Argparse: `--zip <path>` (required), `--database-url <DSN>` (optional, falls back to env), `--no-refresh` flag (skip the matview refresh, useful for tests).

Wire into `pyproject.toml` under `[project.scripts]`:
```
be-leads-ingest-kbo = "scraper.sources.kbo_dump.cli:cli_main"
be-leads-validate-kbo = "scraper.sources.kbo_dump.cli:cli_validate"
```

`cli_validate` is a thin wrapper around `stdnum.be.vat.is_valid()`.

### C. Tests

Layout:
```
tests/
├── unit/sources/kbo_dump/
│   ├── __init__.py
│   ├── test_parser.py
│   └── test_transformer.py
├── integration/sources/kbo_dump/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_ingester.py
│   └── test_cli.py
└── golden/kbo_dump/
    ├── README.md                       # documents the synthetic fixture
    └── synthetic_mini/                  # NOT a real ZIP — a directory of fake CSVs the tests zip on the fly
        ├── meta.csv
        ├── enterprise.csv
        ├── denomination.csv
        ├── address.csv
        ├── contact.csv
        └── activity.csv
```

**Synthetic fixture content** — small but exercises edge cases. Generate exactly:

- `meta.csv` — 5 rows: SnapshotDate=15-04-2026, ExtractTimestamp, ExtractType=Full, ExtractNumber=42, Version=R018.00.
- `enterprise.csv` — header + 5 rows. Include:
  - One known good (Bellock-equivalent: `0439401387, AC, 000, 1, 014, 014, 28-12-1989`).
  - One natural-person (`0123456749` or any valid checksum, with `TypeOfEnterprise=2`).
  - One that starts with `1` (modern allocation, e.g. `1000000000` if checksum is valid — pick something whose `stdnum.be.vat.is_valid()` returns True).
  - One with no juridical_form (NULL/empty column).
  - One with a recent StartDate.
- `denomination.csv` — header + 7 rows mixing legal names (001), abbreviations (002), commercial names (003) across the 5 enterprises.
- `address.csv` — header + 6 rows. Include: one Antwerpen address (zip 2060), one Brussels (1000), one French-only (Liège, FR fields filled, NL empty), one with NULL street (must be skipped by transformer).
- `contact.csv` — header + 10 rows. Include: 1 valid Antwerpen landline (`03 236 13 06`), 1 valid Liège landline (`04 220 11 22`), 1 mobile (`0474 12 34 56`), 1 valid email (`info@example.be`), 1 valid website (`https://example.be`), 1 INVALID phone (`123` — must trigger the validator skip path), 1 EMAIL with extra whitespace.
- `activity.csv` — header + 8 rows. Include: NaceVersion 2008 and 2025 entries (transformer should keep both for now; dedup is matview's job). Include MAIN, SECO, and AUXI classifications.

The fixture directory checks into git. Tests zip it on the fly:

```python
@pytest.fixture
def synthetic_zip(tmp_path: Path) -> Path:
    src = Path("tests/golden/kbo_dump/synthetic_mini")
    out = tmp_path / "KboOpenData_42_2026_04_Full.zip"
    with zipfile.ZipFile(out, "w") as zf:
        for f in src.glob("*.csv"):
            zf.write(f, arcname=f.name)
    return out
```

Unit tests:
- `test_parser.py` — exercise each `iter_*` function against the synthetic mini fixture. Assert row counts, date parsing, NULL handling, KBO compaction.
- `test_transformer.py` — pure functions. Each transformer test feeds one row, asserts the Observation contents (field, source, confidence, value shape).

Integration tests (Postgres):
- `test_ingester.py`:
  1. `ingest_zip` on the synthetic fixture → produces N observations.
  2. Re-run `ingest_zip` → produces 0 new observations (idempotent).
  3. After ingest, query `companies_current` for a known KBO → returns the legal name, founding date, etc.
  4. Invalid phone in the fixture → skipped, `phones_invalid_skipped == 1` in the report.
  5. Update ZIP (synthesise on the fly — zip `enterprise_delete.csv` and `enterprise_insert.csv`) → produces `status=deleted` observation.
- `test_cli.py`:
  1. Subprocess `uv run be-leads-ingest-kbo --zip <synthetic> --no-refresh` against the test DB. Assert exit 0, report JSON printed to stdout.
  2. Subprocess `uv run be-leads-validate-kbo "0439.401.387"` prints `valid` and exits 0.
  3. Subprocess `uv run be-leads-validate-kbo "123"` prints `invalid` and exits 2.

### D. Update agent_docs/runbook.md

Append:

```
## KBO Open Data ingestion

### One-time setup
1. Register: https://kbopub.economie.fgov.be/kbo-open-data/login?lang=en
2. Verify email; accept the licence.
3. (Optional, for automation) email kbo-bce-webservice@economie.fgov.be requesting SFTP credentials.

### Manual ZIP download
1. Log in to the portal.
2. Download `KboOpenData_<n>_<YYYY>_<MM>_Full.zip` to `data/kbo_dump/`.
3. Ingest: `uv run be-leads-ingest-kbo --zip data/kbo_dump/KboOpenData_*_Full.zip`
4. First Full ZIP: expect ~2M enterprise rows, ~30 min ingest, ~1 GB Postgres after refresh.
5. Daily Update ZIPs: ~50k rows, ~2 min ingest.

### Refresh strategy
- Weekly cron: full ZIP, full re-ingest.
- Daily cron (between weeklies): apply Update ZIPs.
- After each ingest: `SELECT refresh_companies_current();` runs automatically.

### Schema reference
See .claude/skills/kbo-lookup/references/open-data-schema.md.
```

### E. Update CLAUDE.md

Under "## Per-source knowledge":
```
- KBO / CBE rules (Open Data + kbopub): `.claude/skills/kbo-lookup/SKILL.md` (active)
```

### F. Update CHANGELOG

Under `[Unreleased]`:
```
### Added
- Skill: `kbo-lookup` (Open Data daily ZIP + kbopub HTML for function holders).
- Source: `kbo_dump` — parser, transformer, ingester for KBO Open Data Full and Update ZIPs.
- CLI: `uv run be-leads-ingest-kbo --zip <path>` and `uv run be-leads-validate-kbo <number>`.
- Golden fixture: `tests/golden/kbo_dump/synthetic_mini/` (≈40 rows covering the edge cases documented in the schema reference).
```

## Verification — run before stopping

```bash
docker compose up -d pg
uv sync --locked --dev
uv run pytest -q -m "not network and not slow"
uv run pytest --cov=src/scraper/sources/kbo_dump --cov-fail-under=90 -q tests/unit/sources/kbo_dump tests/integration/sources/kbo_dump
uv run mypy src/scraper
uv run ruff check src/scraper tests
uv run ruff format --check src/scraper tests
uv run be-leads-validate-kbo "0439.401.387"   # → "valid"
uv run be-leads-validate-kbo "0439401388"      # → "invalid", exit 2 (last digit wrong)
uv run be-leads-validate-kbo "BE0439401387"    # → "valid"

# End-to-end: build the synthetic ZIP, ingest it, query companies_current
uv run python -c "
import zipfile, pathlib
src = pathlib.Path('tests/golden/kbo_dump/synthetic_mini')
out = pathlib.Path('/tmp/test_ingest.zip')
with zipfile.ZipFile(out, 'w') as zf:
    for f in src.glob('*.csv'):
        zf.write(f, arcname=f.name)
print(out)
"
uv run be-leads-ingest-kbo --zip /tmp/test_ingest.zip
docker compose exec pg psql -U leads -d leads -c "SELECT COUNT(*) AS observations FROM observations WHERE source='kbo_dump';"
docker compose exec pg psql -U leads -d leads -c "SELECT kbo_number, field, value FROM companies_current WHERE kbo_number='0439401387' ORDER BY field;"
```

The last `psql` query must return ≥3 rows for Bellock: at minimum `founding_date`, `name`, `address`. Eyeball them.

## Stop conditions

When all green:
1. Print one-line summary: number of new files, total tests passing (separate count for kbo_dump), coverage %, observations inserted from the synthetic fixture.
2. Print verbatim: `Ready for prompt 6 (source: kbopub HTML scraper for function holders). Commit: git add . && git commit -m "skill: kbo-lookup + source: kbo_dump (prompt 5)".`
3. End the turn.

## Things you must NOT do

- Do not implement the kbopub HTML scraper. That's prompt 6.
- Do not implement the SFTP downloader. `downloader.py` is a stub.
- Do not download an actual KBO Open Data ZIP. Use only the synthetic mini fixture.
- Do not add new runtime deps. `asyncpg`, `pydantic`, `python-stdnum`, `phonenumbers`, `structlog` are in the lockfile. `zipfile`, `csv`, `datetime` are stdlib.
- Do not modify pre-prompt-5 source modules (`src/scraper/db/`, `src/scraper/lib/`). They're stable. The only acceptable change is to add an `__init__.py` to `src/scraper/sources/` if it doesn't exist.
- Do not change the observation JSONB shapes from `provenance-schema` skill section 7. The shapes are contracts.
- Do not skip the idempotency test. Re-running the same ZIP MUST produce zero new observations.
