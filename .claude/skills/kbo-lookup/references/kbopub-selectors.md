# kbopub HTML Selectors

Reference for `src/scraper/sources/kbopub_html/parser.py`.
Last updated: 2026-05-11 (prompt 6).

## Detail page URL

```
https://kbopub.economie.fgov.be/kbopub/toonondernemingps.html?lang={nl|fr}&ondernemingsnummer={10-digit-kbo}
```

Example: `https://kbopub.economie.fgov.be/kbopub/toonondernemingps.html?lang=nl&ondernemingsnummer=0439401387`

## Page language detection

| Marker | Language |
|--------|----------|
| `lang="fr"` attribute on `<html>` | French |
| `"Données de l"` in page text | French |
| `"Fonctions"` in page text | French |
| Otherwise | Dutch |

## Page structure (high level)

The detail page is a single large `<table>`. Sections are delimited by header rows:

```html
<tr>
  <td class="I" colspan="4"><h2>Section Title</h2></td>
</tr>
```

The parser walks `<tr>` siblings after the Functies/Fonctions header, stopping at the next `<td class="I">` header or `</table>`.

## Functies / Fonctions section

### Section header row

```html
<!-- NL -->
<tr><td class="I" colspan="4"><h2>Functies</h2></td></tr>

<!-- FR -->
<tr><td class="I" colspan="4"><h2>Fonctions</h2></td></tr>
```

**Detection**: `soup.find_all("h2")` filtered to `tag.get_text(strip=True) in ("Functies", "Fonctions")`.
Walk up to `h2.find_parent("tr")` to get the section header `<tr>`.

### Function holder data rows

```html
<tr>
  <td class="QL">Bestuurder</td>           <!-- tds[0]: role label -->
  <td class="QL">Boonen, Jan</td>          <!-- tds[1]: holder name -->
  <td class="QL">
    <span class="upd">Sinds 27 maart 2024</span>  <!-- tds[2]: since date (optional) -->
  </td>
</tr>
```

**Termination**: Stop when a sibling `<tr>` contains `<td class="I">` (next section) or when siblings run out.

**Skip rows**: rows with fewer than 2 `<td>` elements, or where `tds[0].get_text(strip=True)` is empty.

## Role label mapping

### Dutch (NL)

| Raw label | Canonical slug |
|-----------|---------------|
| Bestuurder | director |
| Gedelegeerd bestuurder | managing_director |
| Zaakvoerder | manager |
| Vaste vertegenwoordiger | permanent_representative |
| Voorzitter | chairman |
| Ondervoorzitter | vice_chairman |
| Algemeen directeur | general_director |
| CEO | ceo |
| CFO | cfo |
| COO | coo |
| Vereffenaar | liquidator |
| Commissaris | auditor |

### French (FR)

| Raw label | Canonical slug |
|-----------|---------------|
| Administrateur | director |
| Administrateur délégué | managing_director |
| Gérant | manager |
| Représentant permanent | permanent_representative |
| Président | chairman |
| Vice-président | vice_chairman |
| Directeur général | general_director |
| Liquidateur | liquidator |
| Commissaire | auditor |

Unknown role labels are kept verbatim in both `role` and `role_canonical` fields, with a `structlog` warning.

## Date parsing

Date strings appear inside `<span class="upd">` in `tds[2]`.

**NL format**: `Sinds DD maand YYYY` — e.g. `Sinds 27 maart 2024`
**FR format**: `Depuis DD mois YYYY` — e.g. `Depuis 10 février 2019`

Prefixes stripped: `"sinds "`, `"depuis "` (case-insensitive after `.lower()`).
After stripping, split on whitespace into 3 parts: `[day_str, month_name, year_str]`.
Month names: NL + FR merged dict (no collisions). Returns `datetime.date` or `None` on failure.

## Legal person / linked KBO detection

Hierarchy of checks on the name field (`tds[1]`):

1. **Regex match**: `(?:met KBO|avec BCE)\s+([\d.]+)` or bare 10-digit number `(?<!\d)(\d{10})(?!\d)` → `is_legal_person=True`, `linked_kbo=<10 digits>` (or `None` if digits ≠ 10).
2. **Suffix match**: Last word (uppercased) in `frozenset({"BV", "NV", "SRL", "SA", "BVBA", "SPRL", "CVBA", "SCRL", "VZW", "ASBL"})` → `is_legal_person=True`, `linked_kbo=None`.
3. Otherwise: `is_legal_person=False`, `linked_kbo=None`.

## HTTP response codes

| Status | Meaning | Action |
|--------|---------|--------|
| 200 | OK | Parse response |
| 404 | KBO not found / deregistered | Raise `KboNotFoundError` (counted, batch continues) |
| 403 | WAF / Imperva block | Raise `BlockedError` (batch aborts, no retry) |
| 429 / 503 / 504 | Rate limit / server error | `RetryableError` → exponential backoff (handled by `get_polite_client`) |

## Not-found detection

A 200 response with an empty `<table></table>` inside `<h1>Gegevens van de geregistreerde entiteit</h1>` indicates an unknown/deregistered KBO — the parser returns an empty list (0 function holders), not a `KboNotFoundError`. The ingester counts this as `kbos_processed=1`, `function_holders_total=0`.

## Imperva challenge (future)

Not currently encountered in testing. If kbopub deploys Imperva, signs include:
- HTTP 403 with body containing `"Incapsula"` or `"_Incapsula_Resource_"`
- Redirect to `/_Incapsula_Resource_?...`

Mitigation: Playwright warm-up (see goudengids runbook section — coming in a future prompt). Until then, `BlockedError` aborts the batch.

## Golden fixtures

| Fixture file | KBO (valid checksum) | Description |
|---|---|---|
| `0439401387_bellock_nl.html` | 0439401387 | NL, 1 holder (Boonen Jan / Bestuurder) |
| `0123456749_no_holders.html` | 0123456749 | No Functies section (0 holders) |
| `0234567890_multiple_roles.html` | mapped as 0234567873 | 3 holders: director, managing_director, auditor (legal person) |
| `0345678901_french.html` | mapped as 0345678997 | FR page, 2 holders |
| `0456789012_legal_person_holder.html` | mapped as 0456789034 | Legal person with embedded linked KBO |
