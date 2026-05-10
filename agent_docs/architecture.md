# Architecture

> TODO: Expand this document as modules are added in subsequent prompts.

## Overview

be-leads is an async Python scraper pipeline that builds a Belgian B2B company database from
multiple authoritative and discovery sources. All scraped facts land in a single Postgres 16
database with full provenance. A Streamlit UI serves sector × city queries.

## Module layout

```
src/scraper/
├── lib/          # cross-cutting helpers
│   ├── http/     # shared httpx AsyncClient pool with polite rate limiting
│   ├── polite.py # per-host rate limiter, robots.txt cache, Retry-After handling
│   ├── provenance.py  # observation builders, run_id management
│   ├── validators.py  # KBO checksum (python-stdnum), phone (phonenumbers)
│   ├── errors.py      # typed exception hierarchy
│   └── logging.py     # structlog with contextvars binding
├── db/           # asyncpg pool, repository pattern, Pydantic row models, migrations
├── sources/      # one sub-directory per source
│   └── <name>/
│       ├── fetcher.py   # async HTTP / file download
│       ├── parser.py    # HTML/JSON/XBRL → domain objects
│       └── __init__.py
├── pipeline/     # orchestration: scheduler, enrichment fan-out, consolidation view refresh
├── scoring/      # confidence scoring, deduplication heuristics
└── ui/           # Streamlit app (asyncio.run at the boundary)
```

## Key architectural decisions

### Postgres-only storage
All data — job queue, observations, canonical facts — lives in a single Postgres 16 instance.
See `docs/decisions/0001-postgres-only.md`.

### Async-everywhere boundary
Every function that performs I/O MUST be `async def`. Synchronous I/O in `sources/`, `db/`,
and `pipeline/` is forbidden and will be caught by the ASYNC ruff ruleset. The Streamlit UI
is the only permitted caller of `asyncio.run()`.

### Observations pattern (append-only provenance)
No `UPDATE` on canonical fact tables. Every scraped value becomes one row in `observations`.
A materialised view `companies_current` computes the current best value per field per company.
See `agent_docs/data-model.md`.

### Dependency injection
`httpx.AsyncClient` and `asyncpg.Pool` are passed explicitly to every function that needs them.
No module-level globals or singletons — this keeps the code testable without monkeypatching.

### Fan-out with TaskGroup
Concurrent scraping uses `asyncio.TaskGroup` (Python 3.11+). Bare `asyncio.create_task` is
forbidden to ensure structured concurrency and clean error propagation.
