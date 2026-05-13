# Bootstrap Prompt 1 — Scaffold the `be-leads` Repository

> **How to use:** open a terminal in an empty directory you've named `be-leads/`, run `claude`, and paste everything below the `=== PROMPT ===` line as your first message. Claude Code will produce the repo scaffold and stop. Review the output, commit, then move to prompt 2.

---

=== PROMPT ===

You are bootstrapping a new Python project called `be-leads`. Read this entire prompt before doing anything. The current working directory is empty and is the project root.

## Project context

`be-leads` is a high-volume, recurring scraper that builds a Belgian B2B company database. Sources will be added in subsequent prompts; right now you are only creating the scaffold. Stack: Python 3.12, asyncio, httpx, asyncpg, BeautifulSoup, Streamlit, pytest. Package manager: `uv`. Dev DB: Postgres 16 in docker compose. The repo will be driven by Claude Code itself, so the scaffold must include `.claude/` configuration that enforces TDD via hooks and supports a plan-first workflow.

## Conventions you MUST follow

- **TDD enforcement is via hooks, not honour-system.** Editing anything under `src/scraper/` without touching `tests/` in the same change must be blocked at the hook layer. Non-code files (`*.md`, `*.toml`, `*.yaml`, `*.json`, `Makefile`, `.env*`, anything under `.claude/`, `docs/`, `agent_docs/`) are exempt.
- **Plan-first.** Every non-trivial change starts with a plan file in `.claude/plans/<YYYY-MM-DD>-<slug>.md` derived from `.claude/plans/_template.md`. The hook blocks `Write|Edit|MultiEdit` on `src/scraper/**` unless at least one plan in `.claude/plans/` has `Status: approved` or `Status: in-progress`. (You're scaffolding now, so create one plan with `Status: approved` named `2026-05-10-scaffold.md` so the hooks don't block you within this same session.)
- **Postgres-only.** No SQLite. Jobs queue, observations, everything in Postgres. Use `SELECT ... FOR UPDATE SKIP LOCKED` semantics for worker pop later.
- **Async everywhere I/O happens.** Sync code in `src/scraper/sources/`, `src/scraper/db/`, `src/scraper/pipeline/` is forbidden. Streamlit UI may wrap async via `asyncio.run`.
- **Type hints everywhere.** `mypy --strict` clean.
- **`uv` only.** Forbid `pip install` in hook safety.
- **Don't roll your own where stdlib/canonical libraries exist.** `python-stdnum.be.vat` for KBO checksums (the algorithm is `97 - (int(first8) % 97) == int(last2)`; do not reimplement). `phonenumbers` for Belgian phone classification.
- **Provenance is append-only.** No `UPDATE` on canonical fact tables — ever. Multi-source observations are kept in an `observations` table; a materialised view computes "current best."

## What to produce in this session

Create exactly the files listed below. Do not create source modules, skills, or sources beyond what's listed — those come in later prompts. After file creation, run `uv sync --locked --dev` to verify the manifest is coherent, run `docker compose config` to verify the compose file parses, and stop.

### File tree to create

```
be-leads/
├── pyproject.toml
├── .python-version
├── .gitignore
├── .env.example
├── README.md
├── CLAUDE.md
├── CHANGELOG.md
├── Makefile
├── docker-compose.yml
├── .pre-commit-config.yaml
├── .mcp.json
├── .claude/
│   ├── settings.json
│   ├── settings.local.json.example
│   ├── plans/
│   │   ├── _template.md
│   │   └── 2026-05-10-scaffold.md
│   ├── hooks/
│   │   ├── tdd_gate.sh
│   │   ├── format_and_test.sh
│   │   ├── coverage_gate.sh
│   │   └── bash_safety.sh
│   ├── skills/                      (empty, populated in later prompts)
│   ├── commands/                    (empty, populated later)
│   └── agents/                      (empty, populated later)
├── agent_docs/
│   ├── architecture.md
│   ├── data-model.md
│   └── runbook.md
├── docs/
│   └── decisions/
│       └── 0001-postgres-only.md
├── src/
│   └── scraper/
│       └── __init__.py
└── tests/
    ├── __init__.py
    └── conftest.py
```

### File-by-file specification

