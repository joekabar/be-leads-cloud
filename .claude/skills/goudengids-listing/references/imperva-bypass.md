# Imperva WAF bypass — goudengids.be / pagesdor.be

## Imperva tier

goudengids.be is behind **Imperva Cloud WAF, cookie tier** (verified May 2026). This means:
- A 403 response is returned for requests without valid `incap_ses_*` / `visid_incap_*` cookies.
- The cookies are issued after a browser challenge (JavaScript-based).
- This is NOT the `reese84` tier (which requires solving a CAPTCHA-like challenge).

## Warm-up recipe

### Step 1 — Launch headless Chromium

```python
from playwright.async_api import async_playwright

async with async_playwright() as pw:
    browser = await pw.chromium.launch(
        headless=True,
        args=["--disable-blink-features=AutomationControlled"],
    )
```

`--disable-blink-features=AutomationControlled` removes the `navigator.webdriver` signal
that Imperva checks first.

### Step 2 — Create context with Belgian fingerprint

```python
context = await browser.new_context(
    user_agent=(
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
    ),
    locale="nl-BE",
    viewport={"width": 1280, "height": 720},
)
await context.add_init_script(
    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
)
```

`add_init_script` patches `navigator.webdriver` before the page executes any JavaScript —
this is the belt to `--disable-blink-features`'s suspenders.

### Step 3 — Navigate and wait

```python
page = await context.new_page()
await page.goto("https://www.goudengids.be/", wait_until="domcontentloaded", timeout=30000)
await page.wait_for_selector(
    'input[type="search"], .search-input, form[action*="zoeken"]',
    timeout=30000,
)
```

The selector waits for a known DOM element — once it's visible, the Imperva challenge has
been passed and the session cookies are set.

### Step 4 — Harvest cookies

```python
all_cookies = await context.cookies()
imperva_cookies = {
    c["name"]: c["value"]
    for c in all_cookies
    if re.match(r"^(incap_ses_|visid_incap_|nlbi_|reese84)", c["name"])
}
```

Typical cookie names:
- `incap_ses_<port>_<site_id>` — session cookie (per-page-load)
- `visid_incap_<site_id>` — visitor ID (longer-lived)
- `nlbi_<site_id>` — load-balancer cookie (sometimes absent)
- `reese84` — only if Imperva tier is higher (document as future hardening)

### Step 5 — Close browser

```python
finally:
    await browser.close()
```

Always in a `finally` block to prevent leaked browser processes.

## Cookie lifetime

Cookies typically live **30–60 minutes**. The `WarmupResult.ttl_minutes` is set to `25`
as a safety margin — re-warm at 25 minutes, before typical expiry.

The fetcher auto-checks expiry on every `fetch_page()` call and re-warms proactively.
Do NOT cache cookies across process restarts.

## Retry logic

1. First 403 on a page → trigger re-warm → retry once.
2. Second consecutive 403 → raise `BlockedError` — do NOT retry further.
3. Log `warmup_blocked_twice` and abort the current ingest run.

## Failure modes

| Failure | Cause | Action |
|---|---|---|
| `playwright.errors.Error: Executable doesn't exist` | Chromium not installed | `uv run playwright install chromium` |
| Navigation timeout (30s) | Imperva serving a CAPTCHA page | Retry once with fresh context |
| `reese84` cookie present | Higher Imperva tier detected | See Future Hardening below |
| `nlbi_` cookie absent | Load-balancer not routing this session to a sticky node | Harmless — continue without it |

## Future hardening (not implemented in prompt 8)

If `nlbi_` or `reese84` cookies appear consistently and the warm-up fails:
1. **Mouse movement simulation:** `page.mouse.move(x, y)` and random scrolls before navigation.
2. **Proxy injection:** Pass a residential proxy URL to `browser.new_context(proxy=...)`.
   Residential IPs are not on Imperva's datacenter denylist.
3. **BrightData / Oxylabs residential proxies** — configure via `SCRAPER_PROXY_URL` env var.
   See the Rotating Residential IP section in `agent_docs/runbook.md`.

The injection point for a proxy is in `warmup.py → warmup_cookies()`:
```python
context = await browser.new_context(
    ...
    proxy={"server": proxy_url} if proxy_url else None,
)
```
