# Website Age Heuristics

## Priority 1: WHOIS (confidence 1.00)

```python
import whois  # python-whois; optional — try-import at top of age.py
from urllib.parse import urlparse
import asyncio

domain = urlparse(url).netloc.removeprefix("www.")
w = await asyncio.to_thread(whois.whois, domain)
cd = w.creation_date
if isinstance(cd, list):
    cd = cd[0]
return str(cd)[:4]  # 4-char year
```

Wrap in try/except Exception — WHOIS servers are flaky; any failure falls through to Priority 2.

## Priority 2: Footer year (confidence 0.70)

```python
import re
text = (soup.find("footer") or soup).get_text()[-1000:]
years = re.findall(r"©\s*(\d{4})", text)
if not years:
    years = re.findall(r"\b(20\d{2})\b", text)
return max(years) if years else None
```

Take `max()` — the most recent copyright year is likely the founding/launch year or last update;
for age estimation we want the *earliest* meaningful signal, but in practice the footer's
copyright year is often the site launch year and is the only signal available.

## Priority 3: Wayback CDX (confidence 0.95) — DEFERRED

```
TODO: GET https://web.archive.org/cdx/search/cdx?url={domain}&limit=1&output=json
First-snapshot year. 60 req/min hard ceiling (0.8 rps, concurrency 1 per polite-scraping TOML).
Not implemented this prompt. Implement in a later prompt when Wayback integration is added.
```

## Return type

`tuple[str | None, str]` where:
- First element: 4-char year string (e.g. `"2017"`) or `None`
- Second element: source label — one of `"whois"`, `"footer"`, `"none"`
