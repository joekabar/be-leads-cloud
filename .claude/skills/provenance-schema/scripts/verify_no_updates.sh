#!/usr/bin/env bash
# Guard: fail if any source file contains UPDATE on observations or companies_current.
# Designed for use as a pre-commit hook. Exit 0 = clean, exit 2 = violation found.
set -euo pipefail

SEARCH_DIR="${1:-src}"

# Case-insensitive grep for UPDATE on the two protected tables.
# Allow flexible whitespace between UPDATE and the table name.
if grep -rEi --include="*.py" --include="*.sql" \
    "UPDATE[[:space:]]+(observations|companies_current)" \
    "$SEARCH_DIR" 2>/dev/null; then
    echo "" >&2
    echo "ERROR: Found UPDATE on observations or companies_current in $SEARCH_DIR" >&2
    echo "These tables are append-only. Use INSERT INTO observations instead." >&2
    echo "See .claude/skills/provenance-schema/SKILL.md for the cardinal rule." >&2
    exit 2
fi

exit 0
