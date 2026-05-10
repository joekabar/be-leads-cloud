# Belgian Numbering Plan — Quick Reference

**Country code:** +32  **Trunk prefix:** 0  **Total length:** 9 or 10 digits (with trunk 0).

## Format examples

| Category | National format | Total digits |
|---|---|---|
| Brussels landline | 02 xxx xx xx | 9 |
| Regional landline | 0xx xx xx xx | 9 |
| Mobile | 04xx xx xx xx | 10 |
| Freephone | 0800 xx xxx | 9 |
| Premium rate | 090x xx xxx | 9 |
| M2M | 077 xx xx xxx | 10 |

## Liège disambiguation

`04 xxx xx xx` (9 digits total, NSN length 8) → **Liège landline** (area code 4).
`04xx xx xx xx` (10 digits total, NSN length 9) → **mobile** or special service.

Liège landlines NEVER use sub-blocks starting with 046, 047, 048, or 049; those are mobile
allocations that happen to share the `04` prefix. The 9-vs-10 digit distinction is definitive.

Code guard: `nsn[0] == '4' and len(nsn) == 8 and int(nsn[1:3]) < 55`.

## Mobile sub-allocation: longest prefix wins

Prefixes in `prefixes.tsv` are matched against the national digits (trunk 0 + NSN) using
longest-prefix matching. `0467` (4 chars, Telenet) wins over `04` (2 chars, Liège) for a
10-digit number. `047` (3 chars, Proximus) wins over `04` for 0474/0475/0476/0478/0479.

## Special-service note

The `045x` sub-block is administratively a premium service distinct from mobile `0455`/`0456`
allocations. All 04xx 10-digit numbers default to `mobile` unless a specific prefix in
`prefixes.tsv` overrides this with `kind=premium_rate`. This is a known limitation — update
the TSV if BIPT adds explicit 045x allocations.

## BIPT source

Download the latest allocated-numbers database from:
https://www.bipt.be/operators/publication/database-with-reserved-and-allocated-numbers

Refresh `prefixes.tsv` quarterly. Preserve column order: `prefix | length | kind |
region_or_carrier | notes`. Run `uv run pytest tests/unit/lib/validators/ -q` after updating.
