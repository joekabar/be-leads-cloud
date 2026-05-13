---
name: provenance-schema
description: Apply the project's append-only multi-source provenance schema. Every field value carries source, observed_at, confidence, raw_value, and run_id; canonical fact rows are NEVER UPDATEd — new values become new observations. Use whenever the user adds a data field, modifies the data model, writes an UPDATE statement, joins tables, or computes a "current best" value. Always use this skill instead of writing UPDATE statements on companies or observations — there must never be UPDATEs on canonical fact rows.
allowed-tools: Read, Edit, Bash(uv run python:*), Bash(uv run pytest:*), Bash(psql:*), mcp__postgres__query, mcp__postgres__list_tables, mcp__postgres__describe_table
---

## 1. Cardinal rule

No `UPDATE` on `observations` or `companies_current`. Only `INSERT` into `observations`.
The `companies_current` materialised view is rebuilt by `src/scraper/pipeline/consolidate.py`
(added in a later prompt) — it is read-only at the application level. If you find yourself
writing `UPDATE` on either, stop and write an `INSERT` into `observations` instead.
`ObservationsRepo` intentionally exposes no `update` or `delete` method.

## 2. Schema sketch

Full DDL lives in `references/schema.sql`. Four tables:
- `schema_version` — migration version tracking
- `run_log` — pipeline run audit (start/end, counts)
- `observations` — append-only fact store (BIGSERIAL PK, JSONB value, confidence NUMERIC(3,2))
- `jobs` — worker queue (`SELECT ... FOR UPDATE SKIP LOCKED`)

Materialised view `companies_current` is defined in `references/current-view.sql`.

## 3. Current-best read pattern

For bulk reads, query the materialised view: `SELECT * FROM companies_current WHERE kbo_number = $1`.
For real-time / ad-hoc (no refresh needed), use the `LATERAL` pattern in `references/current-view.sql`.
Use `ObservationsRepo.current_best(kbo_number, field)` from Python — it uses the LATERAL query.
Never `REFRESH MATERIALIZED VIEW` inside a repository method; that belongs in `pipeline/consolidate.py`.

## 4. Confidence scoring

Per-source priors are in `references/confidence.md`. Two adjustments applied after the prior:
- **Recency decay:** `confidence * (0.99 ** days_since_observation)` clamped to `[0.30, 1.00]`
- **Consensus boost:** `min(1.0, base * 1.1)` per matching observation from a *different* source
  for the same `(kbo_number, field, value)`

Apply these in `src/scraper/scoring/` (added in a later prompt), not in the repository layer.

## 5. What "field" means

Allowed values defined in `src/scraper/db/fields.py`. Static fields:
`phone | email | website | address | name | founding_date | nace_code | function_holder |
activity_summary | website_age | postal_code | status`

Financial fields follow pattern `{revenue|profit|employees}_{YYYY}` (four-digit year ≥ 1900).
New fields require a constant added to `src/scraper/db/fields.py` and a `validate_field` update.
`cross_validation` is a search-engine summary field emitted by the `ddg_brave` source.

## 6. Source taxonomy

Allowed values defined in `src/scraper/db/sources.py`:
`kbo_dump | kbopub | nbb_authentic | goudengids | pagesdor | website | ddg | brave | wayback | manual`
New sources require a constant added to `src/scraper/db/sources.py`.

## 7. JSONB value shape

Each field has a canonical shape. Examples:
```json
phone:          {"e164": "+3232361306", "raw": "03 236 13 06", "type": "fixed_line", "region": "Antwerp"}
email:          {"address": "info@bellock.be", "is_role_account": true}
website:        {"url": "https://bellock.be", "tld": "be"}
address:        {"street": "Lange Van Bloerstraat 116", "postal_code": "2060", "city": "Antwerpen", "country": "BE"}
name:           {"text": "Bellock", "lang": "nl"}
founding_date:  {"iso": "1989-12-28"}
nace_code:      {"code": "43.211", "version": "2008"}
function_holder:{"name": "Boonen, Jan", "role": "bestuurder", "since": "2024-03-27"}
revenue_2023:   {"value": 30326, "currency": "EUR", "filing_ref": "2024-00000148"}
cross_validation: {
    "query": "\"Bellock\" Antwerpen",
    "engine": "brave",
    "total_results": 8,
    "official_websites_count": 1,
    "directory_hits_count": 3,
    "social_links_count": 2,
    "news_mentions": 0,
    "first_official_website": "https://bellock.be",
    "snapshot_at": "2026-05-12T15:30:00+00:00"
  }
```

## 9. Synthetic placeholder KBOs

Sources without authoritative KBO numbers (goudengids listing pages, search engines)
emit observations under a synthetic placeholder KBO formed as:

```python
import hashlib
key = f"{name.lower().strip()}|{(postal_code or '').strip()}".encode("utf-8")
h = int(hashlib.sha256(key).hexdigest(), 16)
placeholder = f"9{h % 10**9:09d}"
```

Properties:
- Always 10 digits starting with `9` — real KBOs start with `0` or `1`
- Deliberately fails the mod-97 checksum, so it cannot collide with a real KBO
- Deterministic: same `(name, postal_code)` → same placeholder across runs
- The `Observation._validate_kbo` validator accepts these (bypasses stdnum check)

The consolidation pass (`src/scraper/pipeline/consolidate.py`, prompt 11) maps placeholders
to real KBOs by `(name, postal_code, city)` fuzzy match. Until consolidation, placeholder
observations remain queryable but live in a "candidate" tier (filter with
`kbo_number LIKE '9%'` or `kbo_number NOT LIKE '0%' AND kbo_number NOT LIKE '1%'`).

## 8. Append-only enforcement

`scripts/verify_no_updates.sh` greps `src/` for `UPDATE observations` and
`UPDATE companies_current` (case-insensitive). It exits 2 if found.
Add it to `.pre-commit-config.yaml` in a later step.
`test_no_updates_guard.py` asserts exit 0 on a clean tree and exit 2 after injecting a temp file.
