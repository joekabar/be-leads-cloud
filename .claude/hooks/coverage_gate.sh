#!/usr/bin/env bash
set -euo pipefail

# Skip if not in a git repo (e.g. first session before git init)
if ! git rev-parse --git-dir > /dev/null 2>&1; then
  exit 0
fi

# Skip if no Python files changed since last commit
CHANGED_PY=$(git diff --name-only HEAD 2>/dev/null | grep '\.py$' || true)
[[ -z "$CHANGED_PY" ]] && exit 0

# Run coverage gate
set +e
OUTPUT=$(uv run pytest --cov=src/scraper --cov-fail-under=85 -q --tb=no 2>&1)
STATUS=$?
set -e

echo "$OUTPUT" | tail -20

if [[ $STATUS -ne 0 ]]; then
  echo "Coverage gate failed (threshold: 85%)" >&2
  exit 2
fi

exit 0
