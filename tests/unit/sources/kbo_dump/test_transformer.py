from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest

from scraper.sources.kbo_dump.parser import (
    ActivityRow,
    AddressRow,
    ContactRow,
    DenominationRow,
    EnterpriseRow,
)
from scraper.sources.kbo_dump.transformer import (
    activity_to_observation,
    address_to_observation,
    contact_to_observation,
    denomination_to_observation,
    enterprise_to_observations,
)

_RUN_ID = uuid4()
_OBS_AT = datetime(2026, 4, 15, tzinfo=UTC)
_KBO = "0439401387"


# ── enterprise_to_observations ───────────────────────────────────────────────


def test_enterprise_produces_founding_date_status_and_legal_form() -> None:
    row = EnterpriseRow(
        enterprise_number=_KBO,
        status="AC",
        juridical_situation="000",
        type_of_enterprise="1",
        juridical_form="014",
        juridical_form_cac="014",
        start_date=date(1989, 12, 28),
    )
    obs = enterprise_to_observations(row, _RUN_ID, _OBS_AT)
    assert len(obs) == 3
    fields = {o.field for o in obs}
    assert fields == {"founding_date", "status", "legal_form"}


def test_enterprise_legal_form_nv_is_large() -> None:
    row = EnterpriseRow(
        enterprise_number=_KBO,
        status="AC",
        juridical_situation="000",
        type_of_enterprise="1",
        juridical_form="014",
        juridical_form_cac=None,
        start_date=None,
    )
    obs = enterprise_to_observations(row, _RUN_ID, _OBS_AT)
    lf = next(o for o in obs if o.field == "legal_form")
    assert lf.value["code"] == "014"
    assert lf.value["label"] == "NV"
    assert lf.value["size_category"] == "Large"
    assert lf.confidence == 1.00


def test_enterprise_legal_form_natural_person_is_solo() -> None:
    row = EnterpriseRow(
        enterprise_number=_KBO,
        status="AC",
        juridical_situation="000",
        type_of_enterprise="0",
        juridical_form="010",
        juridical_form_cac=None,
        start_date=None,
    )
    obs = enterprise_to_observations(row, _RUN_ID, _OBS_AT)
    lf = next(o for o in obs if o.field == "legal_form")
    assert lf.value["size_category"] == "Solo"
    assert lf.value["label"] == "Eenmanszaak"


def test_enterprise_legal_form_bv_is_sme() -> None:
    row = EnterpriseRow(
        enterprise_number=_KBO,
        status="AC",
        juridical_situation="000",
        type_of_enterprise="1",
        juridical_form="017",
        juridical_form_cac=None,
        start_date=None,
    )
    obs = enterprise_to_observations(row, _RUN_ID, _OBS_AT)
    lf = next(o for o in obs if o.field == "legal_form")
    assert lf.value["size_category"] == "SME"
    assert lf.value["label"] == "BV"


def test_enterprise_no_juridical_form_omits_legal_form_obs() -> None:
    row = EnterpriseRow(
        enterprise_number=_KBO,
        status="AC",
        juridical_situation="000",
        type_of_enterprise="1",
        juridical_form=None,
        juridical_form_cac=None,
        start_date=None,
    )
    obs = enterprise_to_observations(row, _RUN_ID, _OBS_AT)
    assert not any(o.field == "legal_form" for o in obs)


def test_enterprise_founding_date_iso() -> None:
    row = EnterpriseRow(
        enterprise_number=_KBO,
        status="AC",
        juridical_situation="000",
        type_of_enterprise="1",
        juridical_form=None,
        juridical_form_cac=None,
        start_date=date(1989, 12, 28),
    )
    obs = enterprise_to_observations(row, _RUN_ID, _OBS_AT)
    fd = next(o for o in obs if o.field == "founding_date")
    assert fd.value == {"iso": "1989-12-28"}
    assert fd.confidence == 1.00
    assert fd.source == "kbo_dump"


