#!/usr/bin/env bash
set -euo pipefail

INPUT=$(cat)
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.path // empty')

# No file path in payload — not a file-write tool
[[ -z "$FILE" ]] && exit 0

# Strip leading ./ for consistent matching
FILE="${FILE#./}"

# Exempt: non-code file types
[[ "$FILE" == *.md     ]] && exit 0
[[ "$FILE" == *.toml   ]] && exit 0
[[ "$FILE" == *.yaml   ]] && exit 0
[[ "$FILE" == *.yml    ]] && exit 0
[[ "$FILE" == *.json   ]] && exit 0
[[ "$FILE" == *.lock   ]] && exit 0
[[ "$FILE" == *Makefile* ]] && exit 0
if echo "$FILE" | grep -qE '\.env'; then exit 0; fi

# Exempt: non-code directories
if echo "$FILE" | grep -qE '(^|/)\.claude/|(^|/)docs/|(^|/)agent_docs/'; then
  exit 0
fi

# Plan-first gate: require at least one approved or in-progress plan
PLANS_DIR="${CLAUDE_PROJECT_DIR:-.}/.claude/plans"
if ! grep -rlE '^Status: (approved|in-progress)' "$PLANS_DIR"/ 2>/dev/null | grep -q .; then
  echo "No approved/in-progress plan in .claude/plans/. Run /plan first." >&2
  exit 2
fi

# TDD gate: src/scraper/** changes must be paired with a tests/** change in the same session
if echo "$FILE" | grep -q 'src/scraper/'; then
  if git rev-parse --git-dir > /dev/null 2>&1; then
    if [[ -z "$(git status --porcelain tests/ 2>/dev/null)" ]]; then
      echo "TDD gate: editing $FILE without any tests/ change. Add or update a test first." >&2
      exit 2
    fi
  fi
fi

exit 0
