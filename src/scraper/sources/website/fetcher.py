"""Fetch a single webpage via PoliteClient."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scraper.lib.http.client import PoliteClient


@dataclass(frozen=True, slots=True)
class FetchedPage:
    url: str
    html: str
    status: int
    final_url: str


def _normalise_url(url: str) -> str:
    url = url.strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


async def fetch_page(
    client: PoliteClient,
    url: str,
) -> FetchedPage:
    """GET the URL.  Returns the page even on non-200 so callers can decide."""
    url = _normalise_url(url)
    response = await client.get(url)
    html = response.text
    return FetchedPage(
        url=url,
        html=html,
        status=response.status_code,
        final_url=str(response.url),
    )
