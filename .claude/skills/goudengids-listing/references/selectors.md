# Goudengids listing-page selectors

Last verified: 2026-05-10 against goudengids.be.

## Result card root

```
li[data-small-result]
```

The `data-small-result` attribute value is a JSON string. Parse with `json.loads()`.

## JSON blob fields (from `data-small-result`)

| Key | Type | Description |
|---|---|---|
| `title` | str | Company name |
| `href` | str | Relative URL to detail page (e.g. `/bedrijf/Antwerpen/L389732/Bellock/`) |
| `phone` | str | Primary phone, roughly E.164 without spaces (e.g. `+3232361306`) |
| `logo` | str | Image URL (hosted on `i.fcrmedia.com`) |

## Per-card child element selectors

```
All phones (dropdown):      a[href^="tel:"]         — strip "tel:" prefix
Website:                    a[href*="utm_source=fcrmedia"]  — strip query string
Email (rare):               a[href^="mailto:"]       — strip "mailto:" prefix
Address street:             span[data-yext="street"]
Address postal code:        span[data-yext="postal-code"]
Address city-district:      span[data-yext="city-district"]   (may be absent)
Address city:               span[data-yext="city"]
Short description:          div.result-item__description      (~300 chars)
```

## Phone extraction order

1. `phone` field from the JSON blob (primary)
2. `a[href^="tel:"]` elements in DOM order (additional/mobile numbers)

Deduplicate by raw string. Do NOT validate here — validation is in the transformer.

## Website normalisation

Strip query string from the `utm_source=fcrmedia` link:

```python
from urllib.parse import urlparse, urlunparse
parsed = urlparse(raw_href)
website = urlunparse(parsed._replace(query="", fragment=""))
```

## Detail URL normalisation

If `href` from JSON is relative (starts with `/`), prepend `https://www.{domain}`.

## Empty-results state

Detected by **either**:
- Presence of element matching `.empty-state`
- Page body text containing `"geen resultaten"` (NL) or `"aucun résultat"` (FR)

```python
def is_empty_results_page(html: str) -> bool:
    soup = BeautifulSoup(html, "lxml")
    if soup.select_one(".empty-state"):
        return True
    body_text = soup.get_text(" ", strip=True).lower()
    return "geen resultaten" in body_text or "aucun résultat" in body_text
```

## Last-page detection

`is_last_page = is_empty_results_page(html) or len(cards) == 0`

If the page returned no result cards (even without the empty banner), treat as last page.
