"""Test NBB CBSO and Brave Search API key connectivity."""

from __future__ import annotations

import asyncio
import os

import httpx

from scraper.lib.http.client import PoliteClient
from scraper.lib.http.limiter import HostConfig, HostLimiter

_DEFAULT = HostConfig(rps=2.0, concurrency=4, timeout_s=15.0, user_agent_pool_id="api-client")


def _make_client(inner: httpx.AsyncClient) -> PoliteClient:
    limiter = HostLimiter(configs={}, default=_DEFAULT)
    return PoliteClient(inner=inner, limiter=limiter)


async def check_nbb(client: PoliteClient, key: str) -> None:
    from scraper.lib.errors import NbbAuthError, NbbNotFoundError
    from scraper.sources.nbb_authentic.client import NbbClient

    nbb = NbbClient(polite_client=client, subscription_key=key)
    kbo = "0439401387"  # Bellock NV — well-known Belgian company
    try:
        refs = await nbb.get_references(kbo)
        print(f"[NBB] OK — {len(refs)} references for {kbo}")
    except NbbAuthError:
        print("[NBB] FAIL — 401 Unauthorized: key is invalid or expired")
    except NbbNotFoundError:
        print(f"[NBB] OK (key valid) — {kbo} has no annual reports in NBB")
    except Exception as exc:
        print(f"[NBB] ERROR — {exc}")


async def check_brave(client: PoliteClient, key: str) -> None:
    from scraper.sources.ddg_brave.brave_client import BraveAuthError, BraveClient

    brave = BraveClient(polite_client=client, subscription_key=key)
    try:
        result = await brave.search("Bellock NV Antwerpen", count=3)
        hits = len(result.get("web", {}).get("results", []))
        print(f"[Brave] OK — {hits} results for test query")
    except BraveAuthError:
        print("[Brave] FAIL — 401 Unauthorized: key is invalid")
    except Exception as exc:
        print(f"[Brave] ERROR — {exc}")


async def main() -> None:
    nbb_key = os.environ.get("NBB_CBSO_API_KEY", "")
    brave_key = os.environ.get("BRAVE_SEARCH_API_KEY", "")

    if not nbb_key:
        print("[NBB] SKIP — NBB_CBSO_API_KEY not set")
    if not brave_key:
        print("[Brave] SKIP — BRAVE_SEARCH_API_KEY not set")

    if not nbb_key and not brave_key:
        return

    async with httpx.AsyncClient(follow_redirects=True) as inner:
        client = _make_client(inner)
        tasks = []
        if nbb_key:
            tasks.append(check_nbb(client, nbb_key))
        if brave_key:
            tasks.append(check_brave(client, brave_key))
        await asyncio.gather(*tasks)


asyncio.run(main())
