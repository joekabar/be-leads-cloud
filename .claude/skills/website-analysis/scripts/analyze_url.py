#!/usr/bin/env python
"""Dev script: analyze a single company URL and print a structured summary.

Usage:
    uv run python .claude/skills/website-analysis/scripts/analyze_url.py https://bellock.be

Hits the live website — do NOT call from tests.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[4] / "src"))


async def main(url: str) -> None:
    from scraper.sources.website.age import estimate_age
    from scraper.sources.website.contact_page import find_contact_page
    from scraper.sources.website.fetcher import fetch_page
    from scraper.sources.website.persons import extract_persons
    from scraper.sources.website.structured import extract_jsonld

    from scraper.lib.http.client import get_polite_client
    from scraper.lib.http.limiter import load_from_toml

    per_host_toml = (
        Path(__file__).parents[4]
        / ".claude"
        / "skills"
        / "polite-scraping"
        / "references"
        / "per-host.toml"
    )

    limiter = load_from_toml(per_host_toml)
    async with get_polite_client(limiter) as client:
        print(f"Fetching {url} …", file=sys.stderr)
        page = await fetch_page(client, url)
        print(f"  status={page.status} final_url={page.final_url}", file=sys.stderr)

        print("\n--- JSON-LD ---", file=sys.stderr)
        entities = extract_jsonld(page.html)
        for e in entities:
            print(
                json.dumps(
                    {
                        "type": e.type,
                        "name": e.name,
                        "telephones": e.telephones,
                        "emails": e.emails,
                        "description": e.description,
                        "opening_hours": e.opening_hours,
                        "founders": e.founders,
                        "employees": e.employees,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )

        print("\n--- Contact page ---", file=sys.stderr)
        contact_url = await find_contact_page(client, page.final_url, page.html)
        print(f"  contact_url={contact_url}", file=sys.stderr)

        print("\n--- Persons ---", file=sys.stderr)
        persons = extract_persons(page.html)
        for p in persons:
            print(f"  {p.name!r} role={p.role!r} source={p.source}")

        print("\n--- Age ---", file=sys.stderr)
        year, source_label = await estimate_age(page.final_url, page.html)
        print(f"  year={year} source={source_label}", file=sys.stderr)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: analyze_url.py <url>", file=sys.stderr)
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