**`pyproject.toml`** — project name `be-leads`, version `0.1.0`, requires Python `>=3.12`. Dependencies: `httpx>=0.27`, `asyncpg>=0.29`, `beautifulsoup4>=4.12`, `lxml>=5`, `pydantic>=2.7`, `structlog>=24`, `streamlit>=1.36`, `pdfplumber>=0.11`, `tenacity>=9`, `python-stdnum>=1.20`, `phonenumbers>=8.13`, `python-dotenv>=1.0`. Dev group `[dependency-groups] dev`: `pytest>=8`, `pytest-asyncio>=0.24`, `pytest-cov>=5`, `pytest-recording>=0.13`, `respx>=0.22`, `ruff>=0.6`, `mypy>=1.11`, `pre-commit>=3`, `playwright>=1.59`. Tool sections: `[tool.ruff] target-version="py312" line-length=100`, `[tool.ruff.lint] select=["E","W","F","I","N","UP","B","C4","SIM","TCH","ASYNC","S","RUF"]`, `[tool.mypy] python_version="3.12" strict=true`, `[tool.pytest.ini_options] asyncio_mode="auto" addopts=["--import-mode=importlib","-ra"] testpaths=["tests"] markers=["network: tests that hit real third-party hosts","slow: long-running tests"]`, `[tool.coverage.run] source=["src/scraper"]`. Build system: hatchling, packages = `["src/scraper"]`.

**`.python-version`** → `3.12`

**`.gitignore`** — Python (`__pycache__`, `*.pyc`, `.venv/`, `dist/`, `*.egg-info/`), pytest (`.pytest_cache/`, `htmlcov/`, `.coverage`), uv (`.uv-cache/`), env (`.env`, `.env.local`), Claude (`.claude/settings.local.json`, `.claude/hooks.log`), data (`data/`), IDE (`.vscode/`, `.idea/`, `*.swp`).

**`.env.example`** — `DATABASE_URL=postgresql://leads:leads@localhost:5432/leads`, `LOG_LEVEL=INFO`, `RUN_ENV=dev`, with comments. Add `NBB_CBSO_API_KEY=` and `NBB_CBSO_CLIENT_NUMBER=` (commented, to be filled when prompt for NBB source ships). Add `BRAVE_SEARCH_API_KEY=` (optional fallback).

**`README.md`** — three sections only: "What this is" (one paragraph), "Quick start" (the commands listed at the end of CLAUDE.md), "Repo layout" (point to CLAUDE.md and `agent_docs/architecture.md`). No marketing prose.

**`CLAUDE.md`** — verbatim follow this structure (target ≤150 lines, ≤5 KB):

