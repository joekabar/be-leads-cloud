---
name: kbo-lookup
description: Interact with the Belgian KBO/CBE registry. Covers the FREE daily KBO Open Data ZIP (bulk canonical company facts; download from kbopub.economie.fgov.be/kbo-open-data) and the kbopub HTML public-search detail page (the only place function holders / mandataires / bestuurders live). Validates 10-digit enterprise numbers via stdnum.be.vat (mod-97 checksum); supports both legacy 0xxx and modern 1xxx prefixes. Use whenever the user mentions KBO, CBE, BCE, BTW, ondernemingsnummer, numéro d'entreprise, kbopub, KBO Open Data, mandataires, bestuurders, or anything that looks like a 10-digit Belgian company number.
allowed-tools: Read, Edit, Bash, WebFetch(domain:kbopub.economie.fgov.be), WebFetch(domain:economie.fgov.be), Bash(uv run python:*), Bash(uv run pytest:*), Bash(uv run be-leads-ingest-kbo:*), Bash(uv run be-leads-validate-kbo:*)
---

## 1. When to use

Consult this skill whenever you:
- Parse, validate, store, or look up a KBO number (10-digit Belgian enterprise number)
- Ingest data from the KBO Open Data ZIP (Full or Update)
- Scrape a kbopub detail page (prompt 6 — implementation deferred, see §6)
- Encounter strings that look like `0439.401.387`, `BE0439401387`, or bare 10-digit numbers
- Process enterprise.csv, denomination.csv, address.csv, contact.csv, or activity.csv rows

## 2. Two paths, two purposes

### Path A — KBO Open Data ZIP (free, daily)

The authoritative **bulk** source. A ZIP downloaded from the portal contains CSV files covering
all active Belgian enterprises. Updated daily. Requires free email registration.

- **File**: `KboOpenData_<n>_<YYYY>_<MM>_Full.zip` (full) or `KboOpenData_<n>_<YYYY>_<MM>_Update.zip`
- **Source name**: `kbo_dump`
- **Ingest command**: `uv run be-leads-ingest-kbo --zip <path.zip>`
- **Schema**: see `references/open-data-schema.md`

### Path B — kbopub HTML public search (per-company, rate-limited)

The **only** source for function holders / mandataires / bestuurders. The Open Data dump does
NOT contain this information. Scraping is reserved for per-company enrichment lookups (prompt 6).

- **URL pattern**: `https://kbopub.economie.fgov.be/kbopub/zoeknummerform.html?nummer=<kbo>`
- **Source name**: `kbopub`
- **Selectors**: see `references/kbopub-selectors.md` (placeholder — populated in prompt 6)
- **Rate**: 0.25 req/s, concurrency 1 (see polite-scraping skill per-host.toml)

## 3. KBO number validation

**Always** use `stdnum.be.vat`. Never roll your own checksum.

```python
from stdnum.be import vat

vat.is_valid("0439401387")   # True
vat.compact("0439.401.387")  # "0439401387"
vat.validate("BE0439401387") # "0439401387"  (strips BE prefix)
```

- Modern numbers may start with **1** as well as **0** (expanded BIPT allocation).
- Canonical format: 10 digits, no dots, no spaces, no "BE" prefix.
- Algorithm summary: see `references/checksum.md`.

## 4. Open Data schema

Full column-by-column documentation: `references/open-data-schema.md`.

Quick reference:
| CSV | Key columns |
|-----|-------------|
| meta.csv | Variable, Value — SnapshotDate, ExtractType (Full\|Update), ExtractNumber |
| enterprise.csv | EnterpriseNumber, Status, TypeOfEnterprise, JuridicalForm, StartDate |
| denomination.csv | EntityNumber, Language, TypeOfDenomination (001=legal,002=abbrev,003=commercial), Denomination |
| address.csv | EntityNumber, TypeOfAddress, Zipcode, MunicipalityNL/FR, StreetNL/FR, HouseNumber |
| contact.csv | EntityNumber, ContactType (TEL\|EMAIL\|WEB), Value |
| activity.csv | EntityNumber, NaceVersion (2003\|2008\|2025), NaceCode, Classification (MAIN\|SECO\|AUXI) |

## 5. Field → observation mapping

| Source row | Field | Confidence | JSONB shape |
|------------|-------|------------|-------------|
| denomination.csv TypeOfDenomination=001 | `name` | 1.00 | `{"text": "...", "lang": "nl"}` |
| denomination.csv TypeOfDenomination=002 | `name` | 0.90 | `{"text": "...", "lang": "nl", "type": "abbreviation"}` |
| denomination.csv TypeOfDenomination=003 | `name` | 0.95 | `{"text": "...", "lang": "nl", "type": "commercial"}` |
| enterprise.csv StartDate | `founding_date` | 1.00 | `{"iso": "1989-12-28"}` |
| enterprise.csv Status | `status` | 1.00 | `{"value": "active"}` |
| address.csv | `address` | 0.95 | `{"street": "...", "postal_code": "...", "city": "...", "country": "BE"}` |
| contact.csv TEL | `phone` | 0.95 | `{"e164": "...", "raw": "...", "type": "...", "region": ...}` |
| contact.csv EMAIL | `email` | 0.85 | `{"address": "...", "is_role_account": false}` |
| contact.csv WEB | `website` | 0.85 | `{"url": "...", "tld": "be"}` |
| activity.csv | `nace_code` | 0.95 | `{"code": "...", "version": "2008"}` |

## 6. kbopub anti-block notes (prompt 6 preview)

The kbopub portal is behind Imperva/Incapsula. Planned approach:
1. Playwright-based cookie warm-up (see polite-scraping skill §Escalate-to-Playwright triggers)
2. Inject session cookie into httpx requests for subsequent lookups
3. Rate: 0.25 req/s, concurrency 1 (per per-host.toml)
4. Selectors: `references/kbopub-selectors.md` (populated in prompt 6)

## 7. CLI commands

```bash
# Quick checksum validation
uv run be-leads-validate-kbo "0439.401.387"   # → "valid"
uv run be-leads-validate-kbo "BE0439401387"   # → "valid"
uv run be-leads-validate-kbo "123"            # → "invalid", exit 2

# Ingest a Full or Update ZIP
uv run be-leads-ingest-kbo --zip data/kbo_dump/KboOpenData_42_2026_04_Full.zip
uv run be-leads-ingest-kbo --zip data/kbo_dump/KboOpenData_43_2026_04_Update.zip --no-refresh
uv run be-leads-ingest-kbo --zip data/kbo_dump/KboOpenData_42_2026_04_Full.zip \
    --database-url postgresql://leads:leads@localhost:5432/leads
```
