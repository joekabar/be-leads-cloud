"""DuckDuckGo search client — wraps the synchronous ddgs library in asyncio.to_thread."""

from __future__ import annotations

import asyncio

import structlog

from scraper.lib.errors import ScraperError

logger = structlog.get_logger()

# Lazy-safe: import the exception class at module load so isinstance() works at runtime,
# but fall back to a private stub if ddgs is not yet installed.
try:
    from ddgs.exceptions import RatelimitException as _DdgsRateLimitException
except ImportError:  # pragma: no cover

    class _DdgsRateLimitException(Exception):  # type: ignore[no-redef]  # noqa: N818
        pass


class DdgRateLimitedError(ScraperError):
    """DDG rate limited after one retry; caller should skip this query."""


class DdgClient:
    def __init__(self, region: str = "be-nl") -> None:
        self._region = region

    async def search(
        self,
        query: str,
        *,
        max_results: int = 10,
    ) -> list[dict[str, str]]:
        """Run a DDG text search in a thread pool.

        Returns a list of ``{"title", "href", "body"}`` dicts.

        Raises:
            DdgRateLimitedError: if DDG rate-limits us on both the initial attempt and the retry.
        """
        region = self._region

        def _run() -> list[dict[str, str]]:
            from ddgs import DDGS

            ddg = DDGS()
            results = ddg.text(
                query,
                max_results=max_results,
                region=region,
                safesearch="moderate",
            )
            return list(results) if results else []

        try:
            return await asyncio.to_thread(_run)
        except _DdgsRateLimitException:
            logger.warning("ddg_rate_limited_retry", query=query)
            await asyncio.sleep(60)
            try:
                return await asyncio.to_thread(_run)
            except _DdgsRateLimitException as exc:
                raise DdgRateLimitedError("DuckDuckGo rate limited after retry") from exc
