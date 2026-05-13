# Query Templates

## Template 1 (default): name + city

```
Brave: "{name}" {city}    country=BE  search_lang={nl|fr}
DDG:   "{name}" {city}    region=be-{nl|fr}
```

Used in all batch runs. The name is always double-quoted so Brave treats it as a phrase.
City is unquoted. Legal-form suffixes are stripped from the quoted name before querying.

**Example:** `"Bellock" Antwerpen`

## Template 2 (on-demand): name + city + site:.be

```
Brave: "{name}" {city} site:.be
DDG:   "{name}" {city} site:.be
```

Use when Template 1 returns 0 results, or when you specifically need the official `.be` presence.
Costs one extra Brave query — only run on-demand, not in batch.

## Template 3 (on-demand): name + phone

```
Brave: "{name}" "{phone_e164_no_spaces}"
DDG:   "{name}" "{phone_pretty}"
```

Use to validate that a specific phone number is associated with the company name on the open web.
Strong evidence when ≥2 results from independent domains contain both name and phone.
Phone is passed as E.164 without spaces for Brave (exact match); formatted for DDG.

## Name normalisation in queries

- Always wrap the company name in double quotes: `"Bellock"` (Brave respects phrase queries)
- Strip legal-form suffixes from the quoted name: `"Acme"` not `"Acme BV"`
- City is unquoted: `Antwerpen` not `"Antwerpen"`

## Query budgeting

Brave free tier: 2 000 queries / month ≈ 65 / day average.

| Run type | Queries / company | Companies / day |
|----------|------------------|-----------------|
| Batch (template 1 only) | 1.0 | 65 |
| With template-2 fallback | 1.5 | ~43 |
| Full (all 3 templates) | 3.0 | ~21 |

For one sector × one city run of ~50 companies, budget 50–75 Brave queries.
DDG fills the gap when Brave quota is exhausted (~100–200 DDG queries/day practical ceiling).

## Language detection

Detect NL vs FR from the source that produced the company record:
- `goudengids` → `nl` (use `be-nl` for DDG, `search_lang=nl` for Brave)
- `pagesdor` → `fr` (use `be-fr` for DDG, `search_lang=fr` for Brave)
- Unknown → default to `nl`
