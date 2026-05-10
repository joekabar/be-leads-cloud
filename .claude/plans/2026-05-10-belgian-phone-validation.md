# Plan: Ship the belgian-phone-validation skill and phone.py module
Date: 2026-05-10
Author: Claude
Status: approved

## Goal
Deliver a self-contained Belgian phone number validator that converts any reasonable Belgian
phone string to the canonical `{e164, raw, type, region, original_carrier}` JSONB shape used
in `observations.value`. The validator is used by every future source that touches phone data
(kbo_dump, kbopub, goudengids, website). No DB or network calls — pure data transform.

## Scope (in)
- `.claude/skills/belgian-phone-validation/SKILL.md` + references + CLI script
- `src/scraper/lib/validators/__init__.py` and `phone.py`
- `tests/unit/lib/validators/test_phone.py` (19 test functions)
- `pyproject.toml`: add `be-leads-validate-phone` script entry point
- `CLAUDE.md`: add skill reference under Per-source knowledge
- `CHANGELOG.md`: add Unreleased entries
- `agent_docs/runbook.md`: add Phone validation section

## Out of scope
- Phone-vs-city consistency checking (enrichment pipeline step)
- Current-carrier lookup (would require paid API; original_carrier is allocation-only)
- Any existing source modules
- Database integration (validator returns Pydantic model only)
- New runtime dependencies (phonenumbers, pydantic already in lockfile)

## Files to be created or modified
- NEW: `.claude/skills/belgian-phone-validation/SKILL.md`
- NEW: `.claude/skills/belgian-phone-validation/references/prefixes.tsv`
- NEW: `.claude/skills/belgian-phone-validation/references/numbering-plan-rules.md`
- NEW: `.claude/skills/belgian-phone-validation/scripts/validate.py`
- NEW: `src/scraper/lib/validators/__init__.py`
- NEW: `src/scraper/lib/validators/phone.py`
- NEW: `tests/unit/lib/validators/__init__.py`
- NEW: `tests/unit/lib/validators/test_phone.py`
- MOD: `pyproject.toml`
- MOD: `CLAUDE.md`
- MOD: `CHANGELOG.md`
- MOD: `agent_docs/runbook.md`

## Tests required (red first)
- 4 format-variant tests for same Antwerp number
- Liège trap: 04 220 11 22 → fixed_line (NOT mobile)
- Mobile boundary: 0471 22 33 44 → mobile (NOT fixed_line)
- Per-carrier: Proximus (047x), Telenet (0467), Lycamobile (0465)
- City checks: Brussels, Ghent
- Special services: premium_rate, toll_free, m2m
- Invalid inputs: short, letters, empty, None
- Pydantic model round-trip: only 5 documented keys
- TSV reload cache: contents stable after importlib.reload
- CLI smoke: subprocess call parses JSON, e164 correct

## Acceptance criteria
- [ ] Skill loads on phone-related prompts
- [ ] `uv run be-leads-validate-phone "03 236 13 06"` prints canonical JSON
- [ ] Python API returns PhoneValidation matching observation JSONB shape
- [ ] `mypy --strict` clean on `src/scraper`
- [ ] `uv run pytest --cov=src/scraper/lib/validators --cov-fail-under=95 tests/unit/lib/validators` passes
- [ ] All 4 CLI verification calls print correct type/region/original_carrier

## Risks
- phonenumbers library stubs may be incomplete → add mypy override if needed
- Belgian 090x premium format length ambiguity (TSV says 9, test case is 10 digits) → let
  phonenumbers determine validity; adjust test if rejected

## Rollback plan
- Delete `src/scraper/lib/validators/` and `tests/unit/lib/validators/`
- Revert pyproject.toml script entry, CLAUDE.md, CHANGELOG.md, runbook.md
