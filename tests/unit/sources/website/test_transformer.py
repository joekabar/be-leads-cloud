"""Unit tests for website transformer.py."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from scraper.sources.website.persons import ContactPerson
from scraper.sources.website.structured import extract_jsonld
from scraper.sources.website.transformer import ExtractedSite, site_to_observations

_GOLDEN = Path("tests/golden/website")
_NOW = datetime(2026, 5, 12, 12, 0, 0, tzinfo=UTC)
_REAL_KBO = "0439401387"
_PLACEHOLDER_KBO = "9123456789"


def _html(name: str) -> str:
    return (_GOLDEN / name).read_text(encoding="utf-8")


def _wordpress_site(kbo: str = _REAL_KBO) -> tuple[ExtractedSite, list]:
    html = _html("wordpress_local_business.html")
    structured = extract_jsonld(html)
    extracted = ExtractedSite(
        url="https://bellock.be",
        structured=structured,
        contact_page_url=None,
        persons=[],
        activity_summary="Electrical installations and maintenance in Antwerp.",
        website_age=("2017", "footer"),
        phones_found=[],
        emails_found=[],
    )
    obs = site_to_observations(kbo, extracted, uuid4(), _NOW)
    return extracted, obs


class TestSiteToObservations:
    def test_wordpress_emits_at_least_five_observations(self) -> None:
        _, obs = _wordpress_site()
        assert len(obs) >= 5

    def test_wordpress_phone_observations(self) -> None:
        _, obs = _wordpress_site()
        phone_obs = [o for o in obs if o.field == "phone"]
        assert len(phone_obs) == 2

    def test_wordpress_phone_shape(self) -> None:
        _, obs = _wordpress_site()
        phone_obs = [o for o in obs if o.field == "phone"]
        for po in phone_obs:
            assert "e164" in po.value
            assert "type" in po.value

    def test_wordpress_email_observation(self) -> None:
        _, obs = _wordpress_site()
        email_obs = [o for o in obs if o.field == "email"]
        assert len(email_obs) == 1
        assert email_obs[0].value["address"] == "info@bellock.be"

    def test_wordpress_address_observation(self) -> None:
        _, obs = _wordpress_site()
        addr_obs = [o for o in obs if o.field == "address"]
        assert len(addr_obs) == 1
        assert addr_obs[0].value["street"] == "Lange Van Bloerstraat 116"
        assert addr_obs[0].value["postal_code"] == "2060"
        assert addr_obs[0].value["city"] == "Antwerpen"

    def test_wordpress_activity_summary_observation(self) -> None:
        _, obs = _wordpress_site()
        summ = [o for o in obs if o.field == "activity_summary"]
        assert len(summ) == 1
        assert "Antwerp" in summ[0].value["text"]

    def test_wordpress_website_age_observation(self) -> None:
        _, obs = _wordpress_site()
        age_obs = [o for o in obs if o.field == "website_age"]
        assert len(age_obs) == 1
        assert age_obs[0].value["year"] == "2017"
        assert age_obs[0].value["method"] == "footer"

    def test_jsonld_phone_confidence_1_00(self) -> None:
        _, obs = _wordpress_site()
        phone_obs = [o for o in obs if o.field == "phone"]
        for po in phone_obs:
            assert po.confidence == pytest.approx(1.00)

    def test_address_confidence_0_90(self) -> None:
        _, obs = _wordpress_site()
        addr_obs = [o for o in obs if o.field == "address"]
        assert addr_obs[0].confidence == pytest.approx(0.90)

    def test_footer_age_confidence_0_70(self) -> None:
        _, obs = _wordpress_site()
        age_obs = [o for o in obs if o.field == "website_age"]
        assert age_obs[0].confidence == pytest.approx(0.70)

    def test_whois_age_confidence_1_00(self) -> None:
        html = _html("wordpress_local_business.html")
        extracted = ExtractedSite(
            url="https://bellock.be",
            structured=extract_jsonld(html),
            contact_page_url=None,
            persons=[],
            activity_summary=None,
            website_age=("2017", "whois"),
            phones_found=[],
            emails_found=[],
        )
        obs = site_to_observations(_REAL_KBO, extracted, uuid4(), _NOW)
        age_obs = [o for o in obs if o.field == "website_age"]
        assert age_obs[0].confidence == pytest.approx(1.00)

    def test_role_email_is_role_account_true(self) -> None:
        _, obs = _wordpress_site()
        email_obs = [o for o in obs if o.field == "email"]
        assert email_obs[0].value["is_role_account"] is True

    def test_personal_email_is_role_account_false(self) -> None:
        html = """<html><body>
        <script type="application/ld+json">
        {"@type":"LocalBusiness","name":"X","email":"jan.peeters@x.be"}
        </script></body></html>"""
        from scraper.sources.website.structured import extract_jsonld as ejl

        extracted = ExtractedSite(
            url="https://x.be",
            structured=ejl(html),
            contact_page_url=None,
            persons=[],
            activity_summary=None,
            website_age=(None, "none"),
            phones_found=[],
            emails_found=[],
        )
        obs = site_to_observations(_REAL_KBO, extracted, uuid4(), _NOW)
        email_obs = [o for o in obs if o.field == "email"]
        assert email_obs[0].value["is_role_account"] is False

    def test_kbo_propagated_real(self) -> None:
        _, obs = _wordpress_site(_REAL_KBO)
        assert all(o.kbo_number == _REAL_KBO for o in obs)

    def test_kbo_propagated_placeholder(self) -> None:
        _, obs = _wordpress_site(_PLACEHOLDER_KBO)
        assert all(o.kbo_number == _PLACEHOLDER_KBO for o in obs)

    def test_source_is_website(self) -> None:
        _, obs = _wordpress_site()
        assert all(o.source == "website" for o in obs)

    def test_person_microdata_confidence_0_85(self) -> None:
        html = _html("wordpress_local_business.html")
        persons = [ContactPerson(name="Jan Peeters", role="Directeur", source="microdata")]
        extracted = ExtractedSite(
            url="https://bellock.be",
            structured=extract_jsonld(html),
            contact_page_url=None,
            persons=persons,
            activity_summary=None,
            website_age=(None, "none"),
            phones_found=[],
            emails_found=[],
        )
        obs = site_to_observations(_REAL_KBO, extracted, uuid4(), _NOW)
        person_obs = [o for o in obs if o.field == "function_holder"]
        assert len(person_obs) == 1
        assert person_obs[0].confidence == pytest.approx(0.85)

    def test_person_heuristic_confidence_0_55(self) -> None:
        html = _html("wordpress_local_business.html")
        persons = [ContactPerson(name="Jean Dupont", role="gérant", source="heuristic")]
        extracted = ExtractedSite(
            url="https://bellock.be",
            structured=extract_jsonld(html),
            contact_page_url=None,
            persons=persons,
            activity_summary=None,
            website_age=(None, "none"),
            phones_found=[],
            emails_found=[],
        )
        obs = site_to_observations(_REAL_KBO, extracted, uuid4(), _NOW)
        person_obs = [o for o in obs if o.field == "function_holder"]
        assert person_obs[0].confidence == pytest.approx(0.55)

    def test_heuristic_phone_confidence_0_60(self) -> None:
        extracted = ExtractedSite(
            url="https://example.be",
            structured=[],
            contact_page_url=None,
            persons=[],
            activity_summary=None,
            website_age=(None, "none"),
            phones_found=[("03 555 12 12", 0.60)],
            emails_found=[],
        )
        obs = site_to_observations(_REAL_KBO, extracted, uuid4(), _NOW)
        phone_obs = [o for o in obs if o.field == "phone"]
        assert phone_obs[0].confidence == pytest.approx(0.60)

    def test_no_website_age_when_none(self) -> None:
        extracted = ExtractedSite(
            url="https://example.be",
            structured=[],
            contact_page_url=None,
            persons=[],
            activity_summary=None,
            website_age=(None, "none"),
            phones_found=[],
            emails_found=[],
        )
        obs = site_to_observations(_REAL_KBO, extracted, uuid4(), _NOW)
        assert not any(o.field == "website_age" for o in obs)

    def test_invalid_phone_skipped(self) -> None:
        extracted = ExtractedSite(
            url="https://example.be",
            structured=[],
            contact_page_url=None,
            persons=[],
            activity_summary=None,
            website_age=(None, "none"),
            phones_found=[("not-a-phone", 0.85), ("03 555 12 12", 0.85)],
            emails_found=[],
        )
        obs = site_to_observations(_REAL_KBO, extracted, uuid4(), _NOW)
        phone_obs = [o for o in obs if o.field == "phone"]
        assert len(phone_obs) == 1
