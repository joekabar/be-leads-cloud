---
name: goudengids-listing
description: Scrape sector × city listing pages on goudengids.be (NL) and pagesdor.be (FR) for company discovery. Host is behind Imperva Cloud WAF (cookie tier, not reese84 — verified). Pattern is two-phase: warm up cookies via Playwright headless Chromium against the homepage, then transfer cookies to httpx for paginated listing fetches at 0.3 rps. Each result card yields name, phone, address, optional email/website, optional KBO. Use whenever the user mentions goudengids, pagesdor, golden pages, gouden gids, listing page, company directory, sector search, or "find me companies in <city>".
allowed-tools: Read, Edit, Bash, WebFetch(domain:goudengids.be), WebFetch(domain:pagesdor.be), Bash(uv run python:*), Bash(uv run pytest:*), Bash(uv run be-leads-discover-goudengids:*), mcp__playwright__*
---

## 1. When to use

Use for **discovery** (finding new companies not yet in KBO Open Data) and **contact enrichment**
(extra phones, websites). NOT for canonical company facts — KBO Open Data wins for those.

The source value for observations is always `"goudengids"` (NL) or `"pagesdor"` (FR).
See `references/selectors.md` for CSS selectors and `references/imperva-bypass.md` for the
Playwright warmup recipe.

## 2. URL structure

**NL (goudengids.be):**
`https://www.goudengids.be/zoeken/{sector_slug}/{city_slug}/{page}/`

**FR (pagesdor.be):**
`https://www.pagesdor.be/recherche/{sector_slug_fr}/{city_slug}/{page}/`

Both slugs are lowercase and hyphenated. Examples:
- `/zoeken/elektriciens/antwerpen/1/`
- `/zoeken/loodgieters/sint-niklaas/2/`
- `/recherche/electriciens/liege/1/`

City slug rules: lowercase, trim whitespace, replace internal spaces with hyphens.
"Sint-Niklaas" → "sint-niklaas"; "Brussel Stad" → "brussel-stad".

## 3. Imperva pattern

See `references/imperva-bypass.md` for the full recipe. Summary:

1. **Warm-up (~3s):** render homepage with Playwright headless Chromium, harvest cookies
   matching `^(incap_ses_|visid_incap_|nlbi_|reese84)`.
2. **Transfer:** inject cookies into httpx session via `cookies=warmup_result.cookies`.
3. **Fetch:** use httpx + PoliteClient for all paginated listing requests.
4. **Re-warm:** at 25 minutes OR on first 403 (whichever comes first). Never cache cookies
   across process restarts.

## 4. Listing card structure

Each result is a `<li data-small-result='...(JSON)...'>` element. The JSON blob contains the
primary fields; additional phones and address details are in child elements. Full selectors
in `references/selectors.md`.

KBO number is NOT reliably present on listing cards. Leave `kbo_number` as a synthetic
placeholder (see Section 9). The consolidation pass (prompt 11) reconciles placeholders.

## 5. Pagination

Path-based: `/1/`, `/2/`, … Maximum ~25 pages per sector/city pair.

**Stop conditions:**
- `is_empty_results_page(html)` returns True ("geen resultaten" banner)
- Page returns 0 `<li data-small-result>` elements

## 6. Sector slugs

`references/sectors.toml` contains the canonical NL→FR mapping. Do NOT invent slugs.
Pass `--sector` value is validated against the toml at CLI startup.

## 7. Rate limits

- 0.3 rps, concurrency 1 (configured in polite-scraping `references/per-host.toml`)
- **NEVER** issue concurrent goudengids requests — the WAF penalises bursts harder than
  sustained low rates.
- One warm-up per process restart + every 25 minutes.

## 8. What NOT to scrape from goudengids

Do not attempt to scrape these from goudengids — use the authoritative source instead:

| Field | Authority |
|---|---|
| KBO / enterprise number | `kbo_dump` / `kbopub` |
| Founding date | `kbo_dump` |
| NACE code | `kbo_dump` |
| Employees, revenue | `nbb_authentic` |
| Function holders | `kbopub` |

## 9. Synthetic placeholder KBOs

Because goudengids listing pages don't include KBO numbers, observations use synthetic
placeholder KBOs:

```
f"9{sha256(f'{name.lower()}|{postal_code or ""}').digest_as_int() % 10**9:09d}"
```

Real KBOs start with `0` or `1`; placeholders start with `9` and deliberately fail the
mod-97 checksum. See `.claude/skills/provenance-schema/SKILL.md` §9 for the full spec.

## 10. Confidence priors (from provenance-schema `references/confidence.md`)

| Field | Confidence |
|---|---|
| name | 0.85 |
| phone | 0.85 |
| website | 0.85 |
| address | 0.80 |
| email | 0.80 |
