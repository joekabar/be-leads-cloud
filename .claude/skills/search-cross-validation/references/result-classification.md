# Result Classification Rules

## Bucket: official_website

The domain (netloc, lowercased, `www.` stripped) matches the company name normalised.

**Normalisation steps:**
1. Strip diacritics via `unicodedata.normalize("NFD")` then ASCII encode
2. Lowercase
3. Split on non-word characters (`\W+`)
4. Remove words that are common Belgian legal-form suffixes:
   `bv nv sa sprl srl bvba cvba scrl commv cv vzw asbl`
5. Join tokens and strip all remaining non-alphanumeric characters

**Domain stem extraction:**
- Take the domain labels up to but NOT including the final TLD
- Remove dashes and other non-alphanumeric chars
- Lowercase

**Match rules (in order):**
1. Exact match between normalised name and normalised domain stem (any TLD) → `official_website`
2. Normalised name is a substring of normalised domain stem AND TLD == `"be"` → `official_website`

**Examples:**
```
"Bellock"           + bellock.be                → official_website  (exact)
"Bellock"           + bellock-elektriciteit.be   → official_website  (contains, .be)
"Bellock"           + bellockantwerpen.be         → official_website  (contains, .be)
"Bellock"           + bellockcars.com            → other             (contains but not .be, not exact)
"Acme BV"           + acme.be                    → official_website  (strip BV → "acme", exact)
"Mediapro"          + mediapro.com               → official_website  (exact)
"Mediapro"          + mediapro.be                → official_website  (exact)
"Bückens & Zoon"    + buckens-zoon.be             → official_website  (strip diacritics & symbols → "buckenszoon", exact)
```

**Tie-breakers** (when multiple official_website candidates, used in transformer):
1. `.be` TLD wins over `.com` / `.eu` / others
2. Shorter domain wins (fewer chars in netloc)
3. `https` wins over `http`

## Bucket: directory

Domain labels (dot-separated) contain any of:
```
goudengids  pagesdor    goldenpages  kbo          kompass     europages
trustlocal  companyweb  bizzy        trendstop    opencorporates  dnb
theorg      freightnet  panjiva      exporthub    b2bhint     namesdir
radaris     cybo        marketinsider  glassdoor  indeed
```

## Bucket: social

Domain labels contain any of:
```
facebook  linkedin  instagram  twitter  x  youtube  tiktok
pinterest  vimeo  foursquare  snapchat
```

Note: `x.com` matches via the "x" label. Social check runs **before** official_website,
so a result on `facebook.com/bellock` is classified social, not official.

## Bucket: news

Domain labels contain any of:
```
vrt  hln  demorgen  standaard  tijd  knack  lalibre  lesoir  rtbf  sudinfo
```
OR the URL path contains `/article/`, `/nieuws/`, or `/actualite/`.

## Bucket: other

Everything else: Wikipedia, forums, government portals, blog posts, etc.

## Per-bucket action

| Bucket | Produces observation? | Where stored |
|--------|----------------------|--------------|
| `official_website` | Yes — `website` field | `observations` table |
| `directory` | No | `cross_validation` JSONB summary only |
| `social` | No | `cross_validation.social_links` list |
| `news` | No | `cross_validation.news_mentions` count |
| `other` | No | Discarded entirely |
