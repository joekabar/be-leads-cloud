# NBB CBSO Authentic Data API — specification

## Base URL

```
https://ws.cbso.nbb.be
```

## Authentication

Every request requires two headers:

```http
NBB-CBSO-Subscription-Key: <your-key>
X-Request-Id: <uuid4-per-request>
```

Obtain a key at `https://api-portal.nbb.be` → subscribe to "Authentic Data Query" (FREE).

## Endpoints

### GET /authentic/legalEntity/{enterpriseNumber}/references

Returns metadata for all annual account filings for one entity.

**Path parameter:** `enterpriseNumber` — 10-digit KBO number without dots or spaces
(e.g. `0439401387`). Use `stdnum.be.vat.compact(kbo)` to normalise.

**Example request:**
```
GET https://ws.cbso.nbb.be/authentic/legalEntity/0439401387/references
NBB-CBSO-Subscription-Key: abc123...
X-Request-Id: f47ac10b-58cc-4372-a567-0e02b2c3d479
```

**Example response:**
```json
{
  "references": [
    {
      "referenceNumber": "2024-00000148",
      "depositDate": "2024-09-12",
      "exerciseStart": "2023-01-01",
      "exerciseEnd": "2023-12-31",
      "modelType": "ABBREVIATED",
      "language": "NL",
      "depositType": "DEPOSIT",
      "filingMethod": "STRUCTURED"
    }
  ]
}
```

**Empty case:** `{"references": []}` — entity exists but never filed. Not an error.

### GET /authentic/legalEntity/{enterpriseNumber}/references/{referenceNumber}/accountingData

Returns parsed key figures for one filing.

**Path parameters:**
- `enterpriseNumber` — same as above
- `referenceNumber` — from `/references` response (e.g. `2024-00000148`)

**Example request:**
```
GET https://ws.cbso.nbb.be/authentic/legalEntity/0439401387/references/2024-00000148/accountingData
NBB-CBSO-Subscription-Key: abc123...
X-Request-Id: a1b2c3d4-0000-4000-8000-000000000001
```

**Example response (ABBREVIATED):**
```json
{
  "code_70": 340000,
  "code_9904": 30326,
  "code_9087": 4.0,
  "code_99001": "2023-12-31"
}
```

**MICRO entity (revenue null):**
```json
{
  "code_70": null,
  "code_9904": 8500,
  "code_9087": 1.5,
  "code_99001": "2023-12-31"
}
```

## Error responses

| Status | Meaning                                     | Action in client                |
|--------|---------------------------------------------|---------------------------------|
| 200    | Success                                     | Parse response                  |
| 401    | Invalid or missing subscription key         | Raise `NbbAuthError`, abort     |
| 403    | Key suspended / IP blocked                  | Raise `BlockedError`, abort     |
| 404    | KBO not registered in CBE or never filed    | Raise `NbbNotFoundError`, skip  |
| 429    | Rate limited                                | Honour `Retry-After`, retry     |
| 503    | NBB service temporarily unavailable         | Retry with backoff              |

Note: 401 and 404 arrive as `TerminalServerError` from `request_with_retry` (the retry
layer does not know about NBB-specific semantics). `NbbClient` catches `TerminalServerError`
and re-raises the appropriate typed error.
