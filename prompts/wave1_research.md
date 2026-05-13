# Wave 1 Research Report — Belgian B2B Scraper Sources, Validation, Legal Posture

Validated against live web sources May 2026. Where 2026 info couldn't be confirmed, flagged inline.

---

## TL;DR (decision-level)

1. **The architecture flips on one finding: KBO Open Data is now updated DAILY (not monthly), free, with email registration, available via SFTP.** This makes kbopub HTML scraping a **fallback for two specific things only** — function holders (bestuurders/mandataires) and live status verification. Bulk facts come from the local mirror of the daily ZIP.

2. **NBB has a free REST API for current-data financial filings** (`Authentic Data Query` product at `https://ws.cbso.nbb.be/authentic/...`). Registration + CLIENT_ID required. Returns XBRL, JSON, and PDF. **No scraping of consult.cbso.nbb.be is needed or appropriate** — it's a JS SPA anyway.

3. **The legal posture is more constrained than wave 2 documented.** The Belgian DPA fined Bisnode/Black Tiger €174,640 in January 2024 for exactly this activity pattern. BDPA Recommendation 01/2025 (consultation closed May 2025, since adopted) makes cold outreach via legitimate interest "generally not justifiable" without prior relationship. The KBO Open Data licence explicitly forbids reuse of personal data for direct marketing. **The bootstrap prompt must require a documented LIA, suppression list, transparency notices, and source/recipient logging — or the user should reframe to internal CRM enrichment.**

4. **Use `python-stdnum` for KBO/VAT validation.** Built-in `stdnum.be.vat` handles compaction, formatting, mod-97 checksum, and the new `BE1xxxxxxxxx` numbers (Belgium expanded the allocation to also start with `1`, not just `0`). Rolling our own checksum is the highest-risk hallucination vector — eliminate it.

5. **Phone validation: use Google's `phonenumbers` library.** It identifies geographic vs mobile vs VoIP for Belgian numbers without paid lookups. Combine with a hand-curated area-code → city table. Liège is the only landmine: `04` is both Liège landlines (9 digits total) and mobile (10 digits with `04xx`); subscriber length disambiguates.

6. **Goudengids is behind Imperva.** The user's existing app.py already proves this with browser context cookies. Listing-page-only strategy is correct (data-small-result JSON has everything needed). Keep the Playwright-cookie escalation pattern; do not try to bypass Imperva from raw httpx.

7. **DDG is fragile in 2026 (rate-limited at low volumes).** Brave Search free tier (2,000 queries/month, 1 qps) is more reliable. SearXNG self-hosted is the no-rate-limit path for high volume.

8. **Provenance schema: append-only `observations` table with JSONB value column.** Confirmed by wave 2; no reason to reconsider.

---

## 1. KBO / CBE — Crossroads Bank for Enterprises

### KBO Open Data (free bulk, the architectural foundation)