```markdown
# be-leads — Claude Operating Manual

## Project (one paragraph)
High-volume recurring scraper for Belgian B2B company data. Sources will be added incrementally:
KBO Open Data dump (canonical bulk), kbopub HTML (function holders), NBB CBSO Authentic Data
(financials), goudengids/pagesdor listing pages (discovery), company websites (enrichment),
DuckDuckGo + Brave (cross-validation). Output: provenance-tracked Postgres database with a
Streamlit UI for sector × city queries.

## Architecture map
- `src/scraper/lib/`              cross-cutting helpers (http, polite, provenance, validators, errors, logging)
- `src/scraper/db/`                asyncpg pool, repositories, migrations, Pydantic row models
- `src/scraper/sources/<name>/`    one directory per source, layout: `fetcher.py | parser.py | __init__.py`
- `src/scraper/pipeline/`          orchestration: smart-refresh scheduler, enrichment fan-out, consolidation
- `src/scraper/scoring/`           confidence + dedup
- `src/scraper/ui/`                Streamlit app

Async boundary: every I/O function is `async`. Sync code is forbidden in `sources/`, `db/`, `pipeline/`.
UI may call `asyncio.run` at boundaries.

## Data model (canonical)
- `companies(kbo_number PK, ...)`             materialised current-best, NEVER directly UPDATEd
- `observations(id, kbo_number, field, value JSONB, source, observed_at, confidence, run_id, ...)`  append-only
See `agent_docs/data-model.md` for the full schema. The schema migration ships in prompt 3.

## Testing rules — TDD IS ENFORCED BY HOOKS
- Every change to `src/scraper/**` MUST touch `tests/**` in the same turn.
- Tests organised: `tests/unit/`, `tests/integration/`, `tests/golden/` (HTML/JSON/XBRL samples).
- `uv run pytest --cov=src/scraper --cov-fail-under=85` must pass before Stop.
- New scrapers require ≥3 golden HTML samples in `tests/golden/<source>/`.
- Network-hitting tests are marked `@pytest.mark.network` and skipped in CI.

## Coding conventions
- Type hints everywhere; `mypy --strict`.
- Pydantic v2 only at boundaries (parsed records, API I/O). Internal data: `@dataclass(frozen=True, slots=True)`.
- Pass dependencies explicitly (httpx client, asyncpg pool). No module-level globals.
- `asyncio.TaskGroup` for fan-out, never bare `create_task`.
- `structlog` with `contextvars`; bind `kbo_number`, `source`, `run_id` at outermost scope.
- Errors: typed exceptions in `src/scraper/lib/errors.py`. No bare `except:`.
- HTTP: never `httpx.AsyncClient()` per request — use the pool from `src/scraper/lib/http/`.

## Anti-patterns (never)
- `UPDATE companies SET ...` — observations only, never overwrite canonical facts.
- Synchronous I/O in async paths.
- Auto-retry on 403 — escalate or stop. Retry only on 429/503/504.
- Reimplementing KBO checksum or Belgian phone validation — use `python-stdnum.be.vat` and `phonenumbers`.
- Reading personal data into the system without per-source flags. (Out of scope for this iteration but the schema must support it later.)

## Per-source knowledge
Skills live under `.claude/skills/<name>/SKILL.md` and load on demand. Don't put per-source detail
in this file.

## Polite scraping
Default 0.5 req/s per host, exponential backoff with jitter on 429/503. Honour Retry-After. Skip on 403.
robots.txt fetched and cached at startup. See `.claude/skills/polite-scraping/SKILL.md` (added prompt 2).

## How to run
- One-time: `uv python install 3.12 && uv sync --locked --dev && uv run playwright install chromium`
- DB: `docker compose up -d pg`
- Tests: `uv run pytest` or `uv run pytest -m "not network"`
- Lint: `uv run ruff check . && uv run ruff format --check .`
- Type check: `uv run mypy src/scraper`
- App: `uv run streamlit run src/scraper/ui/app.py`

## Definition of done (every change)
1. Plan written in `.claude/plans/` and approved.
2. Tests added/updated FIRST, failing on the new behaviour.
3. Implementation makes them pass.
4. `ruff check`, `ruff format --check`, `mypy --strict` clean on changed files.
5. Coverage not regressed.
6. CHANGELOG entry added.
```

**`CHANGELOG.md`** — Keep-a-Changelog format, one entry under `[Unreleased]` → `Added: scaffold (prompt 1)`.

**`Makefile`** — targets: `pg-up`, `pg-down`, `pg-logs`, `install`, `test`, `test-fast`, `lint`, `type`, `coverage`, `format`, `clean`. All commands use `uv run` where applicable.

**`docker-compose.yml`** — single service `pg` running `postgres:16`, env `POSTGRES_USER=leads POSTGRES_PASSWORD=leads POSTGRES_DB=leads`, port `5432:5432`, named volume `pgdata`, healthcheck `pg_isready -U leads`.

**`.pre-commit-config.yaml`** — ruff (`v0.6.0`, both `ruff-check --fix` and `ruff-format`), local hooks for `mypy src/scraper` and `pytest -x -q -m "not network and not slow"`. Use `language: system`, `pass_filenames: false` for the local hooks.

**`.mcp.json`** — three servers, project-scoped:
- `postgres`: stdio, `command: "uvx"`, `args: ["postgres-mcp", "--access-mode=restricted"]`, `env: { "DATABASE_URL": "${LEADS_DB_RO_URL}" }`. Add a comment-style note in CLAUDE.md telling the dev to set `LEADS_DB_RO_URL` to a read-only role.
- `playwright`: stdio, `command: "npx"`, `args: ["-y", "@playwright/mcp@latest", "--allowed-origins", "goudengids.be;pagesdor.be;kbopub.economie.fgov.be;consult.cbso.nbb.be;ws.cbso.nbb.be"]`.
- `sequential-thinking`: stdio, `command: "npx"`, `args: ["-y", "@modelcontextprotocol/server-sequential-thinking"]`.

**`.claude/settings.json`** — verbatim:

```json
{
  "permissions": {
    "defaultMode": "default",
    "allow": [
      "Read", "Glob", "Grep", "LS", "TodoRead", "TodoWrite", "WebSearch",
      "WebFetch(domain:goudengids.be)",
      "WebFetch(domain:pagesdor.be)",
      "WebFetch(domain:kbopub.economie.fgov.be)",
      "WebFetch(domain:economie.fgov.be)",
      "WebFetch(domain:consult.cbso.nbb.be)",
      "WebFetch(domain:ws.cbso.nbb.be)",
      "WebFetch(domain:nbb.be)",
      "WebFetch(domain:bipt.be)",
      "WebFetch(domain:statbel.fgov.be)",
      "WebFetch(domain:duckduckgo.com)",
      "WebFetch(domain:api.search.brave.com)",
      "WebFetch(domain:web.archive.org)",
      "WebFetch(domain:docs.claude.com)",
      "Bash(uv run pytest:*)",
      "Bash(uv run ruff:*)",
      "Bash(uv run mypy:*)",
      "Bash(uv run python -m scraper.*)",
      "Bash(uv run streamlit:*)",
      "Bash(uv add:*)",
      "Bash(uv sync:*)",
      "Bash(uv lock:*)",
      "Bash(git status)",
      "Bash(git diff:*)",
      "Bash(git log:*)",
      "Bash(git add:*)",
      "Bash(git commit:*)",
      "Bash(git checkout:*)",
      "Bash(git switch:*)",
      "Bash(make:*)",
      "Bash(docker compose:*)",
      "Bash(psql:*)",
      "Bash(jq:*)",
      "mcp__postgres__query",
      "mcp__postgres__list_tables",
      "mcp__postgres__describe_table",
      "mcp__sequential-thinking__*"
    ],
    "ask": [
      "Edit(src/**)", "Write(src/**)",
      "Edit(.claude/**)", "Write(.claude/**)",
      "Edit(.mcp.json)", "Edit(pyproject.toml)",
      "Bash(git push:*)", "Bash(git rebase:*)",
      "mcp__playwright__*"
    ],
    "deny": [
      "Read(./.env)", "Read(./.env.*)",
      "Read(~/.ssh/**)", "Read(~/.aws/**)",
      "Bash(rm -rf /*)", "Bash(rm -rf ~*)",
      "Bash(sudo:*)",
      "Bash(curl http*)", "Bash(wget http*)",
      "Bash(pip install:*)", "Bash(pip3 install:*)", "Bash(python -m pip install:*)",
      "Bash(git push --force*)", "Bash(git push -f*)", "Bash(git reset --hard*)"
    ]
  },
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Write|Edit|MultiEdit",
        "hooks": [{ "type": "command", "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/tdd_gate.sh", "timeout": 10 }]
      },
      {
        "matcher": "Bash",
        "hooks": [{ "type": "command", "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/bash_safety.sh", "timeout": 5 }]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Write|Edit|MultiEdit",
        "hooks": [{ "type": "command", "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/format_and_test.sh", "timeout": 120 }]
      }
    ],
    "Stop": [
      {
        "matcher": "",
        "hooks": [{ "type": "command", "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/coverage_gate.sh", "timeout": 180 }]
      }
    ],
    "SessionStart": [
      {
        "matcher": "",
        "hooks": [{ "type": "command", "command": "echo \"hooks-armed $(date -Iseconds)\" >> .claude/hooks.log" }]
      }
    ]
  },
  "showTurnDuration": true
}
```

**`.claude/settings.local.json.example`** — empty `{}` with a comment-style README hint that this file is gitignored and overrides project settings.

**`.claude/plans/_template.md`** — the plan template:

```markdown
# Plan: <one-line goal>
Date: YYYY-MM-DD
Author:
Status: draft

## Goal
One paragraph. What changes for the system, not what code to write.

## Scope (in)
-

## Out of scope
-

## Files to be created or modified
-

## Tests required (red first)
-

## Acceptance criteria
- [ ]

## Risks
-

## Rollback plan
-
```

**`.claude/plans/2026-05-10-scaffold.md`** — copy of the template with:
- Status: `approved`
- Goal: "Scaffold the be-leads repository (prompt 1) so subsequent prompts can add skills and sources within enforced TDD/plan-first guardrails."
- Files: list every file in this prompt.
- Tests: a single placeholder test under `tests/test_scaffold.py` that imports `scraper` and asserts version metadata exists.
- Acceptance: `uv sync --locked --dev` succeeds; `pytest` collects ≥1 test; `docker compose config` parses; SessionStart hook produced a line in `.claude/hooks.log`.

**`.claude/hooks/tdd_gate.sh`** — bash, `set -euo pipefail`. Reads JSON from stdin (`jq -r '.tool_input.file_path // .tool_input.path // empty'`). Allowlist of exempt paths: `*.md`, `*.toml`, `*.yaml`, `*.yml`, `*.json`, `*.lock`, `*Makefile`, `*.env*`, `.claude/*`, `docs/*`, `agent_docs/*`. If the file is under `src/scraper/` and `git status --porcelain tests/` shows zero changes, print to stderr `"TDD gate: editing $FILE without any tests/ change. Add or update a test first."` and exit 2. Also enforce plan-first: if no file in `.claude/plans/*.md` matches `^Status: (approved|in-progress)`, print to stderr `"No approved/in-progress plan in .claude/plans/. Run /plan first."` and exit 2. Otherwise exit 0.

**`.claude/hooks/format_and_test.sh`** — bash, `set -euo pipefail`. Read file path from stdin JSON. If not a `.py` file, exit 0. Run `uv run ruff format` (best-effort, suppress errors), `uv run ruff check --fix` (best-effort). Then run `uv run pytest -x -q --no-header` against the touched module path. On failure print stderr and exit 2. On success exit 0.

**`.claude/hooks/coverage_gate.sh`** — bash, `set -euo pipefail`. If `git diff --name-only HEAD` shows no `.py` changes this session, exit 0. Otherwise run `uv run pytest --cov=src/scraper --cov-fail-under=85 -q --tb=no | tail -20`. On failure exit 2.

**`.claude/hooks/bash_safety.sh`** — bash. Read command from stdin JSON. Forbidden patterns (case-insensitive grep, exit 2 with reason on stderr): `rm -rf /`, `rm -rf ~`, `pip install`, `pip3 install`, `python -m pip install`, `git push --force`, `git push -f`, `DROP DATABASE`, `DROP TABLE`, `TRUNCATE `, `sudo `. Otherwise exit 0.

All four hook scripts must be `chmod +x`.

**`agent_docs/architecture.md`** — placeholder with a TODO list and references to the future module layout. Document the Postgres-only decision and the async-everywhere boundary rule.

**`agent_docs/data-model.md`** — placeholder with the observations-table schema sketch (not creating the migration yet — that's prompt 3) and the materialised-view rebuild strategy.

**`agent_docs/runbook.md`** — placeholder with sections "Daily KBO Open Data update", "NBB CBSO key registration", "Imperva cookie warm-up", "Rotating residential IP" — content to be filled in later prompts.

**`docs/decisions/0001-postgres-only.md`** — short ADR. Status: Accepted, 2026-05-10. Context: prior project used SQLite for the jobs queue. Decision: drop SQLite, use Postgres-only with `SELECT ... FOR UPDATE SKIP LOCKED` for worker pop. Consequences: one DB to back up, async-only via asyncpg, no cross-DB transaction coordination, requires Postgres in dev (covered by docker compose).

**`src/scraper/__init__.py`** — module docstring, `__version__ = "0.1.0"`.

**`tests/__init__.py`** — empty file.

**`tests/conftest.py`** — empty for now (one comment line: `# shared fixtures will live here`).

**`tests/test_scaffold.py`** — single test `def test_package_metadata():` that imports `scraper` and asserts `scraper.__version__ == "0.1.0"`.

## Verification — run after creating files

```
uv sync --locked --dev
docker compose config
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy src/scraper
ls -la .claude/hooks.log     # SessionStart wrote here
```

If any step fails, fix it, then stop. Do not proceed to add sources, skills, or scaffolding beyond this list.

## Stop conditions

When all files are created and the verification commands pass:
1. Print a one-line summary of what was created (file count, total size).
2. Print the next-step instruction verbatim: `Ready for prompt 2 (skill: polite-scraping). Commit this scaffold first: git init && git add . && git commit -m "scaffold (prompt 1)".`
3. End the turn. Do not start writing skills or source modules.

## Things you must NOT do in this session

- Do not create source files in `src/scraper/sources/`, `src/scraper/db/`, `src/scraper/pipeline/`, `src/scraper/scoring/`, `src/scraper/lib/`, or `src/scraper/ui/`. Those come in later prompts.
- Do not create any `.claude/skills/<name>/SKILL.md`. Skills come in later prompts.
- Do not run `git init` or `git commit`. The user does that.
- Do not install Playwright browsers (`playwright install`). The user does that.
- Do not start Postgres. The user does that.
- Do not write any database migration. Migrations come in prompt 3.
