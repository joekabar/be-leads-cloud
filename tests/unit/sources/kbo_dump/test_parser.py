from __future__ import annotations

import zipfile
from datetime import date
from pathlib import Path

import pytest

from scraper.sources.kbo_dump.parser import (
    detect_extract_type,
    iter_activities,
    iter_addresses,
    iter_contacts,
    iter_denominations,
    iter_enterprises,
    parse_meta,
)

_MINI = Path("tests/golden/kbo_dump/synthetic_mini")


@pytest.fixture(scope="module")
def full_zip(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("zips") / "KboOpenData_42_2026_04_Full.zip"
    with zipfile.ZipFile(out, "w") as zf:
        for f in _MINI.glob("*.csv"):
            zf.write(f, arcname=f.name)
    return out


# ── meta ────────────────────────────────────────────────────────────────────


def test_parse_meta_keys(full_zip: Path) -> None:
    meta = parse_meta(full_zip)
    assert meta["SnapshotDate"] == "15-04-2026"
    assert meta["ExtractType"] == "Full"
    assert meta["ExtractNumber"] == "42"
    assert meta["Version"] == "R018.00"


def test_parse_meta_missing_returns_empty(tmp_path: Path) -> None:
    empty_zip = tmp_path / "empty.zip"
    with zipfile.ZipFile(empty_zip, "w"):
        pass
    assert parse_meta(empty_zip) == {}


def test_detect_extract_type_from_meta(full_zip: Path) -> None:
    assert detect_extract_type(full_zip) == "Full"


def test_detect_extract_type_from_filename(tmp_path: Path) -> None:
    update_zip = tmp_path / "KboOpenData_43_2026_04_Update.zip"
    with zipfile.ZipFile(update_zip, "w"):
        pass
    assert detect_extract_type(update_zip) == "Update"


def test_detect_extract_type_fallback_full(tmp_path: Path) -> None:
    """ZIP with no meta.csv and no 'update' in filename defaults to Full."""
    plain_zip = tmp_path / "KboOpenData_42_2026_04.zip"
    with zipfile.ZipFile(plain_zip, "w"):
        pass
    assert detect_extract_type(plain_zip) == "Full"


def test_parse_meta_non_zip_returns_empty(tmp_path: Path) -> None:
    """A non-ZIP file triggers the except-Exception path → returns {}."""
    bad_file = tmp_path / "not_a_zip.zip"
    bad_file.write_text("this is not a zip file")
    assert parse_meta(bad_file) == {}


def test_iter_enterprises_missing_csv_yields_nothing(tmp_path: Path) -> None:
    """A ZIP with no enterprise.csv yields no rows."""
    empty_zip = tmp_path / "no_enterprise.zip"
    with zipfile.ZipFile(empty_zip, "w"):
        pass
    assert list(iter_enterprises(empty_zip)) == []


def test_iter_enterprises_empty_start_date(tmp_path: Path) -> None:
    """enterprise.csv with empty StartDate produces a row with start_date=None."""
    z = tmp_path / "test.zip"
    csv_content = (
        "EnterpriseNumber,Status,JuridicalSituation,TypeOfEnterprise,"
        "JuridicalForm,JuridicalFormCAC,StartDate\n"
        "0439401387,AC,000,1,014,014,\n"
    )
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("enterprise.csv", csv_content)
    rows = list(iter_enterprises(z))
    assert len(rows) == 1
    assert rows[0].start_date is None


# ── enterprises ─────────────────────────────────────────────────────────────


def test_iter_enterprises_count(full_zip: Path) -> None:
    rows = list(iter_enterprises(full_zip))
    assert len(rows) == 5


def test_iter_enterprises_bellock(full_zip: Path) -> None:
    rows = {r.enterprise_number: r for r in iter_enterprises(full_zip)}
    bellock = rows["0439401387"]
    assert bellock.status == "AC"
    assert bellock.type_of_enterprise == "1"
    assert bellock.juridical_form == "014"
    assert bellock.start_date == date(1989, 12, 28)


def test_iter_enterprises_natural_person(full_zip: Path) -> None:
    rows = {r.enterprise_number: r for r in iter_enterprises(full_zip)}
    nat = rows["0123456749"]
    assert nat.type_of_enterprise == "2"
    assert nat.juridical_form is None


def test_iter_enterprises_modern_prefix(full_zip: Path) -> None:
    rows = {r.enterprise_number: r for r in iter_enterprises(full_zip)}
    assert "1000000021" in rows


def test_iter_enterprises_null_juridical_form(full_zip: Path) -> None:
    rows = {r.enterprise_number: r for r in iter_enterprises(full_zip)}
    assert rows["0200379531"].juridical_form is None


def test_iter_enterprises_recent_start_date(full_zip: Path) -> None:
    rows = {r.enterprise_number: r for r in iter_enterprises(full_zip)}
    assert rows["0800000075"].start_date == date(2023, 11, 22)


def test_iter_enterprises_kbo_compacted(full_zip: Path) -> None:
    for row in iter_enterprises(full_zip):
        assert "." not in row.enterprise_number
        assert len(row.enterprise_number) == 10


# ── denominations ────────────────────────────────────────────────────────────


def test_iter_denominations_count(full_zip: Path) -> None:
    rows = list(iter_denominations(full_zip))
    assert len(rows) == 7


def test_iter_denominations_types(full_zip: Path) -> None:
    rows = list(iter_denominations(full_zip))
    types = {r.type_of_denomination for r in rows}
    assert "001" in types
    assert "002" in types
    assert "003" in types


def test_iter_denominations_bellock_legal(full_zip: Path) -> None:
    rows = [r for r in iter_denominations(full_zip) if r.entity_number == "0439401387"]
    legal = [r for r in rows if r.type_of_denomination == "001"]
    assert len(legal) == 1
    assert legal[0].denomination == "Bellock NV"


# ── addresses ────────────────────────────────────────────────────────────────


def test_iter_addresses_count(full_zip: Path) -> None:
    rows = list(iter_addresses(full_zip))
    assert len(rows) == 6


def test_iter_addresses_antwerpen(full_zip: Path) -> None:
    rows = [
        r
        for r in iter_addresses(full_zip)
        if r.entity_number == "0439401387" and r.type_of_address == "REGO"
    ]
    assert len(rows) == 1
    assert rows[0].zipcode == "2060"
    assert rows[0].municipality_nl == "Antwerpen"
    assert rows[0].street_nl == "Lange Van Bloerstraat"


def test_iter_addresses_liege_fr_only(full_zip: Path) -> None:
    rows = [r for r in iter_addresses(full_zip) if r.entity_number == "0123456749"]
    assert len(rows) == 1
    assert rows[0].street_nl is None
    assert rows[0].street_fr == "Rue de la Régence"


def test_iter_addresses_null_street(full_zip: Path) -> None:
    rows = [r for r in iter_addresses(full_zip) if r.entity_number == "0200379531"]
    assert len(rows) == 1
    assert rows[0].street_nl is None
    assert rows[0].street_fr is None


# ── contacts ────────────────────────────────────────────────────────────────


def test_iter_contacts_count(full_zip: Path) -> None:
    rows = list(iter_contacts(full_zip))
    assert len(rows) == 10


def test_iter_contacts_types(full_zip: Path) -> None:
    rows = list(iter_contacts(full_zip))
    tel = [r for r in rows if r.contact_type == "TEL"]
    email = [r for r in rows if r.contact_type == "EMAIL"]
    web = [r for r in rows if r.contact_type == "WEB"]
    assert len(tel) == 5
    assert len(email) == 3
    assert len(web) == 2


def test_iter_contacts_invalid_phone_row_present(full_zip: Path) -> None:
    tel_rows = [r for r in iter_contacts(full_zip) if r.contact_type == "TEL"]
    invalid = [r for r in tel_rows if r.value.strip() == "123"]
    assert len(invalid) == 1


def test_iter_contacts_email_whitespace_preserved(full_zip: Path) -> None:
    email_rows = [r for r in iter_contacts(full_zip) if r.contact_type == "EMAIL"]
    modern = [r for r in email_rows if "modern" in r.value]
    assert len(modern) == 1
    # Raw value has leading space; transformer must strip it
    assert modern[0].value != modern[0].value.strip() or " " in modern[0].value


# ── activities ───────────────────────────────────────────────────────────────


def test_iter_activities_count(full_zip: Path) -> None:
    rows = list(iter_activities(full_zip))
    assert len(rows) == 8


def test_iter_activities_versions(full_zip: Path) -> None:
    rows = list(iter_activities(full_zip))
    versions = {r.nace_version for r in rows}
    assert "2008" in versions
    assert "2025" in versions


def test_iter_activities_classifications(full_zip: Path) -> None:
    rows = list(iter_activities(full_zip))
    classifications = {r.classification for r in rows}
    assert "MAIN" in classifications
    assert "SECO" in classifications
    assert "AUXI" in classifications
