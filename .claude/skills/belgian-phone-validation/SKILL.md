---
name: belgian-phone-validation
description: Validate, normalize, and classify Belgian phone numbers. Converts any reasonable Belgian phone string to a canonical `{e164, raw, type, region, original_carrier}` JSONB shape suitable for observations. Handles the Liège trap (04 9-digit landline vs 04xx 10-digit mobile), mobile prefixes 0455/0456/0460/0465-0468/047x/048x/049x, premium 070/090x, M2M 077, freephone 0800, and historic-carrier mapping (note: number portability since 2002 makes this allocation-only). Use whenever the user normalizes a Belgian phone, parses BIPT prefixes, sees a phone field in any source, or asks whether a number is a mobile/landline/VoIP/premium.
allowed-tools: Read, Edit, Bash(uv run python:*), Bash(uv run pytest:*), Bash(uv run be-leads-validate-phone:*)
---

## 1. When to use

Consult this skill whenever any source module touches a phone field, when data ingestion needs
the canonical JSONB shape, or when a user asks "what city is this number from" / "is this
mobile or landline". All phone normalisation must go through `validate_phone()` — never roll
your own Belgian prefix logic.

## 2. Canonical output shape

Matches the provenance-schema skill's phone JSONB definition exactly:

```json
{"e164": "+3232361306", "raw": "03 236 13 06", "type": "fixed_line", "region": "Antwerp-Sint-Niklaas", "original_carrier": null}
```

`type` is one of: `fixed_line | mobile | premium_rate | toll_free | shared_cost | m2m | voip | unknown`.
`region` is the BIPT-area city/region name for `fixed_line`; `null` for all other types.
`original_carrier` is the BIPT-allocated carrier for `mobile` (Proximus / Orange / Telenet /
BASE / Lycamobile); `null` for all other types. See section 6 for the portability caveat.

## 3. Use phonenumbers first, then refine

`phonenumbers.parse(s, "BE")` performs the initial parse and validity check. If
`is_valid_number()` is false, raise `InvalidPhoneError`. Then classify via the longest-prefix
match in `references/prefixes.tsv`. Belgian-specific refinements (mobile sub-allocation,
premium sub-tier) come from that table, not from reimplemented logic. Only fall back to
`phonenumbers.number_type()` when no TSV prefix matches.

## 4. The Liège trap

04 xxx xx xx (9 digits total, NSN length 8 after stripping trunk 0) is a Liège **landline**.
04xx xx xx xx (10 digits total, NSN length 9) is **mobile** or another service.
Liège landlines NEVER use sub-blocks 046/047/048/049.
Code guard in `phone.py`: `nsn[0] == '4' and len(nsn) == 8 and int(nsn[1:3]) < 55`.
The TSV entry `04 → fixed_line, Liège-Voeren` also covers this via prefix matching, but the
explicit guard prevents edge-case mis-classification as mobile.

## 5. Prefix table

See `references/prefixes.tsv`. Columns: `prefix | length | kind | region_or_carrier | notes`.
`prefix` is in national format with trunk prefix `0` (e.g. `047`, `0465`, `02`).
`region_or_carrier` is `—` for special services (toll_free, shared_cost, premium, m2m) — these
become `None` in the output. Longest-prefix wins: `0467` beats `04`. Refresh quarterly from
BIPT (see `references/numbering-plan-rules.md` for the source URL).

## 6. Portability caveat

Belgian number portability has been active since 2002. The `original_carrier` field reflects
**historical BIPT allocation only** — it is NOT the current operator. Never say "this number
IS on carrier X"; always say "originally allocated to X". For current carrier lookup, a paid
API (e.g. Numverify, Twilio Lookup) would be required — that is out of scope.

## 7. CLI

Quick dev/debug test:

```bash
uv run be-leads-validate-phone "03 236 13 06"   # fixed_line, Antwerp-Sint-Niklaas
uv run be-leads-validate-phone "0474 12 34 56"  # mobile, Proximus
uv run be-leads-validate-phone "04 220 11 22"   # fixed_line, Liège-Voeren (Liège trap)
uv run be-leads-validate-phone "0467 12 34 56"  # mobile, Telenet
```

Each prints one JSON line to stdout. Errors print to stderr and exit 1.
