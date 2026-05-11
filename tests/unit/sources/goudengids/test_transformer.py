"""Unit tests for goudengids transformer.py."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from scraper.sources.goudengids.parser import ListingCardRow, parse_listing_page
from scraper.sources.goudengids.transformer import card_to_observations, make_placeholder_kbo

_GOLDEN = Path("tests/golden/goudengids")
_NOW = datetime(2026, 5, 11, 12, 0, 0, tzinfo=UTC)


def _bellock_card() -> ListingCardRow:
    html = (_GOLDEN / "listing_antwerpen_electriciens_page1.html").read_text(encoding="utf-8")
    cards = parse_listing_page(html)
    return next(c for c in cards if "Bellock" in c.name)


def _bad_phone_card() -> ListingCardRow:
    html = (_GOLDEN / "listing_antwerpen_electriciens_page1.html").read_text(encoding="utf-8")
    cards = parse_listing_page(html)
    return next(c for c in cards if "BadPhone" in c.name)


def _no_address_card() -> ListingCardRow:
    html = (_GOLDEN / "listing_antwerpen_electriciens_page1.html").read_text(encoding="utf-8")
    cards = parse_listing_page(html)
    return next(c for c in cards if "NoAddress" in c.name)


class TestMakePlaceholderKbo:
    def test_starts_with_9(self) -> None:
        kbo = make_placeholder_kbo("Bellock", "2060")
        assert kbo.startswith("9")

    def test_is_10_digits(self) -> None:
        kbo = make_placeholder_kbo("Bellock", "2060")
        assert len(kbo) == 10
        assert kbo.isdigit()

    def test_deterministic(self) -> None:
        kbo1 = make_placeholder_kbo("Bellock", "2060")
        kbo2 = make_placeholder_kbo("Bellock", "2060")
        assert kbo1 == kbo2

    def test_different_names_different_kbo(self) -> None:
        kbo1 = make_placeholder_kbo("Company A", "2000")
        kbo2 = make_placeholder_kbo("Company B", "2000")
        assert kbo1 != kbo2

    def test_different_postal_different_kbo(self) -> None:
        kbo1 = make_placeholder_kbo("Same Company", "2000")
        kbo2 = make_placeholder_kbo("Same Company", "9000")
        assert kbo1 != kbo2

    def test_none_postal_code(self) -> None:
        kbo = make_placeholder_kbo("No Address Co", None)
        assert kbo.startswith("9")
        assert len(kbo) == 10


class TestCardToObservations:
    def test_bellock_emits_four_observations(self) -> None:
        card = _bellock_card()
        obs = card_to_observations(card, uuid4(), _NOW)
        fields = {o.field for o in obs}
        assert fields == {"name", "phone", "website", "address"}

    def test_bellock_kbo_starts_with_9(self) -> None:
        card = _bellock_card()
        obs = card_to_observations(card, uuid4(), _NOW)
        assert all(o.kbo_number.startswith("9") for o in obs)

    def test_bellock_kbo_consistent_across_obs(self) -> None:
        card = _bellock_card()
        obs = card_to_observations(card, uuid4(), _NOW)
        kbos = {o.kbo_number for o in obs}
        assert len(kbos) == 1

    def test_bellock_kbo_deterministic(self) -> None:
        card = _bellock_card()
        obs1 = card_to_observations(card, uuid4(), _NOW)
        obs2 = card_to_observations(card, uuid4(), _NOW)
        assert obs1[0].kbo_number == obs2[0].kbo_number

    def test_bellock_phone_is_validated_shape(self) -> None:
        card = _bellock_card()
        obs = card_to_observations(card, uuid4(), _NOW)
        phone_obs = next(o for o in obs if o.field == "phone")
        assert "e164" in phone_obs.value
        assert phone_obs.value["e164"] == "+3232361306"
        assert phone_obs.value["type"] == "fixed_line"

    def test_bellock_source_is_goudengids(self) -> None:
        card = _bellock_card()
        obs = card_to_observations(card, uuid4(), _NOW)
        assert all(o.source == "goudengids" for o in obs)

    def test_bellock_confidence_values(self) -> None:
        card = _bellock_card()
        obs = card_to_observations(card, uuid4(), _NOW)
        conf_map = {o.field: o.confidence for o in obs}
        assert conf_map["name"] == pytest.approx(0.85)
        assert conf_map["phone"] == pytest.approx(0.85)
        assert conf_map["website"] == pytest.approx(0.85)
        assert conf_map["address"] == pytest.approx(0.80)

    def test_bellock_address_shape(self) -> None:
        card = _bellock_card()
        obs = card_to_observations(card, uuid4(), _NOW)
        addr = next(o for o in obs if o.field == "address")
        assert addr.value["street"] == "Lange Van Bloerstraat 116"
        assert addr.value["postal_code"] == "2060"
        assert addr.value["city"] == "Antwerpen"
        assert addr.value["country"] == "BE"

    def test_bad_phone_skipped_other_obs_still_emitted(self) -> None:
        card = _bad_phone_card()
        obs = card_to_observations(card, uuid4(), _NOW)
        fields = {o.field for o in obs}
        assert "phone" not in fields
        assert "name" in fields

    def test_no_address_card_skips_address_obs(self) -> None:
        card = _no_address_card()
        obs = card_to_observations(card, uuid4(), _NOW)
        fields = {o.field for o in obs}
        assert "address" not in fields
        assert "name" in fields

    def test_placeholder_kbos_unique_across_all_cards(self) -> None:
        html = (_GOLDEN / "listing_antwerpen_electriciens_page1.html").read_text(encoding="utf-8")
        cards = parse_listing_page(html)
        kbos = [make_placeholder_kbo(c.name, c.address_postal_code) for c in cards]
        assert len(kbos) == len(set(kbos)), "placeholder KBO collision in fixture"

    def test_email_card_emits_email_obs(self) -> None:
        html = (_GOLDEN / "listing_antwerpen_electriciens_page1.html").read_text(encoding="utf-8")
        cards = parse_listing_page(html)
        email_card = next(c for c in cards if "EmailCard" in c.name)
        obs = card_to_observations(email_card, uuid4(), _NOW)
        fields = {o.field for o in obs}
        assert "email" in fields
        email_obs = next(o for o in obs if o.field == "email")
        assert email_obs.value["address"] == "info@emailcard.be"

    def test_run_id_propagated(self) -> None:
        card = _bellock_card()
        run_id = uuid4()
        obs = card_to_observations(card, run_id, _NOW)
        assert all(o.run_id == run_id for o in obs)
