from __future__ import annotations

import urllib.parse
from typing import TYPE_CHECKING, Literal

from scraper.lib.errors import InvalidKboError, KboNotFoundError, TerminalServerError

if TYPE_CHECKING:
    from scraper.lib.http.client import PoliteClient

_BASE_URL = "https://kbopub.economie.fgov.be/kbopub/toonondernemingps.html"


def build_detail_url(kbo_number: str, lang: Literal["nl", "fr"] = "nl") -> str:
    """Return the canonical kbopub detail-page URL for one KBO (10-digit compact form)."""
    params = urllib.parse.urlencode({"lang": lang, "ondernemingsnummer": kbo_number})
    return f"{_BASE_URL}?{params}"


async def fetch_detail_page(
    client: PoliteClient,
    kbo_number: str,
    *,
    lang: Literal["nl", "fr"] = "nl",
) -> str:
    """GET the kbopub detail page HTML for one KBO.

    Validates the KBO number via stdnum before requesting. Returns raw HTML.
    Raises InvalidKboError on bad checksum, KboNotFoundError on HTTP 404,
    BlockedError on HTTP 403 (escalate per polite-scraping rules).
    """
    from stdnum.be import vat

    if not vat.is_valid(kbo_number):
        raise InvalidKboError(kbo_number)

    compact = vat.compact(kbo_number)
    url = build_detail_url(compact, lang)

    try:
        response = await client.get(url)
    except TerminalServerError as exc:
        if exc.status == 404:
            raise KboNotFoundError(compact, url) from exc
        raise

    return response.text
