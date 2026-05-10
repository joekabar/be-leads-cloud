#!/usr/bin/env bash
set -euo pipefail

INPUT=$(cat)
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.path // empty')

# Only process Python files
[[ -z "$FILE" ]] && exit 0
[[ "$FILE" != *.py ]] && exit 0

# Format and lint (best-effort — don't block on formatter failures)
uv run ruff format "$FILE" 2>/dev/null || true
uv run ruff check --fix "$FILE" 2>/dev/null || true

# Run tests
if ! uv run pytest -x -q --no-header tests/ 2>&1; then
  echo "Tests failed after editing $FILE" >&2
  exit 2
fi

exit 0
