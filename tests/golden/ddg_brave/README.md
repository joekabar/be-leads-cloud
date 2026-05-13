# ddg_brave golden fixtures

Hand-crafted JSON fixtures for testing the ddg_brave source without live network calls.

| File | Engine | Purpose |
|------|--------|---------|
| `brave_bellock_antwerpen.json` | Brave | 8 results: 1 official_website, 3 directory, 2 social, 0 news, 2 other |
| `brave_bakk_brugge.json` | Brave | 5 results: 1 official_website, 2 directory, 1 news, 1 other |
| `brave_no_results.json` | Brave | Empty result set — `web.results = []` |
| `brave_quota_exhausted.json` | Brave | Documents HTTP 403 behaviour (BraveQuotaExhausted) |
| `brave_legal_form_suffix.json` | Brave | Company "Acme BV" matches `acme.be` after BV suffix stripped |
| `brave_ambiguous_name.json` | Brave | Company "Mediapro": both `.com` and `.be` domain are official_website; `.be` wins tie-breaker |
| `ddg_bellock_html.json` | DDG | `ddgs.DDGS.text()` return format — list of `{title, href, body}` |
| `ddg_ratelimit.json` | DDG | Documents RatelimitException behaviour (DdgRateLimitedError) |
