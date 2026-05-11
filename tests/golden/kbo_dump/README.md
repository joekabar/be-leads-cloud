# KBO Dump Golden Fixtures

## synthetic_mini/

A hand-crafted 5-company ZIP fixture for unit and integration tests. It is NOT real KBO data.
Tests build the ZIP on the fly from these CSVs using `zipfile.ZipFile`.

### Fixture inventory

| File | Rows | Edge cases covered |
|------|------|--------------------|
| meta.csv | 5 | SnapshotDate, ExtractType=Full |
| enterprise.csv | 5 | legal person, natural person, modern 1xxx prefix, NULL juridical_form, recent StartDate |
| denomination.csv | 7 | types 001 (legal), 002 (abbreviation), 003 (commercial); NL and FR languages |
| address.csv | 6 | NL fields, FR-only fallback (Liège), NULL street (skip), REGO + CORR for same entity |
| contact.csv | 10 | Antwerpen landline, Liège landline, mobile, Ghent landline, INVALID phone (skip), email with whitespace |
| activity.csv | 8 | NaceVersion 2008 and 2025; MAIN, SECO, AUXI classifications |

### Expected observation output

From a Full ingest of this fixture, with no filters:
- `founding_date`: 5
- `status`: 5
- `name`: 7
- `address`: 5 (1 skipped — NULL street for 0200379531)
- `phone`: 4 (1 skipped — "123" fails validate_phone)
- `email`: 3
- `website`: 2
- `nace_code`: 8
- **Total: 39 observations, phones_invalid_skipped=1**

### KBO numbers used

| Number | Description |
|--------|-------------|
| 0439401387 | Bellock-equivalent; legal person, Antwerpen |
| 0123456749 | Natural person (TypeOfEnterprise=2) |
| 1000000021 | Modern 1xxx prefix allocation |
| 0200379531 | No juridical form; NULL street (address obs skipped) |
| 0800000075 | Recent StartDate (2023); Ghent |
