"""Integration tests for be-leads-discover-goudengids CLI."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from scraper.sources.goudengids.ingester import load_valid_sectors
from tests.integration.sources.goudengids.conftest import StubBrowserFetcher

pytestmark = pytest.mark.integration

_GOLDEN = Path("tests/golden/goudengids")


def _page_html(name: str) -> str:
    return (_GOLDEN / name).read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_cli_valid_run_exits_0(
    clean_pool,  # type: ignore[no-untyped-def]
    test_db_dsn: str,
) -> None:
    """CLI _run with valid sector/city completes without error."""
    from scraper.sources.goudengids.cli import _run

    stub = StubBrowserFetcher(
        {
            ("elektriciens", "antwerpen", 1): _page_html(
                "listing_antwerpen_electriciens_page1.html"
            ),
        }
    )
    with patch("scraper.sources.goudengids.fetcher.BrowserListingFetcher", return_value=stub):
        await _run(
            sector_slug="elektriciens",
            city_slug="antwerpen",
            lang="nl",
            max_pages=2,
            skip_recent_hours=0,
            database_url=test_db_dsn,
        )


def test_cli_invalid_sector_exits_2() -> None:
    """Invalid sector slug → sys.exit(2)."""
    from scraper.sources.goudengids.cli import cli_main

    with (
        pytest.raises(SystemExit) as exc_info,
        patch(
            "sys.argv",
            ["be-leads-discover-goudengids", "--sector", "NONEXISTENT", "--city", "antwerpen"],
        ),
    ):
        cli_main()

    assert exc_info.value.code == 2


def test_cli_invalid_sector_lists_valid_slugs(capsys) -> None:  # type: ignore[no-untyped-def]
    """Error message must include valid sector slugs."""
    from scraper.sources.goudengids.cli import cli_main

    valid = load_valid_sectors()

    with (
        pytest.raises(SystemExit),
        patch("sys.argv", ["be-leads-discover-goudengids", "--sector", "BOGUS", "--city", "gent"]),
    ):
        cli_main()

    captured = capsys.readouterr()
    for slug in list(valid.keys())[:3]:
        assert slug in captured.err
