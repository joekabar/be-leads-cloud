# NBB CBSO Authentic Data — golden fixtures

Static JSON fixtures for unit and integration tests. Hand-constructed to match the
`/authentic/legalEntity/{kbo}/references` and `.../accountingData` response shapes.

## KBOs used

| File prefix      | Company        | Notes                                           |
|------------------|----------------|-------------------------------------------------|
| `0439401387`     | Bellock        | 3 ABBREVIATED filings (2021, 2022, 2023)        |
| `0502699332`     | (MICRO entity) | 1 MICRO filing, revenue null (not disclosed)    |
| `9999999991`     | (never filed)  | Empty references — parser unit test only        |
| `0212037309`     | (abbrev/no-emp)| 1 ABBREVIATED filing, employees null            |

## Naming convention

- `{kbo}_references.json` / `{kbo}_references_single.json` — `/references` endpoint response
- `{kbo}_accounting_{ref}.json` — `/accountingData` endpoint response for that reference
- `{kbo}_references_empty.json` — `/references` returning `{"references": []}`

## Field mapping

| JSON key    | Field           | Notes                                 |
|-------------|-----------------|---------------------------------------|
| `code_700`  | revenue (full)  | Preferred over code_70 when present   |
| `code_70`   | revenue (abbr)  | Fallback when code_700 absent         |
| `code_9904` | profit_loss     | Result after tax                      |
| `code_9087` | employees_fte   | Average FTE; null = not disclosed     |
| `code_99001`| exercise_end    | Cross-check with /references metadata |
