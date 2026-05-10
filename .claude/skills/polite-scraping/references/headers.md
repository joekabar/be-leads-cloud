# User-Agent Pools and Required Headers

## browser-mix

Three realistic desktop UAs. Rotate per session (pick deterministically from session ID).

```
Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36
Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:130.0) Gecko/20100101 Firefox/130.0
Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15
```

Required headers:
```
Accept-Language: nl-BE,nl;q=0.9,fr;q=0.5,en;q=0.3
Accept-Encoding: gzip, deflate, br
DNT: 1
Connection: keep-alive
```

## chrome-only

Three Chrome UAs across OS/version variants. Use for goudengids.be and pagesdor.be — Imperva
flags non-Chrome UAs more aggressively.

```
Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36
Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36
Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36
```

Required headers:
```
Accept-Language: nl-BE,nl;q=0.9,fr;q=0.5,en;q=0.3
Accept-Encoding: gzip, deflate, br
DNT: 1
Connection: keep-alive
Sec-Fetch-Dest: document
Sec-Fetch-Mode: navigate
Sec-Fetch-Site: none
```

## api-client

Single identifying UA. Used for NBB CBSO and Brave Search — they expect API clients, not browsers.

```
be-leads/0.1 (+https://example.invalid)
```

Required headers:
```
Accept: application/json
Accept-Encoding: gzip, deflate, br
```

## identifying

Contact-bearing UA. Use for web.archive.org per their request.

```
be-leads/0.1 (contact@example.invalid)
```

Required headers:
```
Accept-Encoding: gzip, deflate, br
```