def test_enterprise_status_active() -> None:
    row = EnterpriseRow(
        enterprise_number=_KBO,
        status="AC",
        juridical_situation="000",
        type_of_enterprise="1",
        juridical_form=None,
        juridical_form_cac=None,
        start_date=None,
    )
    obs = enterprise_to_observations(row, _RUN_ID, _OBS_AT)
    # No founding_date when start_date is None
    assert len(obs) == 1
    assert obs[0].field == "status"
    assert obs[0].value == {"value": "active"}


def test_enterprise_no_start_date_skips_founding() -> None:
    row = EnterpriseRow(
        enterprise_number=_KBO,
        status="AC",
        juridical_situation="000",
        type_of_enterprise="2",
        juridical_form=None,
        juridical_form_cac=None,
        start_date=None,
    )
    obs = enterprise_to_observations(row, _RUN_ID, _OBS_AT)
    assert not any(o.field == "founding_date" for o in obs)


# ── denomination_to_observation ──────────────────────────────────────────────


def test_denomination_legal_name_001() -> None:
    row = DenominationRow(
        entity_number=_KBO,
        language="NL",
        type_of_denomination="001",
        denomination="Bellock NV",
    )
    obs = denomination_to_observation(row, _RUN_ID, _OBS_AT)
    assert obs is not None
    assert obs.field == "name"
    assert obs.value == {"text": "Bellock NV", "lang": "nl"}
    assert obs.confidence == 1.00


def test_denomination_abbreviation_002() -> None:
    row = DenominationRow(
        entity_number=_KBO,
        language="NL",
        type_of_denomination="002",
        denomination="Bellock",
    )
    obs = denomination_to_observation(row, _RUN_ID, _OBS_AT)
    assert obs is not None
    assert obs.value["type"] == "abbreviation"
    assert obs.confidence == 0.90


def test_denomination_commercial_003() -> None:
    row = DenominationRow(
        entity_number=_KBO,
        language="NL",
        type_of_denomination="003",
        denomination="Bellock Locks",
    )
    obs = denomination_to_observation(row, _RUN_ID, _OBS_AT)
    assert obs is not None
    assert obs.value["type"] == "commercial"
    assert obs.confidence == 0.95


def test_denomination_french_language() -> None:
    row = DenominationRow(
        entity_number="1000000021",
        language="FR",
        type_of_denomination="001",
        denomination="Société Moderne SA",
    )
    obs = denomination_to_observation(row, _RUN_ID, _OBS_AT)
    assert obs is not None
    assert obs.value["lang"] == "fr"


def test_denomination_unknown_type_skipped() -> None:
    row = DenominationRow(
        entity_number=_KBO,
        language="NL",
        type_of_denomination="999",
        denomination="Ignored",
    )
    assert denomination_to_observation(row, _RUN_ID, _OBS_AT) is None


# ── address_to_observation ───────────────────────────────────────────────────


def test_address_nl_fields() -> None:
    row = AddressRow(
        entity_number=_KBO,
        type_of_address="REGO",
        zipcode="2060",
        municipality_nl="Antwerpen",
        municipality_fr="Anvers",
        street_nl="Lange Van Bloerstraat",
        street_fr="Rue Lange Van Bloer",
        house_number="116",
        box=None,
    )
    obs = address_to_observation(row, _RUN_ID, _OBS_AT)
    assert obs is not None
    assert obs.field == "address"
    assert obs.value["street"] == "Lange Van Bloerstraat 116"
    assert obs.value["postal_code"] == "2060"
    assert obs.value["city"] == "Antwerpen"
    assert obs.value["country"] == "BE"
    assert obs.confidence == 0.95


def test_address_fr_fallback_when_nl_empty() -> None:
    row = AddressRow(
        entity_number="0123456749",
        type_of_address="REGO",
        zipcode="4000",
        municipality_nl=None,
        municipality_fr="Liège",
        street_nl=None,
        street_fr="Rue de la Régence",
        house_number="5",
        box=None,
    )
    obs = address_to_observation(row, _RUN_ID, _OBS_AT)
    assert obs is not None
    assert obs.value["street"] == "Rue de la Régence 5"
    assert obs.value["city"] == "Liège"


