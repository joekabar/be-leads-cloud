# HTTP Status-Code Playbook

| Code | Action | Reason |
|---|---|---|
| 200 | proceed | success |
| 301/302/303/307/308 | follow (max 5 hops) | normal redirects |
| 304 | use cache | not modified |
| 400 | fail (no retry) | client error, won't fix on retry |
| 401 | fail (no retry) | auth error — fix credentials |
| 403 | stop, escalate | likely WAF block, retrying makes it worse |
| 404 | fail (no retry) | resource doesn't exist |
| 410 | fail (no retry) | resource permanently gone |
| 429 | retry with backoff, honour Retry-After | rate limit |
| 500 | retry once | transient server error |
| 502/504 | retry with backoff | gateway / timeout |
| 503 | retry with backoff, honour Retry-After | service unavailable |
