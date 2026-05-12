# Extraction Priorities & Confidence Values

When multiple extraction methods yield a value for the same field, each observation gets its
own confidence level. The transformer stamps observations per these values.

## Phone observations from website

| Source | Confidence |
|--------|-----------|
| JSON-LD `telephone` | 1.00 |
| `href="tel:"` link | 0.85 |
| Regex on visible text | 0.60 |

## Email observations

| Source | Confidence |
|--------|-----------|
| JSON-LD `email` | 1.00 |
| `href="mailto:"` link | 0.85 |
| Regex on text | 0.50 |

## Person (function_holder) observations

| Source | Confidence |
|--------|-----------|
| Microdata `itemtype=Person` | 0.85 |
| Role-keyword adjacency heuristic | 0.55 |

## Website age

| Source | Confidence |
|--------|-----------|
| WHOIS `creation_date` | 1.00 |
| Footer copyright year | 0.70 |
| Wayback CDX first snapshot (deferred) | 0.95 |

## Activity summary

| Source | Confidence |
|--------|-----------|
| `<meta name="description">` | 0.90 |
| `<meta property="og:description">` | 0.85 |
| `<meta name="twitter:description">` | 0.80 |
| First `<p>` in main/article/section | 0.60 |

## Address from JSON-LD

| Source | Confidence |
|--------|-----------|
| JSON-LD `address` | 0.90 |

## Conflict resolution

When multiple observations exist for the same `(kbo_number, field)`:
- The consolidation pass picks the highest-confidence current-best.
- Same confidence → newest `observed_at` wins.
- Cross-source consensus boost: `min(1.0, base * 1.1)` per matching observation from
  a different source (applied in `src/scraper/scoring/`).
