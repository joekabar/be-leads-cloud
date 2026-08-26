"""Sector slug -> NACE prefix mapping, the vocabulary of the whole pipeline.

Formerly a private constant in pipeline/orchestrator.py imported by six modules.
KBO Open Data stores NACE codes WITHOUT dots ("4321", never "43.21"); every prefix
here must match that format — enforced by tests/unit/lib/test_sector_nace.py.
"""

from __future__ import annotations

SECTOR_NACE_PREFIXES: dict[str, list[str]] = {
    # Construction & installation
    "dakdekkers": ["4391"],
    "elektriciens": ["4321"],  # 43211=electrical systems, 43212=alarm/signalling
    "glaszetters": ["4334"],  # 43340=painting and glazing (includes glazing)
    "isolatiebedrijven": ["4329", "4399"],
    "loodgieters": ["4322"],  # 43220=plumbing, heating, air-conditioning
    "metselaars": [
        "4120",
        "4399",
    ],  # 4120=general building construction (incl. masonry); 4399=other specialised
    "schilders": ["4334"],  # 43340=painting and glazing
    "schrijnwerkers": ["4332"],  # 43320=joinery installation
    "tegelzetters": ["4333"],  # 43330=floor and wall covering
    "timmerlieden": ["4332"],  # 43320=joinery installation (on-site carpentry)
    "vloerleggers": ["4333"],  # 43330=floor and wall covering
    "zonnepaneleninstallateurs": ["4321"],
    "airco-installateurs": ["4322"],
    "sanitair": ["4322"],
    "verwarmingsinstallateurs": ["4322"],
    # Automotive
    "autogarages": ["4520"],  # 45201/45202=maintenance and repair of motor vehicles
    "autohandelaars": ["4511", "4519"],
    "carrosserieherstellers": ["4520"],
    "garagisten": ["4520"],  # 45201/45202 — same as autogarages
    # Food & hospitality
    "bakkers": ["1071"],
    "cateringbedrijven": ["5621", "5629"],
    "hotels": ["5510"],
    "restaurants": ["5610"],
    "slagers": ["1013"],
    "supermarkten": ["4711"],
    "traiteurs": ["5621", "5629"],
    # Retail & market
    "bloemisten": ["4776"],
    "boekhandels": ["4761"],
    "kledingwinkels": ["4771"],
    "marktzaken": ["478"],
    "opticiens": ["4778"],
    "schoenenwinkels": ["4772"],
    "tuincentra": ["4776"],
    # Professional services
    "accountants": ["6920"],
    "advocaten": ["6910"],
    "architecten": ["7111"],
    "belastingconsulenten": ["6920"],
    "ingenieurs": ["7112"],
    "managementconsulenten": ["7022"],
    "notarissen": ["6910"],
    "reclamebureaus": ["7311"],
    "uitzendbureaus": ["7820"],
    "vastgoedmakelaars": ["6831", "6832"],
    "vertalingsbureaus": ["7430"],
    "verzekeringsmaatschappijen": ["651", "652"],
    # Healthcare & personal care
    "apothekers": ["4773"],
    "dierenartsen": ["7500"],
    "huisartsen": ["8621"],
    "kappers": ["9602"],
    "kinderdagverblijven": ["8891"],
    "kinesitherapeuten": ["8690"],
    "schoonheidsspecialisten": ["9602"],
    "tandartsen": ["8623"],
    # ICT & media
    "fotografen": ["7420"],
    "informaticabedrijven": [
        "620",
        "631",
        "582",
    ],  # 620x=programming/consultancy, 631x=hosting/portals, 582x=software publishing
    "telecomdiensten": ["61"],
    # Other services
    "banken": ["641", "642"],
    "begrafenisondernemingen": ["9603"],
    "bewakingsdiensten": ["8010"],
    "campings": ["5530"],
    "drukkerijen": ["1811", "1812"],
    "recyclagebedrijven": ["381", "382", "383"],
    "recyclagebedrijven-industrieel": ["381", "382", "383"],
    "scholen": ["85"],
    "schoonmaakbedrijven": ["8121", "8122", "8129"],
    "taxidiensten": ["4932"],
    "transportbedrijven": ["4941", "4939", "4942"],
    "transportbedrijven-zwaar": ["4941", "4942"],
    "tuinaanleggers": ["8130"],
    "verhuisbedrijven": ["4942"],
    # Tier 1: Guaranteed / very high HV — KBO Open Data only (not on goudengids)
    "energieproducenten": ["3511", "3512", "3513", "3514"],
    "gasdistributie": ["3521", "3522"],
    "stoomlevering": ["3530"],
    "chemiebedrijven": ["201", "202", "203", "204", "205", "206"],
    "farmaceutische-bedrijven": ["211", "212"],
    "staalindustrie": ["241", "242", "243", "244", "245"],
    "petroleumraffinaderijen": ["191", "192"],
    "datacenters": ["6190"],
    "spoortransport": ["4910", "4920"],
    # Tier 2: High HV — KBO Open Data only
    "waterzuivering": ["3600", "3700"],
    "afvalverwerkingsindustrie": ["382", "383", "390"],
    "automobielfabrieken": ["291", "292", "293"],
    "scheepsbouw": ["301", "302", "303"],
    "papierfabrieken": ["171", "172"],
    "rubberindustrie": ["221", "222"],
    "glasindustrie": ["231", "235"],
    "elektronica-fabrieken": ["261", "262", "263", "271", "272", "273", "274"],
    "machinebouwers": ["281", "282", "283", "284", "289"],
    "metaalverwerkingsbedrijven": ["251", "252", "253", "255", "256", "257", "259"],
    "voedingsindustrie": [
        "101",
        "102",
        "103",
        "104",
        "105",
        "106",
        "107",
        "108",
        "109",
        "110",
    ],
    "diervoederfabricage": ["1091", "1092"],
    "textielfabricage": ["131", "132"],
    # Tier 3: Moderate HV — KBO Open Data only
    "ziekenhuizen": ["8610"],
    "logistiekverleners": ["5210", "5220", "5221", "5224"],
    "havenactiviteiten": ["5222", "5223"],
    "bouwbedrijven": ["4110", "4120", "4211", "4212", "4213", "4221", "4222", "4223"],
    "universiteiten": ["8542"],
    "ingenieurs-adviesbureaus": ["7112"],
    "grote-bedrijfsgebouwen": ["6820"],
    "steengroeven": ["0812"],
    "tuinbouwbedrijven-industrieel": ["0113", "0119", "013"],
    "intensieve-veehouderij": ["0147"],
    "snellaadstations": ["4799"],
}
