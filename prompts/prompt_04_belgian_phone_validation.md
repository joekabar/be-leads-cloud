# Bootstrap Prompt 4 — Skill: `belgian-phone-validation`

> **How to use:** in `be-leads/`, Git Bash terminal, fresh `claude` session. Postgres doesn't need to be running for this prompt — no DB integration. Paste everything below `=== PROMPT ===`.

---

=== PROMPT ===

You are adding the third skill: `belgian-phone-validation`. This is a small, self-contained, data-heavy skill. Its outputs are used by every source that touches phone numbers (kbo_dump, kbopub, goudengids, website). Do nothing outside the scope listed.

## Read first

- `CLAUDE.md`
- `.claude/skills/polite-scraping/SKILL.md` (style template)
- `.claude/skills/provenance-schema/SKILL.md` (specifically the `phone` JSONB shape under section 7)
- `src/scraper/db/models.py` (to understand the `Observation.value` JSONB shape contract for phones)
- The three memory files under `~/.claude/projects/C--Users-Oxfam-Documents-Saivy-Programs-be-leads/memory/`

## Plan first

Create `.claude/plans/2026-05-10-belgian-phone-validation.md` from the template:
- Status: `approved`
- Goal: "Ship the `belgian-phone-validation` skill and the supporting `src/scraper/lib/validators/phone.py` module that normalizes a Belgian phone string to the canonical `{e164, raw, type, region}` JSONB shape used in observations."
- Scope in: skill SKILL.md + references (prefixes.tsv, numbering-plan-rules.md) + scripts (validate.py CLI); `src/scraper/lib/validators/__init__.py` + `phone.py`; tests; CLAUDE.md and CHANGELOG entries.
- Out of scope: phone-vs-city consistency checking (that's an enrichment pipeline step, not part of validation); KBO validators (prompt 5); NACE matching (later).
- Acceptance: skill loads on phone-related prompts; CLI `uv run be-leads-validate-phone "03 236 13 06"` prints the canonical JSON; the Python API returns a `PhoneValidation` Pydantic model matching the observation JSONB shape; `mypy --strict` clean; coverage on `src/scraper/lib/validators/phone.py` ≥95%.

## What to produce

### A. The skill: `.claude/skills/belgian-phone-validation/`

Layout:
```
.claude/skills/belgian-phone-validation/
├── SKILL.md
├── references/
│   ├── prefixes.tsv
│   └── numbering-plan-rules.md
└── scripts/
    └── validate.py
```

**`SKILL.md` frontmatter:**

```yaml
---
name: belgian-phone-validation
description: Validate, normalize, and classify Belgian phone numbers. Converts any reasonable Belgian phone string to a canonical `{e164, raw, type, region, original_carrier}` JSONB shape suitable for observations. Handles the Liège trap (04 9-digit landline vs 04xx 10-digit mobile), mobile prefixes 0455/0456/0460/0465-0468/047x/048x/049x, premium 070/090x, M2M 077, freephone 0800, and historic-carrier mapping (note: number portability since 2002 makes this allocation-only). Use whenever the user normalizes a Belgian phone, parses BIPT prefixes, sees a phone field in any source, or asks whether a number is a mobile/landline/VoIP/premium.
allowed-tools: Read, Edit, Bash(uv run python:*), Bash(uv run pytest:*), Bash(uv run be-leads-validate-phone:*)
---
```

**`SKILL.md` body** — seven sections, ≤15 lines each:

1. **When to use.** Phone-related fields in any source module; data ingestion that needs the canonical JSONB shape; any "what city is this number from" question.
2. **Canonical output shape.** Match the `provenance-schema` skill's `phone` JSONB definition:
   ```json
   {"e164": "+3232361306", "raw": "03 236 13 06", "type": "fixed_line", "region": "Antwerp", "original_carrier": null}
   ```
   `type` is one of `fixed_line | mobile | premium_rate | toll_free | shared_cost | m2m | voip | unknown`. `region` for fixed_line is the BIPT-area city/region name; for mobile it's `null`. `original_carrier` for mobile is the BIPT-allocated carrier (Proximus / Orange / Telenet / BASE / Lycamobile) — historical only, NOT current carrier after portability.
3. **Use `phonenumbers` first, then refine.** `phonenumbers.parse(s, "BE")` → if valid, classify via `number_type`. Belgian-specific refinements (mobile sub-allocation, premium tier within 090x) come from `references/prefixes.tsv`.
4. **The Liège trap.** Document the disambiguation: `04 xxx xx xx` (9 digits total) is Liège landline; `04xx xx xx xx` (10 digits total) is mobile or premium. Liège landlines NEVER start with `046/047/048/049`. Pseudocode reference to `phone.py`.
5. **Prefix table.** Point to `references/prefixes.tsv`. Document the columns (prefix, length, kind, region_or_carrier, notes). Refresh quarterly from BIPT.
6. **Portability caveat.** Belgian number portability since 2002 means prefix → carrier is HISTORICAL ALLOCATION only. The `original_carrier` field reflects allocation, not the current operator. Never claim "this number IS on carrier X" — only "originally allocated to X".
7. **CLI.** `uv run be-leads-validate-phone "03 236 13 06"` prints the canonical JSON to stdout for ad-hoc dev / debugging.

**`references/prefixes.tsv`** — tab-separated, header `prefix\tlength\tkind\tregion_or_carrier\tnotes`. Exactly these rows (use the area-code data from wave-1 research; do not invent extras):

```
prefix	length	kind	region_or_carrier	notes
010	9	fixed_line	Wavre	
011	9	fixed_line	Hasselt	
012	9	fixed_line	Tongeren	
013	9	fixed_line	Diest	
014	9	fixed_line	Geel-Herentals-Turnhout	
015	9	fixed_line	Mechelen	
016	9	fixed_line	Leuven-Tienen	
019	9	fixed_line	Waremme	
02	9	fixed_line	Brussels	
03	9	fixed_line	Antwerp-Sint-Niklaas	
04	9	fixed_line	Liège-Voeren	does NOT use 046/047/048/049 sub-blocks
050	9	fixed_line	Bruges-Zeebrugge	
051	9	fixed_line	Roeselare	
052	9	fixed_line	Dendermonde	
053	9	fixed_line	Aalst	
054	9	fixed_line	Ninove	
055	9	fixed_line	Ronse	
056	9	fixed_line	Kortrijk-Mouscron	
057	9	fixed_line	Ypres	
058	9	fixed_line	Veurne	
059	9	fixed_line	Ostend-Bredene-Gistel	
060	9	fixed_line	Chimay	
061	9	fixed_line	Bastogne-Libramont	
063	9	fixed_line	Arlon	
064	9	fixed_line	La Louvière	
065	9	fixed_line	Mons-Casteau	
067	9	fixed_line	Nivelles-Soignies	
068	9	fixed_line	Ath	
069	9	fixed_line	Tournai	
071	9	fixed_line	Charleroi	
080	9	fixed_line	Stavelot	
081	9	fixed_line	Namur	
082	9	fixed_line	Dinant	
083	9	fixed_line	Ciney	
084	9	fixed_line	Marche-en-Famenne	
085	9	fixed_line	Huy	
086	9	fixed_line	Durbuy	
087	9	fixed_line	Verviers	
089	9	fixed_line	Genk	
09	9	fixed_line	Ghent	
0455	10	mobile	Orange	VOO brand
0456	10	mobile	Proximus	Mobile Viking brand
0460	10	mobile	Proximus	
0465	10	mobile	Lycamobile	
0466	10	mobile	Orange	Hey! brand
0467	10	mobile	Telenet	Liberty Global
0468	10	mobile	Telenet	Liberty Global
047	10	mobile	Proximus	047x range
048	10	mobile	BASE	Liberty Global, 048x range
049	10	mobile	Orange	049x range
070	9	shared_cost	—	€0.30/min national pay rate
077	10	m2m	—	machine-to-machine
078	9	shared_cost	—	national pay rate
0800	9	toll_free	—	€0.00/min freephone
0900	9	premium_rate	—	€0.50/min
0901	9	premium_rate	—	€0.50/call
0902	9	premium_rate	—	€1.00/min
0903	9	premium_rate	—	€1.50/min
0904	9	premium_rate	—	€2.00/min
0905	9	premium_rate	—	€2.00/call
0906	9	premium_rate	—	€1.00/min
0907	9	premium_rate	—	€2.00/min
0909	9	premium_rate	—	€31.00/call
```

Notes column: empty strings are permitted; the parser should tolerate them.

**`references/numbering-plan-rules.md`** — short reference doc (≤80 lines):
- Country code `+32`, trunk prefix `0`, total length 9 or 10 digits.
- Format examples: `02 xxx xx xx`, `0xx xx xx xx`, `04xx xx xx xx`.
- Liège disambiguation rule restated.
- Mobile sub-allocation: prefer the **longest matching prefix** in `prefixes.tsv`. `0467` matches before `046` would; `04675` doesn't exist as a prefix so the 4-char one wins.
- Special-service rule: `045x` premium sub-block exists (€1.00/min) but is administratively distinct from mobile `0455`/`0456` allocations — for now, classify all `04xx` 10-digit numbers as mobile unless explicitly listed in `prefixes.tsv` with `kind=premium_rate`. Document this as a known limitation.
- BIPT source: `https://www.bipt.be/operators/publication/database-with-reserved-and-allocated-numbers` — refresh `prefixes.tsv` quarterly.

**`scripts/validate.py`** — ≤40 lines, single-file CLI. Reads one phone string from argv or stdin, calls the Python API, prints the JSON dict. Used during dev.

### B. Python module: `src/scraper/lib/validators/`

Layout:
```
src/scraper/lib/validators/
├── __init__.py
└── phone.py
```

**`__init__.py`** — exports `validate_phone`, `PhoneValidation`, `PhoneType`, `InvalidPhoneError`.

**`phone.py`** — full implementation:

```python
class PhoneType(str, Enum):
    FIXED_LINE = "fixed_line"
    MOBILE = "mobile"
    PREMIUM_RATE = "premium_rate"
    TOLL_FREE = "toll_free"
    SHARED_COST = "shared_cost"
    M2M = "m2m"
    VOIP = "voip"
    UNKNOWN = "unknown"

class PhoneValidation(BaseModel):
    """Canonical phone observation value. Matches the provenance-schema
    contract: every field listed becomes a key in observations.value JSONB."""
    model_config = ConfigDict(frozen=True)
    e164: str                       # +32xxxxxxxxx
    raw: str                        # original input as given
    type: PhoneType
    region: str | None              # fixed_line area; None for mobile/premium
    original_carrier: str | None    # mobile only; None otherwise

class InvalidPhoneError(ScraperError): ...

def validate_phone(s: str, *, default_region: str = "BE") -> PhoneValidation:
    """Parse, classify, return PhoneValidation. Raises InvalidPhoneError on garbage."""
```

Behaviour spec:

1. **Empty / non-string → raise InvalidPhoneError**.
2. Strip the input: keep `+` and digits only for parsing, but keep `raw` as-given for the output.
3. **Parse with `phonenumbers`**. If parse fails or `is_valid_number()` is false → `InvalidPhoneError`.
4. **Normalize to E.164**: `phonenumbers.format_number(n, PhoneNumberFormat.E164)`.
5. **Classify**:
   - Strip `+32` and any leading `0` to get the national-significant-number digits.
   - Look up the **longest matching prefix** from `prefixes.tsv` (load once at module import, cache in module-level dict).
   - If matched: use the row's `kind` and `region_or_carrier`.
   - If no match: fall back to `phonenumbers.number_type()` mapping (FIXED_LINE → fixed_line, MOBILE → mobile, PREMIUM_RATE → premium_rate, TOLL_FREE → toll_free, SHARED_COST → shared_cost, VOIP → voip; otherwise unknown).
6. **Liège trap special case**: if first digit after `+32` is `4` and total NSN length is 8 (i.e. 9-digit number `04 xxx xx xx`), and the 2nd-3rd digits are NOT `55-99` (i.e. not a mobile sub-allocation), classify as `fixed_line, region=Liège-Voeren`. If 9 digits NSN (10-digit number `04xx xx xx xx`), classify per the longest-prefix mobile lookup.
7. `region` populated only for `fixed_line`; `original_carrier` populated only for `mobile`. The other type cells in the TSV (`—`) become `None`.
8. **`raw` field** preserves the original input string as passed in (don't strip whitespace).

Loading the TSV: read from a path resolved as `Path(__file__).parents[3] / ".claude" / "skills" / "belgian-phone-validation" / "references" / "prefixes.tsv"`. Cache the parsed mapping in a module-level dict so import is cheap. If the file is missing, raise a clear `RuntimeError` at import time — the validator is useless without it.

Type-hint everything. `mypy --strict` must pass.

### C. Tests

Layout:
```
tests/unit/lib/validators/
├── __init__.py
└── test_phone.py
```

Required cases (each gets its own test function):

1. **Bellock landline**: `"03 236 13 06"` → `e164="+3232361306"`, `type=fixed_line`, `region="Antwerp-Sint-Niklaas"`, `original_carrier=None`, `raw="03 236 13 06"`.
2. **Bellock landline normalized formats**: same expected output from `"+32 3 236 13 06"`, `"+3232361306"`, `"0032 3 236 13 06"`, `"03.236.13.06"`.
3. **Mobile Proximus**: `"0474 12 34 56"` → `type=mobile`, `region=None`, `original_carrier="Proximus"`.
4. **Mobile Telenet (0467)**: `"0467 12 34 56"` → `original_carrier="Telenet"`.
5. **Mobile Lycamobile (0465)**: `"0465 12 34 56"` → `original_carrier="Lycamobile"`.
6. **Liège landline**: `"04 220 11 22"` (9-digit) → `type=fixed_line`, `region="Liège-Voeren"`, NOT mobile.
7. **Liège-vs-mobile boundary**: `"0471 22 33 44"` (10-digit, starts with 04) → `type=mobile`, NOT fixed_line.
8. **Ghent**: `"09 234 56 78"` → `region="Ghent"`.
9. **Brussels**: `"02 555 12 12"` → `region="Brussels"`.
10. **Premium rate**: `"0902 12 34 56"` → `type=premium_rate`.
11. **Freephone**: `"0800 12 345"` → `type=toll_free`.
12. **M2M**: `"077 12 34 567"` (10 digits) → `type=m2m`.
13. **Invalid input — too short**: `"1234"` → `InvalidPhoneError`.
14. **Invalid input — letters**: `"03 abc def gh"` → `InvalidPhoneError`.
15. **Invalid input — empty**: `""` → `InvalidPhoneError`.
16. **Invalid input — None**: `None` → `InvalidPhoneError` (or TypeError; pick one and assert it).
17. **Pydantic model round-trip**: `validate_phone(...).model_dump()` matches the observation JSONB shape contract exactly (only the documented keys present).
18. **TSV-loader cache**: import the module twice (forcing module reload via `importlib.reload`), assert prefix dict is loaded each time and contents identical.
19. **CLI smoke**: subprocess `uv run be-leads-validate-phone "03 236 13 06"`, parse stdout as JSON, assert `e164 == "+3232361306"`.

Test 19 is integration-ish but doesn't hit the network or DB — keep it in `tests/unit/lib/validators/`, unmarked.

### D. CLI entry point

In `pyproject.toml`, under `[project.scripts]`, add:
```
be-leads-validate-phone = "scraper.lib.validators.phone:cli_main"
```

Implement `cli_main()` in `phone.py` — argparse parses `phone` positional + `--json` flag (default true). Prints `PhoneValidation.model_dump()` as JSON to stdout.

### E. Update CLAUDE.md

Under "## Per-source knowledge" add:
```
- Belgian phone validation rules: `.claude/skills/belgian-phone-validation/SKILL.md` (active)
```

### F. Update CHANGELOG

Under `[Unreleased]`:
```
### Added
- Skill: `belgian-phone-validation` with `references/prefixes.tsv` (BIPT-derived) and numbering-plan-rules.md.
- Module `src/scraper/lib/validators/phone.py` with `validate_phone()` returning the canonical `PhoneValidation` Pydantic model.
- CLI: `uv run be-leads-validate-phone "<number>"`.
```

### G. Update agent_docs/runbook.md

Append a section:
```
## Phone validation

Quick CLI test:
    uv run be-leads-validate-phone "03 236 13 06"

Refresh BIPT prefixes (quarterly):
    1. Download latest from https://www.bipt.be/operators/publication/database-with-reserved-and-allocated-numbers
    2. Update .claude/skills/belgian-phone-validation/references/prefixes.tsv preserving the column order
    3. Run: uv run pytest tests/unit/lib/validators/ -q
    4. Commit with message: "data: refresh BIPT prefix table (YYYY-MM)"
```

## Verification — run before stopping

```bash
uv sync --locked --dev
uv run pytest -q -m "not network and not slow and not integration"
uv run pytest --cov=src/scraper/lib/validators --cov-fail-under=95 -q tests/unit/lib/validators
uv run mypy src/scraper
uv run ruff check src/scraper tests
uv run ruff format --check src/scraper tests
uv run be-leads-validate-phone "03 236 13 06"          # must print JSON
uv run be-leads-validate-phone "0474 12 34 56"
uv run be-leads-validate-phone "04 220 11 22"          # the Liège trap
uv run be-leads-validate-phone "0467 12 34 56"
```

The four CLI calls each print one JSON line. Quick eyeball check: all four must show the expected `type` and `region`/`original_carrier`. If any look wrong, fix and re-test before stopping.

## Stop conditions

When all green:
1. Print one-line summary: number of new files, tests passing (separate count for the validator), coverage % on `src/scraper/lib/validators/phone.py`.
2. Print verbatim: `Ready for prompt 5 (skill: kbo-lookup + source: kbo_dump). Commit: git add . && git commit -m "skill: belgian-phone-validation (prompt 4)".`
3. End the turn. Do not start prompt 5.

## Things you must NOT do

- Do not implement phone-vs-city consistency checking. That's an enrichment-pipeline step that uses a *company address* to validate a *company phone* — out of scope here.
- Do not add a "current carrier" lookup (would require Numverify/Twilio paid API). `original_carrier` is allocation-only, by design.
- Do not modify any existing source modules (none exist yet anyway).
- Do not add database integration. The validator returns a Pydantic model; persistence is the source module's responsibility.
- Do not add new runtime deps. `phonenumbers`, `python-stdnum`, `pydantic` are already in the lockfile.