def test_address_no_street_returns_none() -> None:
    row = AddressRow(
        entity_number="0200379531",
        type_of_address="REGO",
        zipcode="9000",
        municipality_nl="Gent",
        municipality_fr="Gand",
        street_nl=None,
        street_fr=None,
        house_number=None,
        box=None,
    )
    assert address_to_observation(row, _RUN_ID, _OBS_AT) is None


def test_address_no_house_number() -> None:
    row = AddressRow(
        entity_number=_KBO,
        type_of_address="REGO",
        zipcode="1000",
        municipality_nl="Brussel",
        municipality_fr="Bruxelles",
        street_nl="Wetstraat",
        street_fr=None,
        house_number=None,
        box=None,
    )
    obs = address_to_observation(row, _RUN_ID, _OBS_AT)
    assert obs is not None
    assert obs.value["street"] == "Wetstraat"


# ── contact_to_observation ───────────────────────────────────────────────────


def test_contact_valid_antwerpen_landline() -> None:
    row = ContactRow(entity_number=_KBO, contact_type="TEL", value="03 236 13 06")
    obs = contact_to_observation(row, _RUN_ID, _OBS_AT)
    assert obs is not None
    assert obs.field == "phone"
    assert obs.value["e164"] == "+3232361306"
    assert obs.value["type"] == "fixed_line"
    assert obs.confidence == 0.95


def test_contact_liege_landline() -> None:
    row = ContactRow(entity_number="0123456749", contact_type="TEL", value="04 220 11 22")
    obs = contact_to_observation(row, _RUN_ID, _OBS_AT)
    assert obs is not None
    assert obs.value["type"] == "fixed_line"
    assert obs.value["region"] is not None


def test_contact_mobile() -> None:
    row = ContactRow(entity_number="1000000021", contact_type="TEL", value="0474 12 34 56")
    obs = contact_to_observation(row, _RUN_ID, _OBS_AT)
    assert obs is not None
    assert obs.value["type"] == "mobile"


def test_contact_invalid_phone_returns_none() -> None:
    row = ContactRow(entity_number="0200379531", contact_type="TEL", value="123")
    assert contact_to_observation(row, _RUN_ID, _OBS_AT) is None


def test_contact_email_role_account() -> None:
    row = ContactRow(entity_number=_KBO, contact_type="EMAIL", value="info@example.be")
    obs = contact_to_observation(row, _RUN_ID, _OBS_AT)
    assert obs is not None
    assert obs.field == "email"
    assert obs.value["address"] == "info@example.be"
    assert obs.value["is_role_account"] is True


def test_contact_email_non_role() -> None:
    row = ContactRow(entity_number="0123456749", contact_type="EMAIL", value="contact@natural.be")
    obs = contact_to_observation(row, _RUN_ID, _OBS_AT)
    assert obs is not None
    # "contact" IS in _ROLE_ACCOUNTS
    assert obs.value["is_role_account"] is True


def test_contact_email_whitespace_stripped() -> None:
    row = ContactRow(entity_number="0800000075", contact_type="EMAIL", value=" info@modern.be")
    obs = contact_to_observation(row, _RUN_ID, _OBS_AT)
    assert obs is not None
    assert obs.value["address"] == "info@modern.be"


def test_contact_website() -> None:
    row = ContactRow(entity_number="1000000021", contact_type="WEB", value="https://example.be")
    obs = contact_to_observation(row, _RUN_ID, _OBS_AT)
    assert obs is not None
    assert obs.field == "website"
    assert obs.value["url"] == "https://example.be"
    assert obs.value["tld"] == "be"


def test_contact_unknown_type_returns_none() -> None:
    row = ContactRow(entity_number=_KBO, contact_type="FAX", value="03 236 13 07")
    assert contact_to_observation(row, _RUN_ID, _OBS_AT) is None


