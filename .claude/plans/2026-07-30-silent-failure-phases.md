# Plan — stop the nightly pipeline from failing invisibly (2026-07-30)

## Why

The 2026-07-30 nightly run *looked* clean: `batch_finished` with no error, 139 placeholders
resolved. Two failures were hidden inside it.

1. **Phase F produced nothing, three nights running.** `phase_f_started` at 03:29:12, no
   `phase_f_finished` line at all, `prospect_scores=0` in the summary — after burning 7m19s.
   Before this plan's diagnostic run, `max(prospect_scores.computed_at)` was
   **2026-07-27 13:29**. Scores driving the export ranking were three days stale and nothing
   said so.
2. **`nightly_scrape.ps1` reported failure on a successful run.** `logs/nightly_scrape.log`
   has `START` and `SCRAPE` for the 02:30 run but no `END`, while the batch log shows a clean
   `batch_finished`. Task Scheduler recorded `LastTaskResult = 1`.

Both are the same class of bug as `e7d3d77` (`$PSScriptRoot` in a `param()` default): the
failure path is silent, so the run reports success.

## Evidence gathered before planning

- **Phase F is not inherently broken.** Reproduced standalone against the live `leads` DB:
  8,743,514 rows fetched (28.6 s), 1,959,773 KBOs grouped (13.1 s), scored (16.8 s),
  392 upsert batches, slowest batch **0.47 s**, total **1.9 min**. No timeout, no
  `ScoringTimeoutError`, and **zero** non-object JSONB values (the `dict(row["value"])` at
  `prospect.py:135` had been a suspect). The run also repaired the staleness:
  `prospect_scores` is now 1,959,777 rows at 2026-07-30 17:15Z.
- **So the production exception is still unidentified**, and it cannot be identified from the
  logs because `batch.py:802` discards it. Leading hypothesis is `MemoryError`: production
  holds 8.7M rows plus 1.96M dicts alongside Playwright/Chromium, the earlier incident in
  `test_prospect_upsert.py` recorded 4.3 GB resident, and `suppress(Exception)` catches
  `MemoryError`. **The fix is what produces the diagnosis** — tonight's run will log it.
- **Defect 2's mechanism is confirmed, not inferred.** A standalone PS 5.1 probe: a native
  command that exits 0 while writing to stderr, redirected with `*>>` under
  `$ErrorActionPreference = 'Stop'`, raises `NativeCommandError`, terminates the script before
  its `END` line, and exits 1. Identical signature to the real log.
- **Two sectors can never succeed.** `afvalverwerkingsindustrie` and `automobielfabrieken`
  logged `goudengids_sector_not_indexed`; `sectors.toml:523` already carries
  `goudengids_sector_not_indexed = true`. They yield 0 observations, so
  `completed_sectors()` (`sector_queue.py:41`) never marks them done. They sit at the head of
  the pending queue (82 of 103 sectors pending) and will consume 2 of tonight's slots forever.

## Task 1 — phases D/E/F must report failure (primary)

`batch.py` is internally inconsistent: phases A, C1, C2 and G use
`try/except` → `report.sources_failed[...]` + `log.error(...)`. Only D/E/F
(`:782`, `:787`, `:795`, `:802`) use `with suppress(Exception)`.

- Tests first, in `tests/unit/pipeline/test_batch.py`: for each of the matview refresh,
  consolidation and prospect-scoring steps, a raising dependency must (a) leave the rest of
  the batch running, (b) land in `report.sources_failed`, (c) emit a `log.error` carrying the
  exception type and message.
- Then replace the four `with suppress(Exception)` blocks with the file's existing
  `try/except` pattern. Failure stays non-fatal — a blocked scrape should not lose the night's
  consolidation — but it stops being invisible.
- Include the exception type, not just `str(exc)`: a bare `MemoryError` stringifies to `''`.
- `batch_finished` currently logs only counts. Add `failed=sorted(report.sources_failed)` so a
  partial run is visible in the one line an operator actually reads.
- Drop the now-unused `from contextlib import suppress` import (`batch.py:20`) if nothing else
  uses it.

Out of scope, noted for later: Phase F rescores all 1.96M companies after a run that touched
~200 placeholders. Scoping it to KBOs touched by the run would cut it from ~2 min to seconds
and shrink the memory spike that is the prime suspect above. Separate change, separate tests.

## Task 2 — `nightly_scrape.ps1` must always write its own summary

- Wrap the native invocation at line 72 so a stderr-triggered `NativeCommandError` cannot skip
  lines 73–85: set `$ErrorActionPreference = 'Continue'` for the duration of the call (restore
  after), and capture `$LASTEXITCODE` in a `finally`.
- `structlog` writes every log line to stderr, so this fires on **every** run, not on failures
  only — the script has never once written its `END` line.
- Verify by running the script under `powershell.exe -NoProfile -File` (the scheduler's exact
  invocation) and confirming `END exit=... sectors_done=... blocks=...` appears in
  `logs/nightly_scrape.log`.

## Task 3 — not-indexed sectors must leave the rotation

- Test first: a sector flagged `goudengids_sector_not_indexed` is excluded from
  `select_pending_sectors` output even though it has no productive run.
- Reuse the existing flag via `_resolve_goudengids_slug`-style lookup rather than adding a
  second source of truth. Keep the blocked-sector retry behaviour exactly as is — the
  docstring's reasoning is correct for blocks, it just conflates "blocked" with "nonexistent".

## Task 4 — lower the nightly slice to 10

The WAF blocked after 10 productive sectors / ~44 min of Phase B. Re-register
`be-leads-nightly-scrape` with `-Limit 10`. Do this after Task 3, so the 10 slots are 10 real
sectors rather than 8 plus two that can never succeed.

## Deferred

`phase_c2_failed error='No results found.'` — ddg_brave contributed nothing. Needs live
network and a separate investigation; Task 1 is a prerequisite anyway, since right now a C2
failure is at least logged but its effect on the run is not summarised.

## Definition of done

Per `CLAUDE.md`: tests written first and failing; `ruff check`, `ruff format --check`,
`mypy --strict` clean on changed files; `uv run pytest --cov=src/scraper --cov-fail-under=85`
passing; CHANGELOG entry under `## [Unreleased]`.
