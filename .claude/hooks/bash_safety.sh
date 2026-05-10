#!/usr/bin/env bash

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

[[ -z "$COMMAND" ]] && exit 0

# Forbidden patterns (case-insensitive fixed-string match)
FORBIDDEN=(
  "rm -rf /"
  "rm -rf ~"
  "pip install"
  "pip3 install"
  "python -m pip install"
  "git push --force"
  "git push -f"
  "DROP DATABASE"
  "DROP TABLE"
  "TRUNCATE "
  "sudo "
)

for pattern in "${FORBIDDEN[@]}"; do
  if echo "$COMMAND" | grep -qiF "$pattern"; then
    echo "bash_safety: forbidden pattern detected: '$pattern'" >&2
    exit 2
  fi
done

exit 0
