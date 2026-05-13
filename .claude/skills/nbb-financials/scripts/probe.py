#!/usr/bin/env python
"""Probe the NBB CBSO API with a single KBO. Confirms the subscription key works.

Usage:
    NBB_CBSO_API_KEY=<your-key> uv run python .claude/skills/nbb-financials/scripts/probe.py
    NBB_CBSO_API_KEY=<your-key> uv run python .claude/skills/nbb-financials/scripts/probe.py 0502699332
"""

from __future__ import annotations

import json
import os
import sys
import uuid

import httpx

_BASE_URL = "https://ws.cbso.nbb.be"
_DEFAULT_KBO = "0439401387"


def main() -> None:
    key = os.environ.get("NBB_CBSO_API_KEY", "")
    if not key:
        print("Error: set NBB_CBSO_API_KEY before running this script.", file=sys.stderr)
        sys.exit(1)

    kbo = sys.argv[1] if len(sys.argv) > 1 else _DEFAULT_KBO
    url = f"{_BASE_URL}/authentic/legalEntity/{kbo}/references"
    headers = {
        "NBB-CBSO-Subscription-Key": key,
        "X-Request-Id": str(uuid.uuid4()),
        "Accept": "application/json",
        "Accept": "application/json",
    }

    print(f"GET {url}", file=sys.stderr)
    response = httpx.get(url, headers=headers, timeout=15)
    print(f"Status: {response.status_code}", file=sys.stderr)
    print(json.dumps(response.json(), indent=2))


if __name__ == "__main__":
    main()
