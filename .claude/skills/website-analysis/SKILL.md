---
name: website-analysis
description: Analyze a company's own website to extract structured business data — phones, emails, contact persons, activity summary, NACE-classification hints, opening hours, and website age. Two-step process: fetch the homepage, then attempt to find and fetch a contact/team page for richer person data. Uses JSON-LD structured data when present; falls back to heuristics for older sites. Use whenever the user mentions website enrichment, company homepage scraping, contact persons, activity summary, website age, JSON-LD, schema.org, or "scrape the company's own site".
allowed-tools: Read, Edit, Bash, WebFetch, Bash(uv run python:*), Bash(uv run pytest:*), Bash(uv run be-leads-enrich-website:*)
---

## When to use

Any per-company website enrichment. Called by the pipeline fan-out after KBO data and
goudengids discovery have populated website URLs in `companies_current`.

## Three extraction tiers, in confidence order

1. **JSON-LD** `<script type="application/ld+json">`: confidence 1.00.
   Look for `@type` of `LocalBusiness`, `Organization`, `ProfessionalService`, `Store`,
   `Restaurant`, or any schema.org subtype of those. Map: `telephone`, `email`, `address`,
   `openingHours`, `description`, `founder`/`employee` (when typed `Person`).

2. **OpenGraph + meta tags**: confidence 0.85.
   `og:description`, `description`, `og:site_name`.

3. **HTML heuristics**: confidence 0.50–0.75.
   Phone numbers from `<a href="tel:">` (0.85) or text-pattern scan (0.60);
   persons from `itemtype="Person"` microdata (0.85) OR by role-keyword adjacency (0.55);
   footer year for website-age fallback (0.70).

## Contact-page discovery

Try in order: `/contact`, `/contact-us`, `/team`, `/over-ons`, `/about`, `/medewerkers`,
`/wie-zijn-we`, `/notre-equipe`. First `HEAD` that returns 200 wins.
If none of the well-known paths work, scan homepage `<a href>` tags for case-insensitive
match on `contact|team|over-ons|about|medewerkers|wie-zijn-we|notre-equipe|nous-contacter`.

## Website age

1. WHOIS (`creation_date`) — confidence 1.00. Wrapped in `asyncio.to_thread`; all exceptions caught.
2. Footer year (`©\s*(\d{4})` or `\b(20\d{2})\b`) — confidence 0.70.
3. Wayback CDX — confidence 0.95. **Deferred (TODO)**. Not implemented this prompt.

## Activity summary

First non-empty match: `<meta name="description">`, `<meta property="og:description">`,
`<meta name="twitter:description">`, first `<p>` > 60 chars inside `<main>`/`<article>`/`<section>`.
Truncate to 300 characters.

## Contact persons

JSONB shape: `{name, role, source}`. `source` ∈ `{"microdata", "heuristic"}`.
Microdata first (`itemtype` containing `Person`), then role-keyword adjacency heuristic.
Max 4 persons per company.

## Phones from website

Always pipe through `validate_phone()`. Skip on `InvalidPhoneError`. Multiple phones → separate observations.

## Rate

Default polite-scraping rate (0.5 rps per host). Distinct company websites = distinct hosts,
so `concurrent_companies=15` across companies is fine — the limiter is per-host.
Do NOT set a custom per-company host limit for website enrichment; the default handles it.
