# KBO Open Data — CSV Schema Reference

## File characteristics

All CSVs in the KBO Open Data ZIP share the same dialect:
- **Delimiter**: comma (`,`)
- **Text qualifier**: double quote (`"`)
- **Decimal separator**: dot (`.`)
- **Date format**: `dd-mm-yyyy` (Belgian format — note day-first!)
- **NULL representation**: empty string between adjacent commas (e.g. `,,`)
- **Encoding**: UTF-8

## meta.csv

Key/value pairs describing the extract. No header row — two columns: `Variable`, `Value`.

| Variable | Example | Notes |
|----------|---------|-------|
| SnapshotDate | `15-04-2026` | Date the snapshot was taken (dd-mm-yyyy) |
| ExtractTimestamp | `2026-04-15T03:00:00` | When the file was generated |
| ExtractType | `Full` | `Full` or `Update` |
| ExtractNumber | `42` | Sequential counter |
| Version | `R018.00` | Schema version |

## code.csv

Master dictionary for all code values used in other tables.

| Column | Type | Notes |
|--------|------|-------|
| Category | TEXT | Code category (e.g. `JuridicalForm`, `Status`, `TypeOfAddress`) |
| Code | TEXT | The code value (e.g. `014`, `AC`) |
| Language | TEXT | `DE`, `EN`, `FR`, or `NL` |
| Description | TEXT | Human-readable description in that language |

**Note**: In Update ZIPs, code.csv is always included as a full snapshot (not differential).

## enterprise.csv

One row per enterprise (legal entity or natural person registered in KBO).

| Column | Type | Notes |
|--------|------|-------|
| EnterpriseNumber | TEXT | 10-digit KBO number (no dots). PK. |
| Status | TEXT | Always `AC` (active) in this snapshot — deleted companies are not included |
| JuridicalSituation | TEXT | Code from code.csv Category=JuridicalSituation (e.g. `000` = normal) |
| TypeOfEnterprise | TEXT | `1` = legal person, `2` = natural person |
| JuridicalForm | TEXT | Code from code.csv Category=JuridicalForm (e.g. `014` = NV/SA). May be NULL. |
| JuridicalFormCAC | TEXT | CAC-specific juridical form code. May be NULL. |
| StartDate | TEXT | Date of registration (dd-mm-yyyy). May be NULL for very old records. |

**Update ZIP**: `enterprise_delete.csv` + `enterprise_insert.csv` instead of `enterprise.csv`.
Apply deletes first, then inserts.

## establishment.csv

One row per establishment (vestigingseenheid / unité d'établissement).
An enterprise may have multiple establishments.

| Column | Type | Notes |
|--------|------|-------|
| EstablishmentNumber | TEXT | 10-digit establishment number. PK. |
| StartDate | TEXT | Date of registration (dd-mm-yyyy) |
| EnterpriseNumber | TEXT | FK → enterprise.csv.EnterpriseNumber |

## denomination.csv

Names of enterprises and establishments in multiple languages.

| Column | Type | Notes |
|--------|------|-------|
| EntityNumber | TEXT | FK → enterprise.csv or establishment.csv |
| Language | TEXT | `NL`, `FR`, `DE`, `EN`, or `--` (language-neutral) |
| TypeOfDenomination | TEXT | `001` = legal name, `002` = abbreviation, `003` = commercial name |
| Denomination | TEXT | The actual name |

**Gotcha**: An entity may have multiple denominations of the same type in different languages.
The same legal name may appear twice — once in NL, once in FR. Prefer NL; fall back to FR.

## address.csv

Addresses for enterprises and establishments. An entity may have multiple address types.

| Column | Type | Notes |
|--------|------|-------|
| EntityNumber | TEXT | FK → enterprise or establishment |
| TypeOfAddress | TEXT | Code from code.csv Category=TypeOfAddress (e.g. `REGO` = registered office) |
| CountryNL | TEXT | Country name in Dutch. Usually `België`. |
| CountryFR | TEXT | Country name in French. Usually `Belgique`. |
| Zipcode | TEXT | Belgian postal code (4 digits). May be NULL for foreign addresses. |
| MunicipalityNL | TEXT | Municipality name in Dutch. May be NULL (FR-only municipalities). |
| MunicipalityFR | TEXT | Municipality name in French. May be NULL (NL-only municipalities). |
| StreetNL | TEXT | Street name in Dutch. May be NULL. |
| StreetFR | TEXT | Street name in French. May be NULL. |
| HouseNumber | TEXT | House number (string — can be alphanumeric). May be NULL. |
| Box | TEXT | Box/apartment number. May be NULL. |
| ExtraAddressInfo | TEXT | Free-form extra info. Usually NULL. |
| DateStrikingOff | TEXT | Date address was struck off (dd-mm-yyyy). NULL = still active. |

**Strategy**: prefer NL fields; fall back to FR. Skip if no street in either language.

## contact.csv

Contact details for enterprises and establishments.

| Column | Type | Notes |
|--------|------|-------|
| EntityNumber | TEXT | FK → enterprise or establishment |
| EntityContact | TEXT | 3-char code (can be ignored in most use cases) |
| ContactType | TEXT | `TEL` = telephone, `EMAIL` = email, `WEB` = website |
| Value | TEXT | The contact value (phone string, email address, URL) |

**Phone handling**: run `validate_phone()` from `src/scraper/lib/validators/phone.py`.
Skip on `InvalidPhoneError` — log a warning, increment skip counter.

## activity.csv

NACE economic activity classifications.

| Column | Type | Notes |
|--------|------|-------|
| EntityNumber | TEXT | FK → enterprise or establishment |
| ActivityGroup | TEXT | `MAIN` or group code |
| NaceVersion | TEXT | `2003`, `2008`, or `2025` |
| NaceCode | TEXT | NACE code string (e.g. `43.211`) |
| Classification | TEXT | `MAIN` = main activity, `SECO` = secondary, `AUXI` = auxiliary |

**Note**: An entity may have multiple NACE codes across versions. The transformer produces one
observation per row; deduplication by confidence/recency is handled by the companies_current
materialised view.

## branch.csv

Branches (not the same as establishments).

| Column | Type | Notes |
|--------|------|-------|
| Id | TEXT | Branch identifier. PK. |
| StartDate | TEXT | Registration date (dd-mm-yyyy) |
| EnterpriseNumber | TEXT | FK → enterprise.csv |

## Update ZIP mechanics

Update ZIPs follow a differential format. For each table:
- `<table>_delete.csv` — rows to be logically removed (apply first)
- `<table>_insert.csv` — rows to be added (apply after deletes)

**Exception**: `code.csv` is always a full snapshot in Update ZIPs (no differential).

**Ingestion strategy** (append-only, never physical delete):
1. For each row in `enterprise_delete.csv`: write one `status=deleted` observation.
2. For each row in `<table>_insert.csv`: process normally as insert.

## What is NOT in the dump

- **Function holders / mandataires / bestuurders**: only available on the kbopub HTML detail
  page. See `.claude/skills/kbo-lookup/SKILL.md §6` and `references/kbopub-selectors.md`.
- **Financial data**: only from NBB CBSO Authentic Data (prompt N+2).
- **Personal contact data**: out of scope for this iteration (per CLAUDE.md).
