# NBB CBSO filing types

## MICRO

Introduced by Belgian law in 2016. Applies to entities meeting **all** of:
- Balance sheet total ≤ €350 000
- Turnover ≤ €700 000
- Average FTE ≤ 10

**Key behaviours:**
- Only an abbreviated balance sheet is legally required.
- Revenue (`code_70`) is **optional** — many MICRO entities set it to null.
- `code_9904` (profit/loss) and `code_9087` (employees) are typically present.
- `modelType = "MICRO"` in the `/references` response.

## ABBREVIATED (verkort / abrégé)

Applies to small and medium entities below the large-company thresholds
(two of three: balance sheet ≤ €4.5M, turnover ≤ €9M, FTE ≤ 50).

**Key behaviours:**
- Revenue (`code_70`) is **required**.
- All three key fields (revenue, profit, employees) reliably populated.
- `modelType = "ABBREVIATED"`.

## FULL (volledig / complet)

Applies to large companies and listed entities (exceed two of three thresholds above).

**Key behaviours:**
- Full schema — `code_700` (preferred revenue field) and `code_70` may both appear.
- Revenue: use `code_700` if present, otherwise `code_70`.
- All fields reliably present.
- `modelType = "FULL"`.

## CONSOLIDATED

Consolidated accounts filed by parent companies covering the whole group.

**Key behaviours:**
- Revenue and employee count represent the entire group, not just the legal entity.
- For single-entity analysis, prefer the entity's own (non-consolidated) filing.
- `modelType = "CONSOLIDATED"`.
- Out of scope for the current ingester — these filings are not excluded but the data
  should be interpreted at group level only.

## Summary table

| Model type   | Revenue present? | Notes                                      |
|--------------|------------------|--------------------------------------------|
| MICRO        | Often null       | Check null before emitting                 |
| ABBREVIATED  | Yes              | Reliable                                   |
| FULL         | Yes (code_700)   | Prefer code_700 over code_70               |
| CONSOLIDATED | Yes              | Group-level — use with caution             |
| OTHER        | Unknown          | Unexpected API value — handled gracefully  |
