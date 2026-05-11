from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from stdnum.be import vat as be_vat

_MINI = Path("tests/golden/kbo_dump/synthetic_mini")


@pytest.fixture(scope="session")
def synthetic_zip(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("zips") / "KboOpenData_42_2026_04_Full.zip"
    with zipfile.ZipFile(out, "w") as zf:
        for f in _MINI.glob("*.csv"):
            zf.write(f, arcname=f.name)
    return out


def _gen_valid_kbos(count: int) -> list[str]:
    """Generate `count` valid KBO numbers in the 040x range."""
    result: list[str] = []
    i = 0
    while len(result) < count:
        first8 = f"0400{i:04d}"
        check = 97 - (int(first8) % 97)
        if check == 97:
            check = 0
        candidate = f"{first8}{check:02d}"
        if be_vat.is_valid(candidate):
            result.append(candidate)
        i += 1
    return result


@pytest.fixture(scope="session")
def large_zip(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """50-enterprise ZIP; expected to produce ≥200 observations (300 exactly)."""
    kbos = _gen_valid_kbos(50)

    meta = (
        "Variable,Value\n"
        "SnapshotDate,15-04-2026\n"
        "ExtractTimestamp,2026-04-15T03:00:00\n"
        "ExtractType,Full\n"
        "ExtractNumber,99\n"
        "Version,R018.00\n"
    )
    ent_rows = [
        "EnterpriseNumber,Status,JuridicalSituation,TypeOfEnterprise,JuridicalForm,JuridicalFormCAC,StartDate"
    ]
    denom_rows = ["EntityNumber,Language,TypeOfDenomination,Denomination"]
    addr_rows = [
        "EntityNumber,TypeOfAddress,Zipcode,MunicipalityNL,MunicipalityFR,StreetNL,StreetFR,HouseNumber,Box"
    ]
    contact_rows = ["EntityNumber,ContactType,Value"]
    activity_rows = ["EntityNumber,ActivityGroup,NaceVersion,NaceCode,Classification"]

    for idx, kbo in enumerate(kbos):
        ent_rows.append(f"{kbo},AC,000,1,014,014,01-01-2000")
        denom_rows.append(f"{kbo},NL,001,Large Company {idx:02d} NV")
        addr_rows.append(f"{kbo},REGO,1000,Brussel,Bruxelles,Wetstraat,Rue de la Loi,{idx + 1},")
        contact_rows.append(f"{kbo},EMAIL,info{idx:02d}@largetest.be")
        activity_rows.append(f"{kbo},MAIN,2008,62.010,MAIN")

    out = tmp_path_factory.mktemp("zips") / "KboOpenData_99_2026_04_Full.zip"
    with zipfile.ZipFile(out, "w") as zf:
        for name, lines in [
            ("meta.csv", meta),
            ("enterprise.csv", "\n".join(ent_rows) + "\n"),
            ("denomination.csv", "\n".join(denom_rows) + "\n"),
            ("address.csv", "\n".join(addr_rows) + "\n"),
            ("contact.csv", "\n".join(contact_rows) + "\n"),
            ("activity.csv", "\n".join(activity_rows) + "\n"),
        ]:
            zf.writestr(name, lines)
    return out
