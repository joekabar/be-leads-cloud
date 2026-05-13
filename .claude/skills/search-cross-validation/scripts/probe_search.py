#!/usr/bin/env python
"""Quick CLI probe: search for a company name + city and print classified results.

Usage:
    uv run python .claude/skills/search-cross-validation/scripts/probe_search.py "Bellock" "Antwerpen"
    BRAVE_SEARCH_API_KEY=... uv run python ... "Bellock" "Antwerpen"
"""

from __future__ import annotations

import asyncio
import os
import sys


async def _run(name: str, city: str) -> None:
    from scraper.sources.ddg_brave.classifier import classify
    from scraper.sources.ddg_brave.parser import parse_brave, parse_ddg

    query = f'"{name}" {city}'
    brave_key = os.environ.get("BRAVE_SEARCH_API_KEY")

    if brave_key:
        import httpx
        from scraper.sources.ddg_brave.brave_client import BraveClient

        from scraper.lib.http.client import PoliteClient
        from scraper.lib.http.limiter import HostConfig, HostLimiter

        fast = HostConfig(rps=1.0, concurrency=1, timeout_s=10.0, user_agent_pool_id="api-client")
        limiter = HostLimiter(configs={}, default=fast)
        async with httpx.AsyncClient(follow_redirects=True) as inner:
            pc = PoliteClient(inner=inner, limiter=limiter)
            bc = BraveClient(pc, brave_key)
            payload = await bc.search(query)
        results = parse_brave(payload)
        engine = "brave"
    else:
        from scraper.sources.ddg_brave.ddg_client import DdgClient

        client = DdgClient()
        raw = await client.search(query, max_results=10)
        results = parse_ddg(raw)
        engine = "ddg"

    print(f"Engine: {engine}  Query: {query}  Results: {len(results)}")
    for r in results:
        c = classify(r, name)
        print(f"  {c.bucket:18s} {r.domain:40s} {r.title[:60]}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: probe_search.py <name> <city>", file=sys.stderr)
        sys.exit(1)
    asyncio.run(_run(sys.argv[1], sys.argv[2]))
