"""Generate a deterministic 10k-enterprise KBO Open Data fixture ZIP.

Idempotent: random.Random(seed) ensures byte-identical output on every run.
Run directly: python tests/integration/sources/kbo_dump/_generate_large_fixture.py
Or call build(path, n_enterprises=10_000, seed=42) from tests.
"""

from __future__ import annotations

import csv
import io
import random
import zipfile
from pathlib import Path

from stdnum.be import vat as be_vat

BELLOCK_KBO = "0439401387"

# NACE code distribution: (code, weight)
_NACE = [
    ("43.211", 15),
    ("46.110", 15),
    ("47.110", 10),
    ("62.010", 10),
    ("10.110", 7),
    ("25.110", 7),
    ("41.100", 7),
    ("56.101", 7),
    ("45.110", 7),
    ("86.210", 7),
    ("49.410", 8),
]
_NACE_CODES = [c for c, _ in _NACE]
_NACE_WEIGHTS = [w for _, w in _NACE]

# Address distribution: (zipcode, municipality_nl, municipality_fr, weight)
_ADDR = [
    ("1000", "Brussel", "Bruxelles", 30),
    ("2000", "Antwerpen", "Anvers", 25),
    ("9000", "Gent", "Gand", 20),
    ("3000", "Leuven", "Louvain", 10),
    ("4000", "Liège", "Liège", 8),
    ("8000", "Brugge", "Bruges", 7),
]
_ADDR_DATA = [(z, nl, fr) for z, nl, fr, _ in _ADDR]
_ADDR_WEIGHTS = [w for *_, w in _ADDR]


def _make_kbo(base8: int) -> str:
    check = 97 - (base8 % 97)
    if check == 97:
        check = 0
    return f"{base8:08d}{check:02d}"


def _gen_kbo_pool(n: int, rng: random.Random) -> list[str]:
    """Generate n unique valid KBOs; Bellock is always index 0."""
    seen: set[str] = {BELLOCK_KBO}
    result: list[str] = [BELLOCK_KBO]
    n_modern = max(1, int(n * 0.05))
    n_classic = n - 1 - n_modern  # -1 because Bellock is already in result

    i0 = 4_000_001
    added = 0
    while added < n_classic:
        kbo = _make_kbo(i0)
        i0 += 1
        if kbo not in seen and be_vat.is_valid(kbo):
            result.append(kbo)
            seen.add(kbo)
            added += 1

    i1 = 10_000_001
    added = 0
    while added < n_modern:
        kbo = _make_kbo(i1)
        i1 += 1
        if kbo not in seen and be_vat.is_valid(kbo):
            result.append(kbo)
            seen.add(kbo)
            added += 1

    # Shuffle everything after Bellock for realistic ordering
    tail = result[1:]
    rng.shuffle(tail)
    return [result[0], *tail]


def _write_csv(zf: zipfile.ZipFile, name: str, rows: list[list[str]], header: list[str]) -> None:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    w.writerows(rows)
    zf.writestr(name, buf.getvalue())


