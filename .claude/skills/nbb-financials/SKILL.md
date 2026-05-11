---
name: nbb-financials
description: Fetch annual financial data (revenue, profit, employees by year) from the NBB CBSO Authentic Data REST API. Free product; one subscription key per developer; identifies callers via NBB-CBSO-Subscription-Key + per-request UUID. Use whenever the user mentions revenue, omzet, chiffre d'affaires, profit, EBIT, employees by year, balansen, comptes annuels, NBB filings, annual accounts, CBSO, BNB, or financial enrichment. Always uses the /authentic/legalEntity/{KBO}/references endpoint first, then /accountingData per reference.
allowed-tools: Read, Edit, Bash, WebFetch(domain:ws.cbso.nbb.be), WebFetch(domain:consult.cbso.nbb.be), Bash(uv run python:*), Bash(uv run pytest:*), Bash(uv run be-leads-fetch-nbb:*)
---

## When to use

Any financial enrichment task: fetching revenue, profit/loss, or headcount data by fiscal year
for a Belgian legal entity. The NBB CBSO Authentic Data API is the authoritative source — it
contains all annual accounts filed with the National Bank since 1989.

## Two-call dance

Always call `/references` first, then `/accountingData` for each reference you want.

```
GET /authentic/legalEntity/{kbo}/references
→ list of filing metadata (reference number, exercise dates, model type)

GET /authentic/legalEntity/{kbo}/references/{referenceNumber}/accountingData
→ parsed key figures for that filing
```

Never fetch `/accountingData` without first fetching `/references` — the reference number
from the first call is the path parameter for the second.

## Auth

Two headers required on every request:

| Header                      | Value                                    |
|-----------------------------|------------------------------------------|
| `NBB-CBSO-Subscription-Key` | your subscription key from api-portal    |
| `X-Request-Id`              | `str(uuid.uuid4())` — new per request    |

The key comes from the API Management portal at `https://api-portal.nbb.be` after:
1. Creating a free account and verifying email.
2. Subscribing to the product **"Authentic Data Query"** (FREE tier).
3. Copying the Subscription Key from "Profile → Subscriptions."

See `agent_docs/runbook.md` for the full registration walkthrough.

## Rate

`1.0 rps` with `concurrency 2` — enforced via `ws.cbso.nbb.be` entry in
`.claude/skills/polite-scraping/references/per-host.toml`. Do not exceed. The portal
has soft limits documented as "fair use." A batch of 1 000 KBOs takes ~17 min wall-clock
(average 2 calls per KBO: 1 references + 1 accountingData).

## Field mapping

See `references/field-mapping.md` for the full table. Summary:

| JSON key    | Canonical field   | Units     | Notes                                  |
|-------------|-------------------|-----------|----------------------------------------|
| `code_700`  | `revenue_YYYY`    | EUR (int) | Full schema — **preferred**            |
| `code_70`   | `revenue_YYYY`    | EUR (int) | Abbreviated schema — fallback          |
| `code_9904` | `profit_YYYY`     | EUR (int) | Result for the year after tax          |
| `code_9087` | `employees_YYYY`  | FTE (float)| Average FTE; null for MICRO entities  |

YYYY = `exercise_end.year` from the `/references` response.

## Filing types

See `references/filing-types.md`. Quick summary:

- **MICRO** — revenue optional/null. Only abbreviated balance sheet required.
- **ABBREVIATED** — revenue required. Mid-size entities.
- **FULL** — large or listed. All fields present.
- **CONSOLIDATED** — parent companies. Use the parent's own (non-consolidated) filing
  for single-entity data; consolidated is downstream scope.

## Idempotency

24-hour skip per KBO: if any `nbb_authentic` observation exists in the DB within
`skip_recent_hours` (default 24), the KBO is skipped. Pass `--skip-recent-hours 0`
to force a re-fetch.

## NULL handling

**Never emit an observation whose value is null.** MICRO entities often don't disclose
revenue. `parse_accounting_data` returns `None` for missing/null fields; `filing_to_observations`
skips those fields entirely. "Not reported" ≠ "reported as zero" — conflating them
poisons analytics.

## Error handling

| Status | Behaviour                                                    |
|--------|--------------------------------------------------------------|
| 401    | `NbbAuthError` — fail fast, abort the batch                  |
| 404    | `NbbNotFoundError` — count in report, skip, continue batch   |
| 429    | Retry via `PoliteClient` / `request_with_retry` (Retry-After)|
| 503    | Retry via `PoliteClient` / `request_with_retry`              |
| 403    | `BlockedError` — do not retry                                |
