#!/usr/bin/env python
"""Dev CLI: validate a Belgian phone number and print the canonical JSON.

Usage:
    uv run python .claude/skills/belgian-phone-validation/scripts/validate.py "03 236 13 06"
    echo "0474 12 34 56" | uv run python .claude/skills/belgian-phone-validation/scripts/validate.py
"""

from __future__ import annotations

import json
import sys

from scraper.lib.validators import InvalidPhoneError, validate_phone


def main() -> None:
    phone = sys.argv[1] if len(sys.argv) >= 2 else sys.stdin.readline().strip()

    try:
        result = validate_phone(phone)
        print(json.dumps(result.model_dump()))
    except InvalidPhoneError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