# ── activity_to_observation ──────────────────────────────────────────────────


def test_activity_produces_nace_code() -> None:
    row = ActivityRow(
        entity_number=_KBO,
        activity_group="MAIN",
        nace_version="2008",
        nace_code="43.211",
        classification="MAIN",
    )
    obs = activity_to_observation(row, _RUN_ID, _OBS_AT)
    assert obs is not None
    assert obs.field == "nace_code"
    assert obs.value == {"code": "43.211", "version": "2008"}
    assert obs.confidence == 0.95


def test_activity_nace_2025() -> None:
    row = ActivityRow(
        entity_number=_KBO,
        activity_group="MAIN",
        nace_version="2025",
        nace_code="43.211",
        classification="MAIN",
    )
    obs = activity_to_observation(row, _RUN_ID, _OBS_AT)
    assert obs is not None
    assert obs.value["version"] == "2025"


@pytest.mark.parametrize("classification", ["MAIN", "SECO", "AUXI"])
def test_activity_all_classifications_produce_obs(classification: str) -> None:
    row = ActivityRow(
        entity_number=_KBO,
        activity_group=classification,
        nace_version="2008",
        nace_code="43.211",
        classification=classification,
    )
    assert activity_to_observation(row, _RUN_ID, _OBS_AT) is not None


# ── error / defensive paths ──────────────────────────────────────────────────


def test_enterprise_invalid_kbo_returns_empty() -> None:
    row = EnterpriseRow(
        enterprise_number="0000000000",  # fails stdnum checksum
        status="AC",
        juridical_situation="000",
        type_of_enterprise="1",
        juridical_form=None,
        juridical_form_cac=None,
        start_date=None,
    )
    # Observation model will raise ValueError for invalid KBO
    result = enterprise_to_observations(row, _RUN_ID, _OBS_AT)
    assert result == []


def test_denomination_invalid_kbo_returns_none() -> None:
    row = DenominationRow(
        entity_number="0000000000",
        language="NL",
        type_of_denomination="001",
        denomination="Bad KBO",
    )
    assert denomination_to_observation(row, _RUN_ID, _OBS_AT) is None


def test_address_invalid_kbo_returns_none() -> None:
    row = AddressRow(
        entity_number="0000000000",
        type_of_address="REGO",
        zipcode="1000",
        municipality_nl="Brussel",
        municipality_fr=None,
        street_nl="Wetstraat",
        street_fr=None,
        house_number="16",
        box=None,
    )
    assert address_to_observation(row, _RUN_ID, _OBS_AT) is None


def test_contact_empty_value_returns_none() -> None:
    row = ContactRow(entity_number=_KBO, contact_type="TEL", value="   ")
    assert contact_to_observation(row, _RUN_ID, _OBS_AT) is None


def test_contact_email_invalid_kbo_returns_none() -> None:
    row = ContactRow(entity_number="0000000000", contact_type="EMAIL", value="info@example.be")
    assert contact_to_observation(row, _RUN_ID, _OBS_AT) is None


def test_contact_website_invalid_kbo_returns_none() -> None:
    row = ContactRow(entity_number="0000000000", contact_type="WEB", value="https://example.be")
    assert contact_to_observation(row, _RUN_ID, _OBS_AT) is None


def test_activity_invalid_kbo_returns_none() -> None:
    row = ActivityRow(
        entity_number="0000000000",
        activity_group="MAIN",
        nace_version="2008",
        nace_code="43.211",
        classification="MAIN",
    )
    assert activity_to_observation(row, _RUN_ID, _OBS_AT) is None


def test_contact_tel_valid_phone_invalid_kbo_returns_none() -> None:
    """Valid phone but invalid KBO → Observation creation raises ValueError → None."""
    row = ContactRow(entity_number="0000000000", contact_type="TEL", value="03 236 13 06")
    assert contact_to_observation(row, _RUN_ID, _OBS_AT) is None
