"""Unit tests for goudengids parser.py — all HTML from golden fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from scraper.sources.goudengids.parser import is_empty_results_page, parse_listing_page

_GOLDEN = Path("tests/golden/goudengids")


@pytest.fixture()
def antwerpen_html() -> str:
    return (_GOLDEN / "listing_antwerpen_electriciens_page1.html").read_text(encoding="utf-8")


@pytest.fixture()
def brugge_html() -> str:
    return (_GOLDEN / "listing_brugge_bakkers_page2.html").read_text(encoding="utf-8")


@pytest.fixture()
def no_results_html() -> str:
    return (_GOLDEN / "listing_no_results.html").read_text(encoding="utf-8")


@pytest.fixture()
def french_html() -> str:
    return (_GOLDEN / "listing_french_liege_plombiers.html").read_text(encoding="utf-8")


class TestParseListingPage:
    def test_antwerpen_returns_12_cards(self, antwerpen_html: str) -> None:
        cards = parse_listing_page(antwerpen_html)
        assert len(cards) == 12

    def test_bellock_card_exact_match(self, antwerpen_html: str) -> None:
        cards = parse_listing_page(antwerpen_html)
        bellock = next(c for c in cards if "Bellock" in c.name)

        assert bellock.name == "Bellock"
        assert bellock.phones[0] == "+3232361306"
        assert bellock.website is not None
        assert bellock.website.startswith("https://www.bellock.be")
        assert "utm_source" not in (bellock.website or "")
        assert bellock.address_street == "Lange Van Bloerstraat 116"
        assert bellock.address_postal_code == "2060"
        assert bellock.address_city == "Antwerpen"
        assert bellock.description == "Electrotechnical installer since 1989"

    def test_bellock_detail_url_is_absolute(self, antwerpen_html: str) -> None:
        cards = parse_listing_page(antwerpen_html)
        bellock = next(c for c in cards if "Bellock" in c.name)
        assert bellock.detail_url.startswith("https://www.goudengids.be/")

    def test_multi_phone_card_has_two_phones(self, antwerpen_html: str) -> None:
        cards = parse_listing_page(antwerpen_html)
        multi = next(c for c in cards if "MultiPhone" in c.name)
        assert len(multi.phones) == 2
        assert multi.phones[0] == "+3232445566"
        assert multi.phones[1] == "+32478112233"

    def test_no_website_card_has_none_website(self, antwerpen_html: str) -> None:
        cards = parse_listing_page(antwerpen_html)
        no_web = next(c for c in cards if "NoWebsite" in c.name)
        assert no_web.website is None

    def test_email_card_has_email(self, antwerpen_html: str) -> None:
        cards = parse_listing_page(antwerpen_html)
        email_card = next(c for c in cards if "EmailCard" in c.name)
        assert email_card.email == "info@emailcard.be"

    def test_bad_phone_card_preserved_raw(self, antwerpen_html: str) -> None:
        """Parser preserves raw phone strings — validation is the transformer's job."""
        cards = parse_listing_page(antwerpen_html)
        bad = next(c for c in cards if "BadPhone" in c.name)
        assert "123" in bad.phones

    def test_no_address_street_is_none(self, antwerpen_html: str) -> None:
        cards = parse_listing_page(antwerpen_html)
        no_addr = next(c for c in cards if "NoAddress" in c.name)
        assert no_addr.address_street is None
        assert no_addr.address_postal_code == "2050"

    def test_brugge_returns_6_cards(self, brugge_html: str) -> None:
        cards = parse_listing_page(brugge_html)
        assert len(cards) == 6

    def test_empty_results_returns_no_cards(self, no_results_html: str) -> None:
        cards = parse_listing_page(no_results_html)
        assert cards == []

    def test_french_fixture_parses_correctly(self, french_html: str) -> None:
        cards = parse_listing_page(french_html, domain="pagesdor.be")
        assert len(cards) == 4
        dumont = next(c for c in cards if "Dumont" in c.name)
        assert dumont.address_street == "Rue de la Régence 14"
        assert dumont.address_postal_code == "4000"
        assert dumont.address_city == "Liège"

    def test_french_card_detail_url_uses_domain(self, french_html: str) -> None:
        cards = parse_listing_page(french_html, domain="pagesdor.be")
        assert all(c.detail_url.startswith("https://www.pagesdor.be/") for c in cards)

    def test_french_multi_phone(self, french_html: str) -> None:
        cards = parse_listing_page(french_html, domain="pagesdor.be")
        aqua = next(c for c in cards if "Aqua" in c.name)
        assert len(aqua.phones) == 2

    def test_raw_card_html_is_non_empty(self, antwerpen_html: str) -> None:
        cards = parse_listing_page(antwerpen_html)
        assert all(c.raw_card_html for c in cards)

    def test_website_query_string_stripped(self, antwerpen_html: str) -> None:
        cards = parse_listing_page(antwerpen_html)
        for card in cards:
            if card.website:
                assert "utm_source" not in card.website
                assert "utm_medium" not in card.website


class TestIsEmptyResultsPage:
    def test_no_results_page_detected(self, no_results_html: str) -> None:
        assert is_empty_results_page(no_results_html) is True

    def test_antwerpen_not_empty(self, antwerpen_html: str) -> None:
        assert is_empty_results_page(antwerpen_html) is False

    def test_brugge_not_empty(self, brugge_html: str) -> None:
        assert is_empty_results_page(brugge_html) is False

    def test_inline_geen_resultaten_text(self) -> None:
        html = "<html><body><p>geen resultaten gevonden</p></body></html>"
        assert is_empty_results_page(html) is True

    def test_french_aucun_resultat(self) -> None:
        html = "<html><body><p>aucun résultat trouvé</p></body></html>"
        assert is_empty_results_page(html) is True