def build(out_path: Path, *, n_enterprises: int = 10_000, seed: int = 42) -> None:
    """Write a deterministic KBO fixture ZIP to out_path."""
    rng = random.Random(seed)  # noqa: S311
    kbos = _gen_kbo_pool(n_enterprises, rng)

    meta_content = (
        "Variable,Value\n"
        "SnapshotDate,15-04-2026\n"
        "ExtractTimestamp,2026-04-15T03:00:00\n"
        "ExtractType,Full\n"
        "ExtractNumber,42\n"
        "Version,R018.00\n"
    )

    ent_rows: list[list[str]] = []
    denom_rows: list[list[str]] = []
    addr_rows: list[list[str]] = []
    contact_rows: list[list[str]] = []
    activity_rows: list[list[str]] = []

    for idx, kbo in enumerate(kbos):
        is_bellock = kbo == BELLOCK_KBO

        # --- Enterprise ---
        type_of_ent = "1" if rng.random() < 0.70 else "2"
        year = rng.randint(1990, 2026)
        month = rng.randint(1, 12)
        day = rng.randint(1, 28)
        start = f"{day:02d}-{month:02d}-{year}"
        if is_bellock:
            start = "28-12-1989"
            type_of_ent = "1"
        ent_rows.append([kbo, "AC", "000", type_of_ent, "014", "014", start])

        # --- Denominations (avg 1.2 per enterprise) ---
        legal_name = "Bellock NV" if is_bellock else f"Company {idx:05d} NV"
        denom_rows.append([kbo, "NL", "001", legal_name])
        if rng.random() < 0.15:
            abbr = "BLK" if is_bellock else f"C{idx:04d}"
            denom_rows.append([kbo, "NL", "002", abbr])
        if rng.random() < 0.10:
            commercial = "Bellock Services" if is_bellock else f"Company {idx:05d} Services"
            denom_rows.append([kbo, "NL", "003", commercial])

        # --- Addresses (avg 1.5 per enterprise) ---
        if is_bellock:
            addr_rows.append(
                [
                    kbo,
                    "REGO",
                    "2060",
                    "Antwerpen",
                    "Anvers",
                    "Lange Van Bloerstraat",
                    "",
                    "116",
                    "2",
                ]
            )
        else:
            zipcode, muni_nl, muni_fr = rng.choices(_ADDR_DATA, weights=_ADDR_WEIGHTS, k=1)[0]
            street_nl = rng.choice(
                [
                    "Kerkstraat",
                    "Nieuwstraat",
                    "Marktplein",
                    "Dorpsstraat",
                    "Stationsstraat",
                    "Schoolstraat",
                    "Industrielaan",
                ]
            )
            hn = str(rng.randint(1, 200))
            addr_rows.append([kbo, "REGO", zipcode, muni_nl, muni_fr, street_nl, "", hn, ""])
            if rng.random() < 0.30:
                # Branch address
                zipcode2, muni_nl2, muni_fr2 = rng.choices(_ADDR_DATA, weights=_ADDR_WEIGHTS, k=1)[
                    0
                ]
                hn2 = str(rng.randint(1, 200))
                addr_rows.append(
                    [kbo, "BIAN", zipcode2, muni_nl2, muni_fr2, "Industrielaan", "", hn2, ""]
                )

        # --- Contacts ---
        if is_bellock:
            contact_rows.append([kbo, "REC", "TEL", "03 236 13 06"])
            contact_rows.append([kbo, "REC", "EMAIL", "info@bellock.be"])
            contact_rows.append([kbo, "REC", "WEB", "https://www.bellock.be"])
        else:
            r = rng.random()
            if r < 0.80:
                # Valid Belgian phone
                _r2 = rng.randint
                phone_type = rng.choice(["landline_bxl", "landline_ant", "landline_gent", "mobile"])
                if phone_type == "landline_bxl":
                    phone = f"02 {_r2(200, 799)} {_r2(10, 99):02d} {_r2(10, 99):02d}"
                elif phone_type == "landline_ant":
                    phone = f"03 {_r2(200, 299)} {_r2(10, 99):02d} {_r2(10, 99):02d}"
                elif phone_type == "landline_gent":
                    phone = f"09 {_r2(200, 299)} {_r2(10, 99):02d} {_r2(10, 99):02d}"
                else:
                    _prefixes = [
                        "0471",
                        "0474",
                        "0475",
                        "0476",
                        "0477",
                        "0478",
                        "0479",
                        "0481",
                        "0484",
                        "0485",
                        "0486",
                        "0487",
                        "0488",
                        "0489",
                        "0491",
                        "0494",
                        "0495",
                        "0496",
                        "0497",
                        "0498",
                        "0499",
                    ]
                    prefix = rng.choice(_prefixes)
                    phone = f"{prefix} {_r2(10, 99):02d} {_r2(10, 99):02d} {_r2(10, 99):02d}"
                contact_rows.append([kbo, "REC", "TEL", phone])
            elif r < 0.85:
                # Deliberately invalid phone
                contact_rows.append(
                    [kbo, "REC", "TEL", rng.choice(["123", "INVALID", "00000", "notaphone"])]
                )

            if rng.random() < 0.60:
                contact_rows.append([kbo, "REC", "EMAIL", f"info{idx:05d}@company{idx:05d}.be"])

            if rng.random() < 0.40:
                contact_rows.append([kbo, "REC", "WEB", f"https://www.company{idx:05d}.be"])

        # --- Activities (avg 1.8 per enterprise) ---
        if is_bellock:
            activity_rows.append([kbo, "MAIN", "2008", "43.211", "MAIN"])
        else:
            nace1 = rng.choices(_NACE_CODES, weights=_NACE_WEIGHTS, k=1)[0]
            version = rng.choice(["2008", "2025"])
            activity_rows.append([kbo, "MAIN", version, nace1, "MAIN"])
            if rng.random() < 0.60:
                nace2 = rng.choices(_NACE_CODES, weights=_NACE_WEIGHTS, k=1)[0]
                version2 = rng.choice(["2008", "2025"])
                activity_rows.append([kbo, "VECO", version2, nace2, "VECO"])

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("meta.csv", meta_content)
        _write_csv(
            zf,
            "enterprise.csv",
            ent_rows,
            [
                "EnterpriseNumber",
                "Status",
                "JuridicalSituation",
                "TypeOfEnterprise",
                "JuridicalForm",
                "JuridicalFormCAC",
                "StartDate",
            ],
        )
        _write_csv(
            zf,
            "denomination.csv",
            denom_rows,
            ["EntityNumber", "Language", "TypeOfDenomination", "Denomination"],
        )
        _write_csv(
            zf,
            "address.csv",
            addr_rows,
            [
                "EntityNumber",
                "TypeOfAddress",
                "Zipcode",
                "MunicipalityNL",
                "MunicipalityFR",
                "StreetNL",
                "StreetFR",
                "HouseNumber",
                "Box",
            ],
        )
        _write_csv(
            zf,
            "contact.csv",
            contact_rows,
            ["EntityNumber", "EntityContact", "ContactType", "Value"],
        )
        _write_csv(
            zf,
            "activity.csv",
            activity_rows,
            ["EntityNumber", "ActivityGroup", "NaceVersion", "NaceCode", "Classification"],
        )


if __name__ == "__main__":
    import sys

    dest = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else Path("tests/golden/kbo_dump/large_10k/cached.zip")
    )
    build(dest, n_enterprises=10_000, seed=42)
    print(f"Written {dest} ({dest.stat().st_size // 1024} KB)")
