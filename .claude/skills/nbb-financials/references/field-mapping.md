# NBB CBSO field mapping — JSON key → canonical observation field

## Revenue

| JSON key   | Source      | Precedence | Units     |
|------------|-------------|------------|-----------|
| `code_700` | Full schema | **First**  | EUR (int) |
| `code_70`  | Abbreviated | Fallback   | EUR (int) |

**Rule:** if `code_700` is present and non-null, use it. Otherwise fall back to `code_70`.
If both are absent or null, `revenue = None` — do not emit the observation.

`code_700` appears in FULL filings; `code_70` in ABBREVIATED and MICRO.
MICRO entities may have `code_70 = null` — legally optional.

## Profit / Loss

| JSON key   | Field name    | Units     |
|------------|---------------|-----------|
| `code_9904`| `profit_YYYY` | EUR (int) |

"Te bestemmen winst (verlies) van het boekjaar" / "Bénéfice (perte) à affecter de l'exercice".
Negative values are losses — store as-is (negative integer).

## Employees

| JSON key   | Field name       | Units       | Notes                              |
|------------|------------------|-------------|------------------------------------|
| `code_9087`| `employees_YYYY` | FTE (float) | Average FTE over the exercise year |
| `code_1000`| _not used_       | EUR (int)   | Total staff costs — NOT a headcount|

`code_9087` is the average FTE count (e.g. `4.0`, `12.5`). It is absent or null in
many MICRO filings. `code_1000` is the payroll amount in EUR — never use it as employee count.

## Field name convention

```
{metric}_{exercise_year}
```

where `exercise_year = exercise_end.year` from the `/references` response.

Example: a filing with `exerciseEnd = "2023-12-31"` produces:
- `revenue_2023`
- `profit_2023`
- `employees_2023`

## JSONB value shapes

Revenue and profit:
```json
{"value": 340000, "currency": "EUR", "filing_ref": "2024-00000148", "model_type": "ABBREVIATED"}
```

Employees:
```json
{"value": 4.0, "filing_ref": "2024-00000148", "model_type": "ABBREVIATED"}
```

No `currency` on employees — FTE is dimensionless.

## cross-check field

`code_99001` is the exercise end date as a string. It should match `exerciseEnd` from
the `/references` response. Used as a sanity check only — not stored as an observation.
