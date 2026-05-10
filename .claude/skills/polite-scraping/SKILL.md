---
name: polite-scraping
description: Apply rate limiting, exponential backoff with jitter, and per-host concurrency limits to all outbound HTTP. Defines token-bucket defaults per host (goudengids, kbopub, NBB CBSO, generic websites) and the rules for when to escalate from httpx to Playwright. Use whenever the user adds an HTTP call, sees 429/503/403 errors, asks about rate limits, modifies anything in src/scraper/lib/http/, or builds a new source module under src/scraper/sources/. Always consult the per-host TOML before guessing a rate.
allowed-tools: Read, Edit, Bash(uv run python:*), Bash(uv run pytest:*)
---

## When to use

Consult this skill whenever you write or review an HTTP call in any source module, modify
`src/scraper/lib/http/`, tune rate limits, investigate 429/503/403 responses, or onboard a
new host. The per-host TOML is the single source of truth for rates and concurrency — never
hardcode values in source modules.

## Per-host defaults

See `references/per-host.toml` for full config. Quick reference:

| Host | rps | concurrency | notes |
|---|---|---|---|
| goudengids.be | 0.3 | 1 | Imperva — bursts ban IP |
| pagesdor.be | 0.3 | 1 | same parent as goudengids |
| kbopub.economie.fgov.be | 0.25 | 1 | used for KBO numbers and function holders |
| ws.cbso.nbb.be | 1.0 | 2 | requires registered API key (free) |
| api.search.brave.com | 1.0 | 1 | free tier 2k/month |
| duckduckgo.com | 0.3 | 1 | even this rate-limits in 2026 |
| web.archive.org (CDX) | 0.8 | 1 | 60 req/min hard ceiling |
| default | 0.5 | 2 | per host, distinct hosts run in parallel |

## Token bucket

`src/scraper/lib/http/limiter.py` implements an async per-host token bucket. `acquire(host)`
is async and blocks until a slot is free. Hosts are keyed on URL netloc. Each host also has
an `asyncio.Semaphore(concurrency)` that caps simultaneous in-flight requests. Call
`load_from_toml(path)` to build a `HostLimiter` from `references/per-host.toml`.

## Backoff with jitter

Formula: `delay = min(60, base * 2**attempt) + uniform(0, jitter)` with `base=1.0`,
`jitter=0.3`, `max_attempts=5`. Retry only on 429/503/504. Honour `Retry-After` (both
seconds-int and HTTP-date forms). Never retry on 403 — escalate instead.
See `src/scraper/lib/http/retry.py`.

## Status-code playbook

See `references/status-codes.md` for the full table.

## Escalate-to-Playwright triggers

1. HTML response <500 bytes containing `incapsula|imperva|captcha|toegang geweigerd|pardon our interruption`
2. 3 consecutive 403s on the same host within 10 minutes
3. Detail page known to be JS-rendered with no XHR alternative
