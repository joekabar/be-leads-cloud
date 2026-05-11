"""Playwright-based Imperva cookie warm-up for goudengids.be / pagesdor.be.

Two-phase pattern:
  1. Render the homepage with headless Chromium to solve the Imperva challenge.
  2. Return cookies matching ^(incap_ses_|visid_incap_|nlbi_|reese84) for httpx injection.

See .claude/skills/goudengids-listing/references/imperva-bypass.md for full details.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

from scraper.lib.errors import ScraperError

if TYPE_CHECKING:
    from playwright.async_api import Browser

# Module-level import so tests can patch scraper.sources.goudengids.warmup.async_playwright.
from playwright.async_api import async_playwright

logger = structlog.get_logger()

_COOKIE_RE = re.compile(r"^(incap_ses_|visid_incap_|nlbi_|reese84)")
_HOMEPAGE_SELECTOR = (
    'input[type="search"], .search-input, form[action*="zoeken"], form[action*="recherche"]'
)
_CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
)


class WarmupFailedError(ScraperError):
    """Playwright warmup failed — could not obtain Imperva cookies."""


@dataclass(frozen=True, slots=True)
class WarmupResult:
    cookies: dict[str, str]
    obtained_at: datetime
    ttl_minutes: int = 25


def is_expired(result: WarmupResult, *, now: datetime | None = None) -> bool:
    t = now if now is not None else datetime.now(tz=UTC)
    age_minutes = (t - result.obtained_at).total_seconds() / 60.0
    return age_minutes >= result.ttl_minutes


async def _navigate_and_harvest(
    browser: Browser,
    url: str,
    timeout_ms: int,
) -> list[dict[str, Any]]:
    """Open a fresh browser context, navigate, and return raw cookie dicts."""
    context = await browser.new_context(
        user_agent=_CHROME_UA,
        locale="nl-BE",
        viewport={"width": 1280, "height": 720},
    )
    await context.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    page = await context.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        await page.wait_for_selector(_HOMEPAGE_SELECTOR, timeout=timeout_ms)
        raw: list[dict[str, Any]] = [dict(c) for c in await context.cookies()]
        return raw
    finally:
        await context.close()


async def warmup_cookies(
    domain: str = "goudengids.be",
    *,
    timeout_s: float = 30.0,
) -> WarmupResult:
    """Render the homepage with Playwright and harvest Imperva session cookies.

    Retries navigation once on failure before raising WarmupFailedError.
    Browser-launch errors (playwright not installed, etc.) bubble up directly.
    """
    url = f"https://www.{domain}/"
    timeout_ms = int(timeout_s * 1000)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        raw_cookies: list[dict[str, Any]] = []
        success = False
        last_exc: BaseException | None = None
        try:
            for _ in range(2):
                try:
                    raw_cookies = await _navigate_and_harvest(browser, url, timeout_ms)
                    success = True
                    break
                except Exception as exc:
                    last_exc = exc
        finally:
            await browser.close()

    if not success:
        raise WarmupFailedError(
            f"Warmup navigation failed for {domain} after 2 attempts"
        ) from last_exc

    imperva = {
        c["name"]: c["value"]
        for c in raw_cookies
        if isinstance(c.get("name"), str) and _COOKIE_RE.match(c["name"])
    }
    logger.bind(domain=domain).info(
        "warmup_cookies_obtained",
        cookie_names=sorted(imperva.keys()),
        count=len(imperva),
    )
    return WarmupResult(cookies=imperva, obtained_at=datetime.now(tz=UTC))