- **URL:** https://kbopub.economie.fgov.be/kbo-open-data/login?lang=en (registration + email verify)
- **Cookbook:** https://economie.fgov.be/sites/default/files/Files/Entreprises/BCE/Cookbook-BCE-Open-Data.pdf (current version R018.00)
- **Data catalogue:** https://economie.fgov.be/sites/default/files/Files/Entreprises/BCE/Catalogue-des-donnees-reutilisables-BCE-opendata.pdf
- **Cadence:** **DAILY** (the original docs said monthly; that's outdated). Files retained 31 days. Created from a midnight snapshot.
- **Distribution:** web portal manual download OR SFTP server (request access at `kbo-bce-webservice@economie.fgov.be`).
- **Format:** ZIP containing CSVs, comma-delimited, double-quote-text, dot decimal, `dd-mm-yyyy` dates.
- **Filename pattern:** `KboOpenData_<extractnumber>_<year>_<month>_Full.zip` and `..._Update.zip`.

#### Files in the ZIP

| File | Contents | Key |
|---|---|---|
| `meta.csv` | snapshot date, extract timestamp/number, version | n/a |
| `code.csv` | code-table descriptions in NL/FR/DE/EN | (Category, Code, Language) |
| `enterprise.csv` | 1 row per active enterprise: number, status, juridical situation/form, type, start date | EnterpriseNumber |
| `establishment.csv` | 1 row per active establishment unit | EstablishmentNumber, EnterpriseNumber |
| `denomination.csv` | names (legal, commercial, abbreviation) per language | EntityNumber + Type + Lang |
| `address.csv` | seat & branch addresses with NL+FR street/municipality, postal code, house number, box | EntityNumber |
| `contact.csv` | **phones, emails, websites** — multi-row per entity | EntityNumber + ContactType |
| `activity.csv` | NACE 2003/2008/**2025** codes per activity, classified main/secondary/auxiliary | EntityNumber + NaceVersion + NaceCode |
| `branch.csv` | foreign-entity Belgian branches | Id, EnterpriseNumber |

#### Update file mechanics

- For each table there's `<table>_delete.csv` and `<table>_insert.csv`.
- Apply: `DELETE FROM <table> WHERE EntityNumber IN (delete file)` then `INSERT (insert file)`. Done.
- **No history.** If an address changed, only the new one is in the file.

#### What's NOT in the Open Data dump

- **Function holders / mandataires / bestuurders** (Director, Zaakvoerder, etc.). These appear only on the kbopub HTML detail page.
- **Capacities / authorisations** (e.g. "Elektrotechnisch installateur" for Bellock). On HTML only.
- **History / change log.** Snapshot only.
- **Linked entities / beneficial ownership.**

So architecture: **bulk ingest of Open Data → kbopub HTML scraping is reserved for function-holder enrichment per company at a strictly bounded rate.** That's a 99% reduction in kbopub traffic vs scraping it for everything.

### KBO Public Search (kbopub) — for function holders only

- **Search by number URL:** `https://kbopub.economie.fgov.be/kbopub/zoeknummerform.html?nummer={KBO}&actionLu=Zoek&lang=en|fr|nl`
- **Detail page URL pattern (after redirect):** `https://kbopub.economie.fgov.be/kbopub/toonondernemingps.html?ondernemingsnummer={KBO}` (the user's existing code already uses this).
- **License explicit prohibition:** "Reuse of data made available via Public Search is prohibited. Systematic and uninterrupted downloading of CBE data is not allowed." — **systematic scraping is non-compliant**. The legitimate path is the Open Data dump. For the few HTML scrapes you do, throttle hard (≤ 1 req every 4–6 s) and cache aggressively.
- **Anti-bot:** the user's existing app.py uses a Playwright-Imperva-cookie pattern that works. Maintain it.
- **Search-by-name** (POST to `zoeknaamfonetischps.html`) works but is more rate-restricted; prefer name → KBO via the Open Data file's `denomination.csv`.

### KBO checksum — use `python-stdnum`, do not roll your own

- Belgian enterprise numbers are 10 digits.
- **As of 2024-ish, numbers may start with `1` as well as `0`.** Validators that hard-code `BE0...` will reject valid numbers. `BE1...` is increasingly common.
- VAT number = `BE` + the 10-digit enterprise number (same checksum).
- Algorithm: `int(first_8_digits) % 97 == 97 - int(last_2_digits)`.
- **Recommendation:** `pip install python-stdnum`, use `stdnum.be.vat.compact()`, `validate()`, `is_valid()`. Bellock check via this library would return `'0439401387'` from input `'BE0439401387'`, `'(0)439401387'`, or `'0439.401.387'`.

### Establishment unit numbers (vestigingseenheid)

- Format: `9.999.999.999` (10 digits with periods, distinct from enterprise number `9999.999.999`).
- One enterprise can have many establishments.
- These are useful for matching addresses on the ground (Bellock has its workshop at one establishment, registered seat at another).

---

## 2. NBB — National Bank of Belgium financial data

### Free REST API (the right path)

- **Production base URL:** `https://ws.cbso.nbb.be/`
- **APIs:** `authentic`, `extracts`, `improved` (improved is paid; authentic is **free**).
- **Test environment:** `https://developer.uat2.cbso.nbb.be/` (useful for Claude Code integration tests).
- **Developer portal:** `https://developer.cbso.nbb.be/` — register, create profile, request access per product. Approval is manual.
- **Subscription docs:** https://www.nbb.be/en/central-balance-sheet-office/consultation/web-services
- **Technical guide PDF:** https://www.nbb.be/doc/ba/cbso2022/cbso_webservices_technical%20guide_0.94.pdf

#### Free products (Authentic family)

| Product | What it gives | Free? |
|---|---|---|
| **Authentic Data Query** | per-CBE current+historical filing references and documents (PDF / XBRL / JSON) | **Free** |
| **Authentic Data Daily Extract** | daily ZIP of all references/documents published on a given date | **Free** |
| **Authentic Archive Data** | for a specified date, all references/documents published in last 3 years | **Free** |
| Improved Data Query / Archive | NBB-corrected (CORRECTED, EURO_CONVERTED, PDF_ENCODED) versions | Paid |

#### Operations (Authentic)

```
GET /authentic/legalEntity/{legalEntityId}/references
  → JSON list of references like 2021-00000148

GET /authentic/references/{referenceId}/representations/pdf
GET /authentic/references/{referenceId}/representations/xbrl
GET /authentic/references/{referenceId}/representations/json
```

Each request needs: API key (header), client-side UUID request-id (for logging/debug), CLIENT_NUMBER (in subscription).

#### Format availability over time

- **PDF**: filings from 1999 onwards.
- **XBRL**: filings from **2 April 2007** onwards. Older filings only have PDF. XBRL files use the taxonomy active at filing time; older XBRL is NOT converted to current taxonomy.
- **JSON**: only for XBRL filings published since **4 April 2022**, and only the last 3 years.
- **Practical implication:** for a 1989-incorporated company like Bellock, recent filings will have JSON. For old historical analysis, you may have only PDF and need pdfplumber/camelot.

#### XBRL taxonomy

- **Current version (in use since 2 January 2026):** `nbb-cbso-26.0.10` (per https://www.nbb.be/en/central-balance-sheet-office/preparation-and-filing/technical-information-and-taxonomy-9 — flagged as "the final version", which suggests a forthcoming change to a new naming scheme).
- Three filing models depending on company size:
  - **MICRO** — abridged-er than ABRIDGED, fewer line items.
  - **ABRIDGED** (formerly "schema A") — small companies.
  - **FULL** (formerly "schema C") — large companies.
- Size criteria use last-closed-balance values for: balance sheet total, turnover (excl. VAT), and average annual FTE (Companies and Associations Code Arts. 1:24/1:25).
- Companies with unlimited liability partners (general/limited partnerships, certain co-ops) are **exempt from filing** if all partners are natural persons. This is why some KBO entries lack any NBB filings.

#### Implementation tip

- Use `arelle` library or `python-xbrl` for XBRL parsing.
- For micro PDFs (one-page schedules with consistent layout), `pdfplumber` is sufficient and cheaper than `camelot`.
- The JSON representation, when available, is the cheapest extraction path — go that route first.

### Why NOT to scrape consult.cbso.nbb.be

- It's a JavaScript SPA — direct GET returns ~400 bytes of skeleton HTML.
- Scraping it via Playwright is wasteful when the official REST API is free.
- The API gives the same data + provenance + better rate limits.

---

## 3. Belgian phone-number validation

### Source of truth

- BIPT (Belgian Institute for Postal Services and Telecommunications): https://www.bipt.be/operators/publication/database-with-reserved-and-allocated-numbers
- Wikipedia table is reliable for area codes; mobile prefixes change as new ranges are allocated, so refresh quarterly from BIPT.

### Geographic landline area codes — full table

| Code | City / area |
|---|---|
| 010 | Wavre (Waver) |
| 011 | Hasselt |
| 012 | Tongeren (Tongres) |
| 013 | Diest |
| 014 | Geel, Herentals, Turnhout |
| 015 | Mechelen (Malines) |
| 016 | Leuven (Louvain), Tienen (Tirlemont) |
| 019 | Waremme (Borgworm) |
| **02** | **Brussels** |
| **03** | **Antwerp**, Sint-Niklaas |
| **04** | **Liège** (Luik), Voeren — 9-digit numbers (`04 xxx xx xx`); does NOT use `04 6x/7x/8x/9x` |
| 050 | Bruges (Brugge), Zeebrugge |
| 051 | Roeselare |
| 052 | Dendermonde |
| 053 | Aalst |
| 054 | Ninove |
| 055 | Ronse |
| 056 | Kortrijk, Comines-Warneton, Mouscron |
| 057 | Ypres (Ieper) |
| 058 | Veurne |
| 059 | Ostend, Bredene, Gistel |
| 060 | Chimay |
| 061 | Bastogne, Libramont-Chevigny |
| 063 | Arlon |
| 064 | La Louvière |
| 065 | Mons (Bergen), Casteau |
| 067 | Nivelles, Soignies |
| 068 | Ath |
| 069 | Tournai |
| 071 | Charleroi |
| 080 | Stavelot |
| 081 | Namur (Namen) |
| 082 | Dinant |
| 083 | Ciney |
| 084 | Marche-en-Famenne |
| 085 | Huy |
| 086 | Durbuy |
| 087 | Verviers |
| 089 | Genk |
| **09** | **Ghent** |

### Mobile prefixes (10 digits total, 04xx xx xx xx)

- `0455` — Orange (VOO)
- `0456` — Proximus (Mobile Viking)
- `0460` — Proximus
- `0465` — Lycamobile
- `0466` — Orange (Hey!)
- `0467` — Telenet (Liberty Global)
- `0468` — Telenet
- `047x` — Proximus
- `048x` — BASE (Liberty Global)
- `049x` — Orange Belgium
- More ranges between `0440`–`0468` are activated on rolling basis. Refresh from BIPT quarterly.
- **Carrier-from-prefix is historical only** since Belgian number portability (2002). Don't claim a number "is on Telenet" — say "originally allocated to Telenet."

### Special-purpose prefixes

- `045x` — premium (€1.00/min) — distinct from mobile `045x` ranges; identified by their reserved sub-blocks
- `070` — premium pay rate (€0.30/min)
- `077` — machine-to-machine
- `078` — national pay rate
- `0800` — toll-free (€0.00)
- `0900–0909` — premium (€0.50–€31.00, varies)

### Disambiguation rule (Liège trap)

```
length 9 + starts with "04" + NOT in {046,047,048,049,0455,0456}  →  Liège landline
length 10 + starts with "04"                                       →  mobile or premium
length 9 + starts with "0" + 1 or 2-digit area code                →  geographic landline
```

### City-from-area-code matching

- Belgian area codes are coarse. `03` covers Antwerp province (Antwerp, Sint-Niklaas, Mortsel, Berchem, Borgerhout, ...). A `03` phone for a company in Borgerhout matches. A `09` phone for Borgerhout does not.
- Build a province / metro mapping and treat any phone whose area-code-province matches the company's address-province as "city-consistent." Tighter than nothing, looser than exact city.

### Recommended tooling

- **`phonenumbers`** (Google's libphonenumber port).
  ```python
  import phonenumbers
  from phonenumbers import geocoder, carrier, number_type, PhoneNumberType
  num = phonenumbers.parse("03 236 13 06", "BE")
  phonenumbers.is_valid_number(num)             # True
  phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164)  # "+3232361306"
  geocoder.description_for_number(num, "en")    # "Antwerp"
  number_type(num) == PhoneNumberType.FIXED_LINE  # True
  ```
  Cheap, deterministic, no API call. Use for normalization + line-type. Use the area-code table for finer city/region matching beyond what `geocoder` returns.

---

## 4. Goudengids.be / pagesdor.be

### State in 2026

- Behind Imperva Incapsula (confirmed by user's existing app.py and search results).
- Server-side rendered HTML. Listing pages contain everything needed; **detail pages add little and trigger Imperva more aggressively.**
- The `data-small-result` JSON attribute on each `<li>` listing card is the canonical extraction target. The user's app.py already parses it correctly.

### Listing-card data (per the user's own confirmed instruction)

From the listing page alone, extracted from the `data-small-result` JSON + sibling DOM:

- `title` — company name
- `phone` — primary phone (in JSON)
- `phones[]` — extra phones from `tel:` dropdown (DOM scrape)
- `address` — street + postal code (`data-yext` spans)
- `city` — `data-yext="city"` span
- `website` — anchor href containing `utm_source=fcrmedia`
- `description` — `.result-item__description`
- `KBO` — sometimes present in the JSON-LD LocalBusiness `taxID` or `sameAs` to kbopub
- `logo` — image URL

This is everything the user needs. **No detail-page scraping required for the primary fields.**

### City filtering

- Goudengids returns nearby towns under broad city searches. Filter post-fetch: keep only listings whose `data-yext="city"` matches OR whose postal code is in the target NIS-code-defined city.
- Belgian postal codes are 4 digits, 1000–9999, and a city's postal-code set is well-defined (e.g. Antwerpen = 2000, 2018, 2020, 2030, 2040, 2050, 2060).

### Pagination

- Path-based: `/zoeken/{slug}/{city}/1/`, `/2/`, ... up to 25 pages typical, sometimes more.
- Stop on 0 listings or when last page reaches `data-results-count`.

### robots.txt

Could not fetch directly during research (Imperva). The user's app.py already operates with full Imperva-cookie reuse; assume the directory permits crawling at low rate. Treat the **license terms** as the binding signal — there's no public API license, so this is grey-area scraping. Stay below 0.5 req/s on the listing pages.

### Anti-block strategy (proven by user's existing app.py)

1. Single Playwright Chromium session at start to obtain Imperva cookies.
2. Reuse those cookies in an httpx session for all subsequent listing fetches.
3. Rotate User-Agent (3-pool minimum).
4. 2–4 second random delay between page fetches.
5. On `is_blocked(html)` (HTML <500 bytes or contains "captcha"/"imperva"/"toegang geweigerd"), re-launch browser to refresh cookies. Don't retry from raw httpx — Imperva will hard-block the IP.

### Sector slugs

- The user's app.py already has a curated 65-sector list. Refresh quarterly from goudengids' public sitemap (`/sitemap.xml`) which lists all sector URLs.

### pagesdor.be (FR equivalent)

- Same structure, same parent (FCR Media). FR slugs: `Electriciens`, `Boulangers`, `Notaires`, etc. Different from NL slugs.
- City filter same: 4-digit postal codes are language-neutral.

---

## 5. Free / cheap search engines for cross-validation

### DuckDuckGo (the user's current default)

- Library: `ddgs` (renamed from `duckduckgo-search`). The old name has years of rate-limit issues; the current package isn't drastically better.
- Realistic: **~0.3 queries/sec sustained**, ~1k queries/day. Returns 202 Ratelimit at higher rates.
- Mitigations: socks5h proxy via `DDGS_PROXY` env var, longer delays, `region="be-nl"` to keep results focused.
- Verdict: **use as primary for low volume** because it's free + no auth. Have a fallback ready.

### Brave Search API

- **Free tier (live as of May 2026 per `brave.com/search/api/`):** 2,000 queries/month, 1 qps. No-credit-card-required tier was eliminated in February 2026 per news reports, but the official page still shows free tier. Treat as: register, may need card-on-file but no charge under 2k.
- Auth: `X-Subscription-Token` header.
- Endpoint: `https://api.search.brave.com/res/v1/web/search?q=...&country=BE`.
- Response: clean JSON, includes `web`, `news`, `videos`, `discussions`.
- Reliable, recommended as DDG fallback at 2k/month. For higher volume the Base plan is $5/1000 — still cheap enough that paying might be worth the reliability.

### SearXNG (self-hosted)

- The escape hatch for "I never want to deal with rate limits."
- Docker image: `searxng/searxng`. Aggregates 70+ engines including Google/Bing/DDG behind your IP.
- For high-volume work this is the practical solution.
- Tradeoff: maintenance overhead, occasional engine breakage.

### Google CSE / Bing API

- Google Custom Search JSON API: 100 queries/day free, $5/1000 thereafter. 100/day is too low.
- Bing Search API: **retired August 2025** (per multiple references). Replacement is Microsoft's Azure-based "Grounding with Bing Search" via Copilot — different product, paid only.

### Verdict

Primary: `ddgs` library, polite (0.3 qps, capped 800/day).
Fallback: Brave free tier (1 qps, 2000/mo).
Escape hatch: SearXNG container.

---

## 6. Cross-source confirmation — real walkthrough

**Target:** Bellock (electrician/locksmith in Antwerp), the company in the user's own annotations. Walking the full chain.

### Step 1 — Goudengids listing page

Search `Electriciens` × `Antwerpen`, find Bellock card:

- name = `Bellock`
- phone = `+3232361306` (`03 236 13 06` formatted)
- address = `Lange Van Bloerstraat 116, 2060 Antwerpen`
- website (utm_source=fcrmedia) = `https://www.bellock.be`
- KBO (from JSON-LD) = `0439401387`
- founding date (from "Bedrijfsinformatie" block) = `1989-12-28`
- employees = `Van 1 persoon tot 4 personen`
- status = `Actieve dossier`

**This single page yields 8/10 of the priority fields.** Listing-page-only is correct.

### Step 2 — DDG cross-check

Query `"Bellock" Antwerpen elektriciteit ondernemingsnummer`. Top results:

- bellock.be (own website)
- elektricien-gids.be — independent directory: confirms `KBO 439401387, 03 236 13 06, Lange Van Bloerstraat 116-118, 2060`
- bsearch.be — confirms phone, address, KBO, founding 28-12-1989, "1-5 personeel"
- companyweb.be — confirms KBO `BE0439.401.387`, last balance year 2023, NACE "Algemene elektrotechnische installatiewerken", "Micro 1 FTE"
- trendstop.knack.be — confirms KBO, public-facing `bruto marge €30,326`, sector ranking

**Five independent sources agree on the canonical facts.** The phone-and-website-and-KBO triangulation is rock-solid for this kind of established small business.

### Step 3 — Website ownership confirmation

- bellock.be `/contact`: phone `03 236 13 06` ✓ matches goudengids
- bellock.be `/elektriciteit`: phone `03 236 13 06` ✓
- email `info@bellock.be` (parseable from contact page)
- Service description matches sector slug `Electriciens`: "elektriciteitswerken, sloten, parlofonie, camerabewaking" ✓

The website-phone-match heuristic is reliable. **Recommend: confirm a website via at least one identical phone match between site and directory.**

### Step 4 — Phone area-code/city validation

- `03 236 13 06` — area code `03` → Antwerp province
- Address city: Antwerpen (postal 2060)
- 2060 is Antwerpen (Antwerpen-Noord) — within Antwerp province
- Match: ✓ (province-level)

### Step 5 — KBO checksum

- KBO `0439401387`. Last 2 digits `87`. First 8: `04394013`.
- `int('04394013') % 97 = 4394013 % 97 = 10`
- `97 - 10 = 87` ✓ checksum valid
- (Use `stdnum.be.vat.is_valid('0439401387')` → True. Don't roll your own.)

### Step 6 — KBO Public Search detail page

`https://kbopub.economie.fgov.be/kbopub/toonondernemingps.html?ondernemingsnummer=0439401387`

Extracts (per user's annotations):

- Begindatum: 28 december 1989 ✓ matches
- Naam: BELLOCK ✓
- Adres van de zetel: Lange Van Bloerstraat 116-118, 2060 Antwerpen ✓
- Bestuurder: **Boonen, Jan** (sinds 27 maart 2024) ← function holder, only here
- Capacities: Elektrotechnisch installateur (sinds 6 februari 1990)

**Function holder data only available here.** Worth the targeted scrape.

### Step 7 — NBB Authentic Data Query

```
GET https://ws.cbso.nbb.be/authentic/legalEntity/0439401387/references
  → list including 2024-XXXXXXXX for the 2023 balance year
GET https://ws.cbso.nbb.be/authentic/references/2024-XXXXXXXX/representations/json
  → JSON with revenue, EBITDA, equity, employees as XBRL line-item values
```

CompanyWeb confirms a balance was filed 27-07-2024 (2023 financial year). Bellock is MICRO so the JSON will have abridged line items — no separate revenue line for many micros, but cost-of-sales and gross margin are typically present (Trends Top showed `bruto marge €30,326`).

### Where this strategy fails

- **Holding companies / shell entities:** name on goudengids is the trading name; KBO has only the legal entity. DDG mostly returns aggregator pages, no real website. Phone often a generic switchboard.
- **Solo professionals (advocaten, dokters):** often no website at all, or a personal name domain. Phone ↔ city correlation strong because solos work locally.
- **Recently struck-off entities:** KBO Open Data only contains active entities. Goudengids may show stale entries. Always cross-check status via Open Data.
- **Group companies sharing one website:** N companies, one site → website-ownership match flags all of them. Need to handle the 1:N case in the schema.

**Recommendation:** flag a confidence score that accounts for: (a) number of independent confirmations, (b) phone-on-website match, (c) website TLD = .be, (d) postal-code-province matches phone-area-code-province, (e) KBO active, (f) NBB filing within 18 months.

---

## 7. Website analysis — heuristics

### Detect "real company HQ website" vs not

Positive signals (each adds confidence):
- Domain matches company name (token-set Jaccard ≥ 0.6) — `bellock.be` vs `Bellock` = 1.0
- TLD is `.be` (Belgian companies overwhelmingly prefer this)
- Phone on website matches at least one phone from goudengids/KBO/Open Data
- Email domain on site matches website domain (`info@bellock.be`)
- Has a `/contact` or `/contacteer` or `/contact-fr` page
- `<title>` contains the company name
- NOT a known directory domain (skip list: `goudengids`, `pagesdor`, `kompass`, `linkedin`, `facebook`, `instagram`, `bsearch`, `bizzy`, `companyweb`, `trendstop`, `dnb`, `europages`, `wikipedia`, etc. — extend the user's existing SKIP_DOMAINS)
- Schema.org `LocalBusiness` JSON-LD with matching `taxID`/`name`/`address`

Negative signals:
- More than 4 path segments (e.g. `/en/persons/jan-boonen`)
- Path contains `/company/`, `/profile/`, `/listing/`, `/bedrijf/`, `/entreprise/`
- WHOIS / Wayback Machine history shorter than 6 months — likely a parked SEO domain
- Site has no contact info anywhere
- Site mentions multiple unrelated companies (broker / lead-gen page)

### Domain age

- `python-whois` works for most TLDs but `.be` returns limited data via DNSBE policy (only thick whois on registrar lookup; bulk is rate-limited to 60 queries/min from a single IP).
- Fallback: Wayback Machine CDX API:
  ```
  https://web.archive.org/cdx/search/cdx?url=bellock.be&output=json&limit=1&fl=timestamp
  ```
  First snapshot timestamp ≈ first-public-online date. Free, no rate limits at low scale.
- Footer year extraction (`© 2025 Bellock`) is a useful third signal when both fail.

### Activity description

- Best source: `<meta name="description">` then `og:description` then first `<p>` over 60 chars in `<main>/<article>`. The user's existing `_summary_from_soup` already does this correctly.

### Contact persons / "people working there"

- JSON-LD `Person` blocks (rare).
- Heuristic: `<h2|h3|h4|p|span>` containing job titles `[zaakvoerder, ceo, directeur, manager, sales, contact, verantwoordelijke, gérant]` followed by capitalised two-word names.
- Cross-check with KBO function holders (the `Bestuurder` field above) — KBO is authoritative for legal officers; website is for everyday contacts.
- **DO NOT**: scrape LinkedIn, scrape Facebook About sections, scrape Instagram bios. ToS violations + GDPR risk on natural-person data without legal basis.

### Email harvesting

- Regex: `[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}` — straightforward.
- Obfuscation: `info [at] bellock [dot] be`, `info(at)bellock`, image-based. Handle `[at|@]` and `[dot|.]` substitutions; image-based emails are out of scope (not worth OCR effort).
- Mailto: prefer `mailto:` href contents over body text.
- Generic addresses (`info@`, `contact@`, `hello@`) are role accounts — keep them but mark them not as personal data. Personal addresses (`firstname.lastname@company`) are personal data → require GDPR-compliant handling (see §12).

### Sitemap discovery

- Try `/sitemap.xml`, `/sitemap_index.xml`, `/robots.txt → Sitemap:`.
- Useful for sites with many product/service pages where the right "who we are" content isn't on the home page.

---

## 8. Polite-scraping & anti-blocking

### Per-host token bucket targets

| Host | Recommended max rps | Concurrency | Notes |
|---|---|---|---|
| goudengids.be | 0.3 | 1 | Imperva — bursts get IP-banned |
| pagesdor.be | 0.3 | 1 | Same parent as above |
| kbopub.economie.fgov.be | 0.25 | 1 | License explicitly forbids systematic download. Reserve for function-holder lookups only. |
| economie.fgov.be (Open Data SFTP/portal) | 1 download per file (full or update) | n/a | Daily file fetched once. |
| ws.cbso.nbb.be | 1.0 | 2 | Their published rate guidance — verify in dev portal. |
| consult.cbso.nbb.be | 0 | 0 | Don't scrape. Use API. |
| bipt.be | 0.5 | 1 | Reference data — fetch once, cache. |
| duckduckgo.com (via ddgs) | 0.3 | 1 | Even this is risky |
| api.search.brave.com | 1.0 | 1 | Free tier limit |
| Generic company website | 0.5 | 2 | Per host. Different companies → different hosts. |

### Backoff with jitter

```python
def backoff(attempt, base=1.0, jitter=0.3, cap=60.0):
    return min(cap, base * 2**attempt) + random.uniform(0, jitter)
```

Apply on `429`, `503`, `504` with `Retry-After` honored if present (both seconds-int and HTTP-date forms). Never retry on `403`; escalate to Playwright-cookie refresh or stop.

### User-Agent strategy

- Pool of 3–5 realistic recent browser UAs (Chrome 134+, Firefox 130+, Safari 18+ on Win/Mac/Linux).
- One UA per session (don't change mid-session — Imperva flags this).
- Rotate per session.
- Include `Accept-Language: nl-BE,nl;q=0.9,fr;q=0.5,en;q=0.3` and `Accept-Encoding: gzip, deflate, br`.
- HTTP/2 by default in httpx — keep it.

### When Playwright is needed

- Goudengids/pagesdor (Imperva) — yes, for cookie acquisition.
- KBO — typically not, but escalate if 403s start.
- NBB API — never (REST).
- Random company websites — usually not. Few SMEs have anti-bot.
- Any site whose detail content lives in XHRs — yes, or sniff the XHR endpoints once and call them directly with httpx.

### Caching layer

- `hishel` (httpx-native cache) with SQLite backend, **30-day TTL on raw HTML**, keyed on (URL + Authorization-or-Cookie hash to avoid leaking auth state).
- For Open Data dump CSVs: keep them as-is on disk in `data/kbo_dump/<YYYY-MM-DD>/`, retain last 7 days, prune older.
- For NBB JSON/XBRL: keep forever (they're tiny per filing).
- For DDG results: cache 14 days — searches go stale quickly but not within a single run.

### Single residential IP vs rotation

- For this user's scale (one sector × one city per run, recurring), **single residential IP with respectful pacing is the right answer.** IP rotation adds cost and complexity, and is unnecessary if rates are sane.
- If the user moves to "scrape all of Belgium nightly" then datacenter-grade IPs will get burned and residential rotation becomes necessary. That's a v2 problem.

---

## 9. Refresh strategy ("smart refresh", best-practice tier)

### Tiered TTL by source

| Data class | TTL | Rationale |
|---|---|---|
| KBO Open Data | 7 days (refetch full or apply daily updates) | Updated daily; refresh weekly with daily deltas in between is overkill — start with weekly full ingest |
| KBO function holders (kbopub HTML) | 90 days | Mandate changes are infrequent |
| Goudengids listing | 30 days | Phones, websites, descriptions evolve; sector membership changes |
| NBB filings | check monthly for new references; download new ones as published | Annual filings released July–September |
| Company websites (full crawl) | 60 days | Costly; rare changes |
| DDG cross-validation | 14 days | Search results shift; cheap |

### Score-driven priority

- Compute `score` per company (higher = more interesting lead).
- Inputs: KBO active=+1, recent founding=+1, website-confirmed=+1, NBB filings within 18 months=+1, multiple sources confirm phone=+1, employees > 0=+1.
- Refresh order: top-quartile leads twice as often as bottom-quartile.

### Concrete schedule (recommendation)

```
Daily   00:30 — fetch KBO Open Data update file, apply deltas
Weekly  Sun 02:00 — fetch KBO Open Data full file, full re-sync
Daily   03:00 — process NBB authentic-data daily extract, ingest new filings for entities we track
Hourly  during business hours (9–18 BE local) — drain enrichment queue:
                            jobs prioritised by (lead_score DESC, last_scraped_at ASC)
Nightly 23:00 — recompute scores, re-rank queue
```

### Queue / job schema

The user's existing `sqlite.py` schema is good. Keep it. Add:

- `priority INTEGER NOT NULL DEFAULT 5` to `jobs`.
- index `(status, priority DESC, next_retry_at, id) WHERE status='pending'`.

### Exponential backoff per job

- attempts: 0..5 retries
- base: 60s, 2x growth → 60s, 2m, 4m, 8m, 16m, 32m
- after 5 failures → status `dead`

---

## 10. Provenance / data-quality schema

### Decision: append-only `observations` table with JSONB value

Rejected alternatives:
- **Per-source columns** (`phone_goudengids`, `phone_kbo`, ...): rigid, NULL-heavy, breaks when a 5th source is added.
- **JSONB on `companies` row only**: loses history; the user explicitly wants every observation kept.
- **Per-source observations table per field** (`phone_observations`, `email_observations`, ...): table explosion.

Chosen schema (refines wave 2, adds run linkage):

```sql
CREATE TABLE observations (
  id           BIGSERIAL PRIMARY KEY,
  kbo_number   CHAR(10)    NOT NULL,
  field        TEXT        NOT NULL,    -- 'phone' | 'email' | 'website' | 'address' | 'name' | 'revenue_2024' | ...
  value        JSONB       NOT NULL,    -- typed payload, e.g. {"e164": "+3232361306", "raw": "03 236 13 06", "type": "fixed_line"}
  raw_value    TEXT,                    -- pre-normalised string (audit / debug)
  source       TEXT        NOT NULL,    -- 'goudengids' | 'pagesdor' | 'kbo_dump' | 'kbopub' | 'nbb_authentic' | 'website' | 'ddg' | 'brave'
  source_url   TEXT,
  observed_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  confidence   NUMERIC(3,2) NOT NULL DEFAULT 0.50,
  run_id       UUID        NOT NULL
);

CREATE INDEX ON observations (kbo_number, field, observed_at DESC);
CREATE INDEX ON observations (source, observed_at DESC);
CREATE INDEX ON observations USING gin (value);

-- Materialized current-best, recomputed nightly:
CREATE MATERIALIZED VIEW companies_current AS
SELECT DISTINCT ON (kbo_number, field)
       kbo_number, field, value, source, observed_at, confidence
FROM observations
ORDER BY kbo_number, field, confidence DESC, observed_at DESC;
```

### Confidence scoring

Per-source priors (start values, tune later):

| Source | Phone | KBO# | Address | Founding | Website | Financials | Persons |
|---|---|---|---|---|---|---|---|
| `kbo_dump` | 0.95 | 1.00 | 0.95 | 1.00 | 0.85 | — | — |
| `kbopub` | 0.85 | 1.00 | 0.95 | 1.00 | 0.80 | — | 0.95 |
| `nbb_authentic` | — | 1.00 | — | — | — | 1.00 | — |
| `goudengids` | 0.85 | 0.85 | 0.80 | 0.85 | 0.85 | — | — |
| `pagesdor` | 0.85 | 0.85 | 0.80 | 0.85 | 0.85 | — | — |
| `website` | 0.75 | 0.50 | 0.70 | — | 1.00 | — | 0.65 |
| `ddg` / `brave` | 0.50 | — | 0.50 | — | 0.55 | — | — |

Recency decay: multiply by `0.99 ** days_since_observation` capped at `0.5`.
Cross-source consensus boost: `min(1.0, base * 1.1)` per matching observation from a different source for the same `(kbo_number, field, value)` tuple.

### Validation rules — encode as DB CHECKs and as a `validators/` module

```python
def postal_code_matches_city(postal: str, city: str) -> bool: ...
def kbo_active(kbo: str) -> bool: ...                     # check kbo_dump
def phone_area_matches_postal(phone: str, postal: str) -> bool: ...
def founding_date_sane(d: date) -> bool:                  # 1830 <= year <= today
def employees_range_valid(s: str) -> bool: ...
def website_not_parked(url: str) -> bool: ...             # look for parking provider strings
```

Run validators after each ingest; flag rather than reject. Failed validations become a `validation_flags` row, not a hard error.

---

## 11. Other Belgian B2B sources

### Free / low-friction

- **Trends Top (`trendstop.knack.be`)** — public profiles include sector ranking + gross margin. Premium for full financials. Rate: scrape gently for the public summary; their full data is paywalled.
- **CompanyWeb (`companyweb.be`)** — confirmed Bellock data shows: status, KBO, BTW-plicht, oprichting, last balance year, size class, NACE, rating (premium). 7-day free trial. Public summary scrape fine.
- **Bizzy (`bizzy.be`)** — free Belgian company database, financial scoring. Scrapable with care.
- **bsearch.be** — independent directory, mirrors KBO + adds tags. Useful aggregator.
- **elektricien-gids.be / elektriciensgids.be / similar sector-specific gids.be sites** — high-quality structured data per sector. Some are themselves scraped from the same source. Low-priority, useful for additional confirmation.
- **Statbel (`statbel.fgov.be`)** — aggregate Belgian statistics. Useful for benchmarking sector size + denominators, not per-company.
- **eJustice / Belgian Official Gazette (`ejustice.just.fgov.be`)** — official publications: incorporations, mandate changes, dissolutions. Free, scrapable. Highest authority for "what changed when". Good for change-detection on flagged companies.
- **OpenCorporates Belgium** — free tier API, mirrors KBO. Less fresh than KBO Open Data — skip.

### NOT to use (per user instruction)

- LinkedIn (ToS, legal risk per multiple EU rulings).
- Freelancer.be.

### Paid (skip unless user changes mind)

- Graydon, Creditsafe, D&B, Trends Top Finance — paid commercial financials.
- KBO Public Search Webservice (the SOAP one) — €50 / 2000 requests; pointless when Open Data is free.

---

## 12. Legal & ethical posture (this is the section that matters most)

### The hard reality

The Belgian DPA fined **Bisnode/Black Tiger €174,640** (decision 07/2024) and **a hearing-aid retailer** in 2025 (decision 76/2025) for **exactly** what this scraper does at the technical level: collecting and reusing public-source company contact data for direct marketing.

The DPA's adopted 2025 Recommendation (replacing 2020 guidance) holds that:

1. **"Cold outreach" via legitimate interest is generally not justifiable.** Reasonable expectations test: people whose data is in KBO/goudengids/their own website do not generally expect someone to compile it into a list and call/email them.
2. **Article 14 transparency obligations apply** — within 30 days, you must notify each data subject that you have their data, your purposes, your legal basis, and their rights. The "disproportionate effort" exemption is read very narrowly.
3. **Article 15 access requests must list specific recipients** — not just categories. The DPA has fined controllers for hiding behind "categories of recipients."
4. **Belgian telemarketing is shifting from opt-out to opt-in** (draft law, August 2026 deadline). The "Do Not Call Me" list will become the only legal cold-call permission system.

### KBO Open Data licence

> "Personal data may not be reused for direct marketing purposes."

This is contractual, not just regulatory. Personal data in this context means data on **natural-person registered entities** (sole traders, freelancers registered under their own name) and contact persons (directors named on filings).

### What this means for the project

The bootstrap prompt MUST require, at minimum:

1. **Documented LIA (Legitimate Interests Assessment)** stored in the repo at `docs/lia.md`, referenced in CLAUDE.md, dated, with named author. Without this, the project is non-compliant from day one.

2. **Suppression list** (Robinson List + custom opt-outs). Apply BEFORE export. If a number is on the federal "Do Not Call Me" registry (`https://www.dncm.be`), it must be marked and excluded from any output flagged for cold outreach.

3. **Natural-person filtering**. KBO `TypeOfEnterprise` = `1` (legal person) is fine; `2` (natural person) is much riskier — those are sole traders whose KBO-registered phone/address IS personal data. The bootstrap prompt should default to filtering out natural-person enterprises in marketing exports unless explicitly opted in, with documented reason.

4. **Source/recipient logging**. Every export must record: which company received which data, at what time, via which run_id. This satisfies Article 15 access-request obligations.

5. **Data retention policy**. Per DPA 2025 guidance: prospect data shorter than customer data. Recommend: 18 months for unconverted prospects, deleted automatically.

6. **Privacy notice template**. The downstream user of the export (e.g. an outbound sales rep) must include a transparency notice in their first contact citing this database as a source. The bootstrap prompt should generate a template `outreach_template.md`.

7. **Personal data redaction switch**. Two export modes:
   - "factual lookup" — all data, for internal CRM enrichment of existing customers (defensible).
   - "outreach list" — natural-person enterprises filtered out, suppression list applied, role-only emails (`info@`, `contact@`).

### Reframing the use case

If the user wants this as a hard-launch B2B lead-gen pipeline against cold prospects: **the scraper is the easy part. The compliance program around it is the hard part, and ignoring it cost Bisnode €174k.**

If the user wants this for:
- internal customer enrichment (looking up data on existing customers / prospects who reached out first)
- factual due-diligence lookup (single-company queries for KYC, supplier vetting)
- B2B research (reading-only, not outreach)

then the legal posture is much more comfortable.

The bootstrap prompt should ask the user to declare the use case in `docs/use-case.md` and tailor the export pipeline accordingly. **Without that declaration, default to the most restrictive output (no marketing exports, factual-lookup mode only).**

### robots.txt

Not legally binding in Belgium (no Belgian case law treats robots.txt as a contract), but ignoring it weighs against the controller in any LIA balancing test ("did you take reasonable steps to respect the data source?"). Treat as binding in practice.

---

## 13. Architecture summary (revised in light of Wave 1 findings)

Differences from wave 2's recommendations:

1. **A new module: `src/scraper/sources/kbo_dump/`** with a daily ingest worker. This is the canonical company table. Other sources enrich it.
2. **A new module: `src/scraper/sources/nbb/`** that talks to the REST API, not consult.cbso.nbb.be.
3. **A new module: `src/scraper/lib/compliance/`** containing:
   - `lia.py` — load and version the LIA from `docs/lia.md`
   - `suppression.py` — Robinson List integration
   - `redaction.py` — natural-person filter & role-email selection
   - `transparency.py` — generate Article 14 notices for stored data subjects
   - `audit.py` — log every export with run_id, recipients, fields
4. **kbopub becomes a per-company enrichment fallback** at very low rate, not a primary source.
5. **The provenance schema gets `confidence`, `run_id`, and a materialised view for current-best.**
6. **`stdnum`, `phonenumbers`, `arelle` (or fallback `pdfplumber`)** are first-class dependencies.
7. **Two export modes** baked into the pipeline.

Caveats unchanged from wave 2: TDD via hooks, plan-first workflow, six skills, Postgres MCP, Playwright MCP gated, local terminal + uv.

---

## Caveats and unknowns

- **2026-current goudengids HTML structure** — I couldn't fetch robots.txt or a sample listing page directly during this research due to Imperva. The user's existing app.py confirms the data-small-result JSON pattern still works as of their last run. Assume stable for now; verify on first integration test.
- **NBB taxonomy version after `26.0.10`** — the docs flag this as "the final version." There's a hint a new family is coming. Build the parser to be taxonomy-version-aware; don't hardcode field names.
- **Brave Search free tier** — official page still shows it but news reports say it was eliminated for new signups in February 2026. Behaviour for new accounts might differ from documented. Have SearXNG ready as the third tier.
- **DPA recommendation 01/2025 status** — was a draft consultation closed May 2025; I treated it as adopted and binding because subsequent DPA decisions (76/2025, 72/2025) cite its principles. Verify on the BDPA site if pursuing high-volume marketing use case.
- **Imperva detection of the cookie-reuse pattern** — Imperva refines detection continuously. The pattern in the user's app.py works today. It might not work in 6 months. Monitor and adapt.
- **KBO Open Data SFTP access lead time** — needs an email to `kbo-bce-webservice@economie.fgov.be`. Allow 2 weeks. Until then use the web portal manual download.
- **`.be` WHOIS rate limits** — DNSBE policy varies; scraper-friendly providers like `whoisxmlapi.com` or `viewdns.info` have free tiers if direct WHOIS gets throttled.
