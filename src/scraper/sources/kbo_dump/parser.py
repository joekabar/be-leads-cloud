from __future__ import annotations

import csv
import io
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

from stdnum.be import vat as be_vat


def _compact_kbo(raw: str) -> str:
    return str(be_vat.compact(raw))


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%d-%m-%Y").date()
    except ValueError:
        return None


def _none_if_empty(s: str) -> str | None:
    stripped = s.strip()
    return stripped if stripped else None


def _has_csv(zf: zipfile.ZipFile, name: str) -> bool:
    return any(n.lower() == name.lower() for n in zf.namelist())


def _open_reader(zf: zipfile.ZipFile, name: str) -> csv.DictReader[str]:
    for n in zf.namelist():
        if n.lower() == name.lower():
            raw = zf.open(n)
            text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
            return csv.DictReader(text)
    raise KeyError(f"{name!r} not found in ZIP")


@dataclass(frozen=True, slots=True)
class EnterpriseRow:
    enterprise_number: str
    status: str
    juridical_situation: str
    type_of_enterprise: str
    juridical_form: str | None
    juridical_form_cac: str | None
    start_date: date | None


@dataclass(frozen=True, slots=True)
class AddressRow:
    entity_number: str
    type_of_address: str
    zipcode: str | None
    municipality_nl: str | None
    municipality_fr: str | None
    street_nl: str | None
    street_fr: str | None
    house_number: str | None
    box: str | None


@dataclass(frozen=True, slots=True)
class ContactRow:
    entity_number: str
    contact_type: str
    value: str


@dataclass(frozen=True, slots=True)
class DenominationRow:
    entity_number: str
    language: str
    type_of_denomination: str
    denomination: str


@dataclass(frozen=True, slots=True)
class ActivityRow:
    entity_number: str
    activity_group: str
    nace_version: str
    nace_code: str
    classification: str


def parse_meta(zip_path: Path) -> dict[str, str]:
    """Read meta.csv as key/value pairs. Returns {} if missing."""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            if not _has_csv(zf, "meta.csv"):
                return {}
            reader = _open_reader(zf, "meta.csv")
            return {row["Variable"]: row["Value"] for row in reader}
    except Exception:
        return {}


def detect_extract_type(zip_path: Path) -> Literal["Full", "Update"]:
    """Reads meta.csv ExtractType; falls back to filename pattern."""
    meta = parse_meta(zip_path)
    extract_type = meta.get("ExtractType", "")
    if extract_type in ("Full", "Update"):
        return extract_type  # type: ignore[return-value]
    if "update" in zip_path.name.lower():
        return "Update"
    return "Full"


def iter_enterprises(zip_path: Path) -> Iterator[EnterpriseRow]:
    """Yield rows from enterprise.csv (Full) or enterprise_insert.csv (Update)."""
    with zipfile.ZipFile(zip_path) as zf:
        csv_name = (
            "enterprise_insert.csv" if _has_csv(zf, "enterprise_insert.csv") else "enterprise.csv"
        )
        if not _has_csv(zf, csv_name):
            return
        reader = _open_reader(zf, csv_name)
        for row in reader:
            yield EnterpriseRow(
                enterprise_number=_compact_kbo(row["EnterpriseNumber"]),
                status=row["Status"],
                juridical_situation=row["JuridicalSituation"],
                type_of_enterprise=row["TypeOfEnterprise"],
                juridical_form=_none_if_empty(row.get("JuridicalForm", "")),
                juridical_form_cac=_none_if_empty(row.get("JuridicalFormCAC", "")),
                start_date=_parse_date(row.get("StartDate", "") or ""),
            )


def iter_deleted_enterprises(zip_path: Path) -> Iterator[str]:
    """Yield enterprise numbers from enterprise_delete.csv (Update ZIPs only)."""
    with zipfile.ZipFile(zip_path) as zf:
        if not _has_csv(zf, "enterprise_delete.csv"):
            return
        reader = _open_reader(zf, "enterprise_delete.csv")
        for row in reader:
            yield _compact_kbo(row["EnterpriseNumber"])


def iter_addresses(zip_path: Path) -> Iterator[AddressRow]:
    """Yield rows from address.csv (Full) or address_insert.csv (Update)."""
    with zipfile.ZipFile(zip_path) as zf:
        csv_name = "address_insert.csv" if _has_csv(zf, "address_insert.csv") else "address.csv"
        if not _has_csv(zf, csv_name):
            return
        reader = _open_reader(zf, csv_name)
        for row in reader:
            yield AddressRow(
                entity_number=_compact_kbo(row["EntityNumber"]),
                type_of_address=row.get("TypeOfAddress", ""),
                zipcode=_none_if_empty(row.get("Zipcode", "") or ""),
                municipality_nl=_none_if_empty(row.get("MunicipalityNL", "") or ""),
                municipality_fr=_none_if_empty(row.get("MunicipalityFR", "") or ""),
                street_nl=_none_if_empty(row.get("StreetNL", "") or ""),
                street_fr=_none_if_empty(row.get("StreetFR", "") or ""),
                house_number=_none_if_empty(row.get("HouseNumber", "") or ""),
                box=_none_if_empty(row.get("Box", "") or ""),
            )


def iter_contacts(zip_path: Path) -> Iterator[ContactRow]:
    """Yield rows from contact.csv (Full) or contact_insert.csv (Update)."""
    with zipfile.ZipFile(zip_path) as zf:
        csv_name = "contact_insert.csv" if _has_csv(zf, "contact_insert.csv") else "contact.csv"
        if not _has_csv(zf, csv_name):
            return
        reader = _open_reader(zf, csv_name)
        for row in reader:
            yield ContactRow(
                entity_number=_compact_kbo(row["EntityNumber"]),
                contact_type=row["ContactType"],
                value=row["Value"],
            )


def iter_denominations(zip_path: Path) -> Iterator[DenominationRow]:
    """Yield rows from denomination.csv (Full) or denomination_insert.csv (Update)."""
    with zipfile.ZipFile(zip_path) as zf:
        csv_name = (
            "denomination_insert.csv"
            if _has_csv(zf, "denomination_insert.csv")
            else "denomination.csv"
        )
        if not _has_csv(zf, csv_name):
            return
        reader = _open_reader(zf, csv_name)
        for row in reader:
            yield DenominationRow(
                entity_number=_compact_kbo(row["EntityNumber"]),
                language=row["Language"],
                type_of_denomination=row["TypeOfDenomination"],
                denomination=row["Denomination"],
            )


def iter_activities(zip_path: Path) -> Iterator[ActivityRow]:
    """Yield rows from activity.csv (Full) or activity_insert.csv (Update)."""
    with zipfile.ZipFile(zip_path) as zf:
        csv_name = "activity_insert.csv" if _has_csv(zf, "activity_insert.csv") else "activity.csv"
        if not _has_csv(zf, csv_name):
            return
        reader = _open_reader(zf, csv_name)
        for row in reader:
            yield ActivityRow(
                entity_number=_compact_kbo(row["EntityNumber"]),
                activity_group=row.get("ActivityGroup", ""),
                nace_version=row["NaceVersion"],
                nace_code=row["NaceCode"],
                classification=row["Classification"],
            )
