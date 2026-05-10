# ADR 0001 — Postgres-only storage

**Status:** Accepted
**Date:** 2026-05-10

## Context

An earlier prototype stored the crawler job queue in SQLite (for operational simplicity) while
keeping observations in Postgres. This created two databases to operate, monitor, and back up.
Cross-database transactional guarantees were impossible, and SQLite WAL mode caused contention
under concurrent workers pulling jobs from the queue.

## Decision

Drop SQLite entirely. Use Postgres 16 exclusively for all persistent storage: job queue,
observations, canonical company facts, pipeline run audit log, and configuration tables.

Worker pop uses `SELECT ... FOR UPDATE SKIP LOCKED` on the `jobs` table — a Postgres-native
pattern that provides correct at-most-once delivery under concurrent async workers without
requiring a separate message broker (Redis, RabbitMQ, etc.).

## Consequences

**Positive:**
- Single database to operate, monitor, and back up.
- `asyncpg` is the only DB driver — no `aiosqlite` or dual-driver complexity.
- `SELECT ... FOR UPDATE SKIP LOCKED` gives correct job semantics with zero extra infrastructure.
- Postgres JSONB handles flexible observation values without a schema migration per new field type.
- One connection pool shared across the pipeline simplifies resource management.

**Negative / trade-offs:**
- Requires a running Postgres instance in local dev. Covered by `docker compose up -d pg`.
- Async-only I/O path — no sync ORM (Django ORM, SQLAlchemy sync) in scraper code.
- No cross-database transactions (not needed for this project).
- Heavier than SQLite for true one-off local scripts, but we don't have that use case.
