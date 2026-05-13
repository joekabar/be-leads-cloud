# Search Engine Operational Specs

## Brave Search API

Base URL: `https://api.search.brave.com/res/v1/web/search`
Auth: header `X-Subscription-Token: <key>`

Required headers:
```
Accept: application/json
Accept-Encoding: gzip
X-Subscription-Token: <BRAVE_SEARCH_API_KEY>
```

Query params:
| Param | Type | Default | Notes |
|-------|------|---------|-------|
| `q` | string | required | the search query |
| `count` | int | 10 | max 20; keep at 10 to preserve quota |
| `country` | string | "BE" | pass "BE" for Belgian-biased results |
| `search_lang` | string | "nl" | pass "nl" or "fr" based on company language |
| `safesearch` | string | "moderate" | keep default |
| `offset` | int | — | **DO NOT USE** — burns quota |
| `result_filter` | string | "web" | keep default |

Free tier limits:
- 2 000 queries per month
- 1 query per second
- HTTP 429 when over QPS
- HTTP 403 when monthly quota exhausted (raised as `BraveQuotaExhausted`)

Response shape (2026):
```json
{
  "type": "search",
  "web": {
    "type": "search",
    "results": [
      {
        "type": "search_result",
        "title": "Bellock - Elektriciteit Antwerpen",
        "url": "https://www.bellock.be/",
        "language": "nl",
        "description": "...(DO NOT STORE — copyright)"
      }
    ]
  }
}
```

We parse **only**: `title`, `url`, `language`. `description` is discarded.

## DuckDuckGo (via `ddgs` Python library)

Library: `ddgs` on PyPI (the maintained successor to `duckduckgo-search`).

Usage pattern:
```python
import asyncio
from ddgs import DDGS

def _sync_search(query: str, region: str) -> list[dict[str, str]]:
    ddg = DDGS()
    results = ddg.text(query, max_results=10, region=region, safesearch="moderate")
    return list(results) if results else []

results = await asyncio.to_thread(_sync_search, query, "be-nl")
```

Result shape:
```python
[{"title": "string", "href": "https://...", "body": "snippet"}]
```

Rate limit handling:
- `ddgs.exceptions.RatelimitException` raised after ~5–10 rapid requests
- On first `RatelimitException`: sleep 60 s, retry once
- On second `RatelimitException`: raise `DdgRateLimitedError`
- The ddgs library is **synchronous** — always wrap in `asyncio.to_thread()`

Region codes: `"be-nl"` for Dutch, `"be-fr"` for French.
