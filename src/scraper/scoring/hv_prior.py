"""HV-tier prior table: NACE prefix → HV-cabinet probability in [0, 1].

Lookup uses longest-prefix match so a 4-digit prefix ("3511") beats a 2-digit
one ("35") for the same code, enabling fine-grained tier assignment without
collision risk.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

# Keys are KBO-style dotless NACE prefixes (e.g. "3511", not "35.11").
# Values are HV probability in [0.0, 1.0].
# T1 >= 0.80 / T2 0.55-0.79 / T3 0.30-0.54 / T4 < 0.30
_HV_PRIORS: dict[str, float] = {
    # ─── Tier 1 ───────────────────────────────────────────────────────────────
    # Electricity generation, transmission, distribution
    "3511": 1.00,
    "3512": 1.00,
    "3513": 0.90,
    "3514": 0.80,
    # Gas manufacture and distribution
    "3521": 0.90,
    "3522": 0.80,
    # Steam and air conditioning supply
    "3530": 0.80,
    # Petroleum refining / coke
    "191": 0.80,
    "192": 0.90,
    # Basic chemicals (all sub-divisions)
    "201": 0.95,
    "202": 0.95,
    "203": 0.90,
    "204": 0.90,
    "205": 0.90,
    "206": 0.90,
    # Pharmaceuticals
    "211": 0.90,
    "212": 0.90,
    # Basic metals
    "241": 0.95,
    "242": 0.90,
    "243": 0.90,
    "244": 0.85,
    "245": 0.80,
    # Data centres (very high continuous load, often directly HV-fed)
    "6190": 0.90,
    # Rail infrastructure (traction substations, HV grid connection)
    "4910": 0.85,
    "4920": 0.85,
    # Mining / extraction
    "051": 0.70,
    "061": 0.80,
    "062": 0.80,
    "071": 0.65,
    "072": 0.65,
    # ─── Tier 2 ───────────────────────────────────────────────────────────────
    # Motor vehicle manufacture
    "291": 0.75,
    "292": 0.75,
    "293": 0.70,
    # Shipbuilding, railway, aircraft
    "301": 0.75,
    "302": 0.75,
    "303": 0.70,
    "304": 0.65,
    # Water and sewage
    "3600": 0.80,
    "3700": 0.80,
    # Waste treatment and materials recovery
    "381": 0.65,
    "382": 0.70,
    "383": 0.70,
    "390": 0.65,
    # Paper
    "171": 0.70,
    "172": 0.65,
    # Rubber and plastics
    "221": 0.65,
    "222": 0.65,
    # Non-metallic minerals (cement, glass, ceramics)
    "231": 0.70,
    "232": 0.65,
    "233": 0.65,
    "234": 0.65,
    "235": 0.70,
    "236": 0.60,
    # Electronic and electrical equipment
    "261": 0.65,
    "262": 0.60,
    "263": 0.60,
    "271": 0.65,
    "272": 0.65,
    "273": 0.60,
    "274": 0.60,
    "275": 0.55,
    # Machinery
    "281": 0.65,
    "282": 0.65,
    "283": 0.65,
    "284": 0.65,
    "289": 0.65,
    # Fabricated metals
    "251": 0.60,
    "252": 0.65,
    "253": 0.65,
    "255": 0.60,
    "256": 0.65,
    "257": 0.60,
    "259": 0.60,
    # Food processing (industrial scale)
    "101": 0.65,
    "102": 0.60,
    "103": 0.60,
    "104": 0.60,
    "105": 0.65,
    "106": 0.65,
    "107": 0.60,
    "108": 0.60,
    "109": 0.55,
    "110": 0.65,
    "120": 0.60,
    # Textile manufacturing
    "131": 0.55,
    "132": 0.50,
    # Other mining / quarrying
    "089": 0.55,
    "811": 0.55,
    "812": 0.55,
    "0812": 0.50,
    # Transport via pipeline
    "4950": 0.45,
    # ─── Tier 3 ───────────────────────────────────────────────────────────────
    # Hospitals
    "8610": 0.40,
    # Large commercial buildings / office parks (often HV-metered)
    "6820": 0.30,
    # EV fast-charging hubs (high-power grid connection)
    "4799": 0.45,
    # Industrial greenhouses (large lighting + climate load)
    "0113": 0.20,
    "0119": 0.20,
    "013": 0.20,
    # Intensive livestock (ventilation, heating, cooling)
    "0147": 0.15,
    # Port and airport services
    "5222": 0.45,
    "5223": 0.40,
    "5224": 0.35,
    # Warehousing and logistics support
    "5210": 0.35,
    "5220": 0.35,
    "5221": 0.35,
    # Civil engineering (infrastructure)
    "4211": 0.40,
    "4212": 0.45,
    "4213": 0.40,
    "4221": 0.45,
    "4222": 0.40,
    "4223": 0.35,
    "4291": 0.40,
    "4299": 0.35,
    # General construction
    "4110": 0.30,
    "4120": 0.30,
    # Engineering consultancy (often serves industry)
    "7112": 0.35,
    # R&D
    "7211": 0.35,
    "7219": 0.30,
    # Tertiary education (universities)
    "8542": 0.30,
    # Freight road transport
    "4941": 0.30,
    # ─── Tier 4 ───────────────────────────────────────────────────────────────
    # Construction installation (SME)
    "4321": 0.30,
    "4322": 0.20,
    "4329": 0.15,
    "4331": 0.10,
    "4332": 0.10,
    "4333": 0.10,
    "4334": 0.10,
    "4339": 0.10,
    "4391": 0.10,
    "4399": 0.15,
    # Automotive repair
    "4520": 0.15,
    # Retail (non-specialised / food)
    "471": 0.05,
    "472": 0.05,
    "477": 0.05,
    "478": 0.05,
    # Hospitality
    "5510": 0.05,
    "5520": 0.05,
    "5530": 0.05,
    "5610": 0.05,
    "5621": 0.05,
    # Healthcare (small practice)
    "7500": 0.05,
    "8621": 0.05,
    "8622": 0.05,
    "8623": 0.05,
    "8690": 0.05,
    # Personal services
    "9602": 0.05,
    "9603": 0.05,
    # Professional services (SME)
    "6910": 0.05,
    "6920": 0.05,
    "7111": 0.10,
    "7311": 0.05,
    # Education (non-university)
    "851": 0.05,
    "852": 0.05,
    # Removal / last-mile
    "4942": 0.10,
}


def hv_probability(nace_codes: Iterable[str]) -> float:
    """Return max HV probability across all codes via longest-prefix match.

    An unknown prefix (not in _HV_PRIORS) contributes 0.0 — uncovered sectors
    are explicitly not prioritised rather than defaulting to 0.5.
    """
    best = 0.0
    for code in nace_codes:
        code = code.strip()
        for length in range(len(code), 0, -1):
            prefix = code[:length]
            if prefix in _HV_PRIORS:
                best = max(best, _HV_PRIORS[prefix])
                break
    return best
