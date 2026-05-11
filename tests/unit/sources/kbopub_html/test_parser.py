from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from scraper.sources.kbopub_html.parser import (
    detect_lang,
    parse_function_holders,
)

_GOLDEN = Path("tests/golden/kbopub_html")


def _read(name: str) -> str:
    return (_GOLDEN / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# detect_lang
# ---------------------------------------------------------------------------


def test_detect_lang_nl() -> None:
    assert detect_lang(_read("0439401387_bellock_nl.html")) == "nl"


def test_detect_lang_fr() -> None:
    assert detect_lang(_read("0345678901_french.html")) == "fr"


# ---------------------------------------------------------------------------
# parse_function_holders — Bellock (single NL holder, canonical happy path)
# ---------------------------------------------------------------------------


def test_bellock_single_holder() -> None:
    rows = parse_function_holders(_read("0439401387_bellock_nl.html"))
    assert len(rows) == 1
    h = rows[0]
    assert h.role == "Bestuurder"
    assert h.role_canonical == "director"
    assert h.name == "Boonen, Jan"
    assert h.is_legal_person is False
    assert h.linked_kbo is None
    assert h.since == date(2024, 3, 27)
    assert "Boonen" in h.raw_html


# ---------------------------------------------------------------------------
# parse_function_holders — no Functies section
# ---------------------------------------------------------------------------


def test_no_holders_returns_empty_list() -> None:
    rows = parse_function_holders(_read("0123456749_no_holders.html"))
    assert rows == []


# ---------------------------------------------------------------------------
# parse_function_holders — multiple roles
# ---------------------------------------------------------------------------


def test_multiple_roles_count() -> None:
    rows = parse_function_holders(_read("0234567890_multiple_roles.html"))
    assert len(rows) == 3


def test_multiple_roles_canonical_values() -> None:
    rows = parse_function_holders(_read("0234567890_multiple_roles.html"))
    canonicals = {r.role_canonical for r in rows}
    assert canonicals == {"director", "managing_director", "auditor"}


def test_multiple_roles_missing_date_is_none() -> None:
    rows = parse_function_holders(_read("0234567890_multiple_roles.html"))
    commissaris = next(r for r in rows if r.role == "Commissaris")
    assert commissaris.since is None


def test_multiple_roles_legal_form_suffix() -> None:
    rows = parse_function_holders(_read("0234567890_multiple_roles.html"))
    commissaris = next(r for r in rows if r.role == "Commissaris")
    assert commissaris.is_legal_person is True
    assert commissaris.linked_kbo is None


def test_multiple_roles_first_holder_date() -> None:
    rows = parse_function_holders(_read("0234567890_multiple_roles.html"))
    bestuurder = next(r for r in rows if r.role == "Bestuurder")
    assert bestuurder.since == date(2020, 1, 15)


# ---------------------------------------------------------------------------
# parse_function_holders — French page
# ---------------------------------------------------------------------------


def test_french_page_holder_count() -> None:
    rows = parse_function_holders(_read("0345678901_french.html"))
    assert len(rows) == 2


def test_french_page_role_canonical() -> None:
    rows = parse_function_holders(_read("0345678901_french.html"))
    roles = {r.role_canonical for r in rows}
    assert roles == {"managing_director", "manager"}


def test_french_page_date_parsed_correctly() -> None:
    rows = parse_function_holders(_read("0345678901_french.html"))
    delegue = next(r for r in rows if r.role == "Administrateur délégué")
    assert delegue.since == date(2019, 2, 10)


def test_french_page_no_date_is_none() -> None:
    rows = parse_function_holders(_read("0345678901_french.html"))
    gerant = next(r for r in rows if r.role == "Gérant")
    assert gerant.since is None


# ---------------------------------------------------------------------------
# parse_function_holders — legal-person holder
# ---------------------------------------------------------------------------


def test_legal_person_holder_detected() -> None:
    rows = parse_function_holders(_read("0456789012_legal_person_holder.html"))
    acme = next(r for r in rows if "ACME" in r.name)
    assert acme.is_legal_person is True
    assert acme.linked_kbo == "0502699332"


def test_legal_person_holder_linked_kbo() -> None:
    rows = parse_function_holders(_read("0456789012_legal_person_holder.html"))
    acme = next(r for r in rows if "ACME" in r.name)
    assert acme.role_canonical == "director"
    assert acme.since == date(2022, 1, 1)


def test_natural_person_holder_not_flagged() -> None:
    rows = parse_function_holders(_read("0456789012_legal_person_holder.html"))
    vermeersch = next(r for r in rows if "Vermeersch" in r.name)
    assert vermeersch.is_legal_person is False
    assert vermeersch.linked_kbo is None
    assert vermeersch.role_canonical == "permanent_representative"


# ---------------------------------------------------------------------------
# parse_function_holders — unknown role label
# ---------------------------------------------------------------------------

_UNKNOWN_ROLE_HTML = """\
<!DOCTYPE html>
<html lang="nl">
<head><meta charset="UTF-8"><title>Test</title></head>
<body>
<h1>Gegevens van de geregistreerde entiteit</h1>
<table>
  <tr><td class="I" colspan="4"><h2>Functies</h2></td></tr>
  <tr>
    <td class="QL">Erevoorzitter</td>
    <td class="QL">Peeters, Hugo</td>
    <td class="QL"></td>
  </tr>
</table>
</body>
</html>
"""


def test_unknown_role_kept_verbatim(capsys: pytest.CaptureFixture[str]) -> None:
    # structlog uses PrintLogger by default (not stdlib), so we check stdout.
    rows = parse_function_holders(_UNKNOWN_ROLE_HTML)
    assert len(rows) == 1
    assert rows[0].role == "Erevoorzitter"
    assert rows[0].role_canonical == "Erevoorzitter"
    captured = capsys.readouterr()
    assert "unknown_role_label" in captured.out


# ---------------------------------------------------------------------------
# parse_function_holders — missing "Sinds" date handled gracefully
# ---------------------------------------------------------------------------

_NO_DATE_HTML = """\
<!DOCTYPE html>
<html lang="nl">
<head><meta charset="UTF-8"><title>Test</title></head>
<body>
<h1>Gegevens van de geregistreerde entiteit</h1>
<table>
  <tr><td class="I" colspan="4"><h2>Functies</h2></td></tr>
  <tr>
    <td class="QL">Zaakvoerder</td>
    <td class="QL">Claeys, Anne</td>
    <td class="QL"></td>
  </tr>
</table>
</body>
</html>
"""


def test_missing_since_date_is_none() -> None:
    rows = parse_function_holders(_NO_DATE_HTML)
    assert len(rows) == 1
    assert rows[0].since is None
    assert rows[0].role_canonical == "manager"


# ---------------------------------------------------------------------------
# parse_function_holders — empty Functies section (header present, no rows)
# ---------------------------------------------------------------------------

_EMPTY_FUNCTIES_HTML = """\
<!DOCTYPE html>
<html lang="nl">
<head><meta charset="UTF-8"><title>Test</title></head>
<body>
<h1>Gegevens van de geregistreerde entiteit</h1>
<table>
  <tr><td class="I" colspan="4"><h2>Functies</h2></td></tr>
  <tr><td class="I" colspan="4"><h2>Activiteiten</h2></td></tr>
</table>
</body>
</html>
"""


def test_empty_functies_section_returns_empty_list() -> None:
    rows = parse_function_holders(_EMPTY_FUNCTIES_HTML)
    assert rows == []


# ---------------------------------------------------------------------------
# _parse_since edge cases (lines 128, 132-133, 135-136, 139-140)
# ---------------------------------------------------------------------------

# Import for direct testing of the private helper.
from scraper.sources.kbopub_html.parser import _parse_since  # noqa: E402


def test_parse_since_wrong_part_count() -> None:
    assert _parse_since("Sinds 27") is None  # only 1 part after strip


def test_parse_since_non_numeric_day() -> None:
    assert _parse_since("Sinds dag maart 2024") is None  # ValueError on int("dag")


def test_parse_since_unknown_month() -> None:
    assert _parse_since("Sinds 27 xyzmonth 2024") is None


def test_parse_since_invalid_date() -> None:
    assert _parse_since("Sinds 30 februari 2024") is None  # Feb 30 doesn't exist


# ---------------------------------------------------------------------------
# parse_function_holders — h2 not inside a tr (line 172)
# ---------------------------------------------------------------------------

_H2_WITHOUT_TR_HTML = """\
<!DOCTYPE html>
<html lang="nl">
<head><meta charset="UTF-8"><title>Test</title></head>
<body>
<h1>Gegevens van de geregistreerde entiteit</h1>
<h2>Functies</h2>
<p>Bestuurder: Claeys, Anne</p>
</body>
</html>
"""


def test_h2_functies_without_parent_tr_returns_empty() -> None:
    rows = parse_function_holders(_H2_WITHOUT_TR_HTML)
    assert rows == []


# ---------------------------------------------------------------------------
# parse_function_holders — tr with < 2 tds (line 184) and empty role (line 188)
# ---------------------------------------------------------------------------

_SPARSE_ROWS_HTML = """\
<!DOCTYPE html>
<html lang="nl">
<head><meta charset="UTF-8"><title>Test</title></head>
<body>
<h1>Gegevens van de geregistreerde entiteit</h1>
<table>
  <tr><td class="I" colspan="4"><h2>Functies</h2></td></tr>
  <tr><td class="QL">only-one-td</td></tr>
  <tr><td class="QL"></td><td class="QL">Name With Empty Role</td></tr>
  <tr>
    <td class="QL">Bestuurder</td>
    <td class="QL">Valid Person</td>
    <td class="QL"><span class="upd">Sinds 1 januari 2020</span></td>
  </tr>
</table>
</body>
</html>
"""


def test_sparse_rows_skipped_valid_row_kept() -> None:
    rows = parse_function_holders(_SPARSE_ROWS_HTML)
    assert len(rows) == 1
    assert rows[0].name == "Valid Person"
