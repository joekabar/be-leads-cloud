from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from stdnum.be import vat as be_vat

from scraper.lib.errors import NbbAuthError, NbbNotFoundError, TerminalServerError
from scraper.sources.nbb_authentic.parser import ReferenceRow, parse_references

if TYPE_CHECKING:
    from scraper.lib.http.client import PoliteClient

_BASE_URL = "https://ws.cbso.nbb.be"


class NbbClient:
    def __init__(
        self,
        polite_client: PoliteClient,
        subscription_key: str,
    ) -> None:
        self._client = polite_client
        self._subscription_key = subscription_key

    def _auth_headers(self) -> dict[str, str]:
        return {
            "NBB-CBSO-Subscription-Key": self._subscription_key,
            "X-Request-Id": str(uuid.uuid4()),
            "Accept": "application/json",
        }

    async def get_references(self, kbo_number: str) -> list[ReferenceRow]:
        kbo = be_vat.compact(kbo_number)
        url = f"{_BASE_URL}/authentic/legalEntity/{kbo}/references"
        try:
            response = await self._client.get(url, headers=self._auth_headers())
        except TerminalServerError as exc:
            if exc.status == 401:
                raise NbbAuthError(
                    exc.status, exc.url, "NBB CBSO authentication failed: invalid or expired key"
                ) from exc
            if exc.status == 404:
                raise NbbNotFoundError(kbo, exc.url) from exc
            raise
        return parse_references(response.json())

    async def get_accounting_pdf(self, accounting_data_url: str) -> bytes:
        """Fetch the annual accounts PDF for one filing.

        The URL comes from ReferenceRow.accounting_data_url (AccountingDataURL in
        the /references response).  Returns raw PDF bytes.

        Raises NbbAuthError on 401, NbbNotFoundError on 404.
        """
        headers = {
            "NBB-CBSO-Subscription-Key": self._subscription_key,
            "X-Request-Id": str(uuid.uuid4()),
            "Accept": "application/pdf",
        }
        try:
            response = await self._client.get(accounting_data_url, headers=headers)
        except TerminalServerError as exc:
            if exc.status == 401:
                raise NbbAuthError(
                    exc.status, exc.url, "NBB CBSO authentication failed: invalid or expired key"
                ) from exc
            if exc.status == 404:
                raise NbbNotFoundError(accounting_data_url, exc.url) from exc
            raise
        return response.content

    async def get_accounting_data(self, kbo_number: str, reference_number: str) -> dict[str, Any]:
        """Legacy JSON path — the live API does not serve JSON here (returns 415).

        Retained for unit tests.  Use get_accounting_pdf in production.
        """
        kbo = be_vat.compact(kbo_number)
        url = (
            f"{_BASE_URL}/authentic/legalEntity/{kbo}/references/{reference_number}/accountingData"
        )
        try:
            response = await self._client.get(url, headers=self._auth_headers())
        except TerminalServerError as exc:
            if exc.status == 401:
                raise NbbAuthError(
                    exc.status, exc.url, "NBB CBSO authentication failed: invalid or expired key"
                ) from exc
            if exc.status == 404:
                raise NbbNotFoundError(kbo, exc.url) from exc
            raise
        return response.json()  # type: ignore[no-any-return]
