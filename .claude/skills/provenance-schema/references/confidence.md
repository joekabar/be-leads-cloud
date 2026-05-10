# Confidence priors

Per-source starting confidence values. These are priors — adjust with recency decay and
consensus boost before storing.

## Prior table

| Source         | phone | KBO#  | address | founding | website | financials | persons |
|----------------|-------|-------|---------|----------|---------|------------|---------|
| kbo_dump       | 0.95  | 1.00  | 0.95    | 1.00     | 0.85    | —          | —       |
| kbopub         | 0.85  | 1.00  | 0.95    | 1.00     | 0.80    | —          | 0.95    |
| nbb_authentic  | —     | 1.00  | —       | —        | —       | 1.00       | —       |
| goudengids     | 0.85  | 0.85  | 0.80    | 0.85     | 0.85    | —          | —       |
| pagesdor       | 0.85  | 0.85  | 0.80    | 0.85     | 0.85    | —          | —       |
| website        | 0.75  | 0.50  | 0.70    | —        | 1.00    | —          | 0.65    |
| ddg            | 0.50  | —     | 0.50    | —        | 0.55    | —          | —       |
| brave          | 0.50  | —     | 0.50    | —        | 0.55    | —          | —       |
| wayback        | —     | —     | —       | —        | —       | —          | —       |
| manual         | 1.00  | 1.00  | 1.00    | 1.00     | 1.00    | 1.00       | 1.00    |

`—` means the source does not provide this field type; do not create observations for it.

## Adjustment formulas

### Recency decay

```python
import math
days = (now - observed_at).days
decayed = prior * (0.99 ** days)
confidence = max(0.30, min(1.00, decayed))
```

Applied at read time in `src/scraper/scoring/` (pipeline prompt). Not applied at insert time.

### Consensus boost

For each additional observation from a *different* source that matches the same
`(kbo_number, field, value)`:

```python
confidence = min(1.0, confidence * 1.1)
```

Multiple matching sources each contribute one boost (capped at 1.0).

### Worked example

Company 0439401387, field `phone`, value `{"e164": "+3232361306", ...}`:

1. kbo_dump observation, 30 days old: `0.95 * 0.99^30 = 0.704`
2. goudengids observation (same value), 5 days old: `0.85 * 0.99^5 = 0.808`
3. Consensus boost on kbo_dump (goudengids agrees): `0.704 * 1.1 = 0.774`
4. Final winner: goudengids at 0.808 (higher confidence after decay + boost)
