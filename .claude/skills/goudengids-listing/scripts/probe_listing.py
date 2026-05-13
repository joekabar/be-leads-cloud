"""Manual probe script: open a Playwright browser and fetch page 1 for a sector/city.

Usage:
    uv run python .claude/skills/goudengids-listing/scripts/probe_listing.py \
        <sector_slug> <city_slug> [--lang nl|fr]

Hits live goudengids.be — run sparingly (0.3 rps budget).
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

# Allow running from any cwd.
sys.path.insert(0, str(Path(__file__).parents[4] / "src"))


async def main(sector: str, city: str, lang: str) -> None:
    from scraper.lib.http.limiter import load_from_toml
    from scraper.sources.goudengids.fetcher import BrowserListingFetcher
    from scraper.sources.goudengids.parser import parse_listing_page

    per_host_toml = (
        Path(__file__).parents[4]
        / ".claude"
        / "skills"
        / "polite-scraping"
        / "references"
        / "per-host.toml"
    )
    domain = "pagesdor.be" if lang == "fr" else "goudengids.be"
    limiter = load_from_toml(per_host_toml)

    print(f"Opening Chromium browser for {domain}…", file=sys.stderr)
    async with BrowserListingFetcher(limiter, domain=domain) as fetcher:
        print("Browser ready. Fetching page 1…", file=sys.stderr)
        page = await fetcher.fetch_page(sector, city, 1, lang=lang)  # type: ignore[arg-type]
        cards = parse_listing_page(page.html, domain=domain)

    print(f"\n{len(cards)} cards found (is_last={page.is_last_page})")
    if cards:
        first = cards[0]
        print(
            json.dumps(
                {
                    "name": first.name,
                    "phones": first.phones,
                    "website": first.website,
                    "street": first.address_street,
                    "postal_code": first.address_postal_code,
                    "city": first.address_city,
                    "detail_url": first.detail_url,
                },
                indent=2,
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("sector")
    p.add_argument("city")
    p.add_argument("--lang", default="nl", choices=["nl", "fr"])
    args = p.parse_args()

    asyncio.run(main(args.sector, args.city, args.lang))
