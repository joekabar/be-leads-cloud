#!/usr/bin/env python3
"""CLI: check whether a URL is fetchable per that host's robots.txt."""

import sys
import urllib.parse
import urllib.robotparser


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: check_robots.py <url> [user-agent]", file=sys.stderr)
        sys.exit(1)

    url = sys.argv[1]
    ua = sys.argv[2] if len(sys.argv) > 2 else "be-leads/0.1"

    parsed = urllib.parse.urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"

    rp = urllib.robotparser.RobotFileParser()
    rp.set_url(robots_url)
    try:
        rp.read()
    except Exception as exc:
        print(f"Could not fetch {robots_url}: {exc}")
        print("Defaulting to: ALLOWED")
        sys.exit(0)

    allowed = rp.can_fetch(ua, url)
    delay = rp.crawl_delay(ua)

    print(f"URL:         {url}")
    print(f"User-agent:  {ua}")
    print(f"Allowed:     {allowed}")
    print(f"Crawl-delay: {delay if delay is not None else 'not set'}")


if __name__ == "__main__":
    main()
