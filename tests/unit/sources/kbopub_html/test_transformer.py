from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

from scraper.sources.kbopub_html.parser import FunctionHolderRow
from scraper.sources.kbopub_html.transformer import function_holder_to_observation

_KBO = "0439401387"
_RUN_ID = uuid4()
_SNAPSHOT = datetime(2026, 5, 11, 12, 0, 0, tzinfo=UTC)
_URL = "https://kbopub.economie.fgov.be/kbopub/toonondernemingps.html?lang=nl&ondernemingsnummer=0439401387"

_BELLOCK_ROW = FunctionHolderRow(
    role="Bestuurder",
    role_canonical="director",
    name="Boonen, Jan",
    is_legal_person=False,
    linked_kbo=None,
    since=date(2024, 3, 27),
    raw_html="<tr><td>Bestuurder</td><td>Boonen, Jan</td></tr>",
)


def test_observation_kbo_number() -> None:
    obs = function_holder_to_observation(_KBO, _BELLOCK_ROW, _RUN_ID, _SNAPSHOT, source_url=_URL)
    assert obs.kbo_number == _KBO


def test_observation_field() -> None:
    obs = function_holder_to_observation(_KBO, _BELLOCK_ROW, _RUN_ID, _SNAPSHOT, source_url=_URL)
    assert obs.field == "function_holder"


def test_observation_source() -> None:
    obs = function_holder_to_observation(_KBO, _BELLOCK_ROW, _RUN_ID, _SNAPSHOT, source_url=_URL)
    assert obs.source == "kbopub"


def test_observation_confidence() -> None:
    obs = function_holder_to_observation(_KBO, _BELLOCK_ROW, _RUN_ID, _SNAPSHOT, source_url=_URL)
    assert obs.confidence == 0.95


def test_observation_source_url() -> None:
    obs = function_holder_to_observation(_KBO, _BELLOCK_ROW, _RUN_ID, _SNAPSHOT, source_url=_URL)
    assert obs.source_url == _URL


def test_observation_value_name() -> None:
    obs = function_holder_to_observation(_KBO, _BELLOCK_ROW, _RUN_ID, _SNAPSHOT, source_url=_URL)
    assert obs.value["name"] == "Boonen, Jan"


def test_observation_value_role_lowercase() -> None:
    obs = function_holder_to_observation(_KBO, _BELLOCK_ROW, _RUN_ID, _SNAPSHOT, source_url=_URL)
    assert obs.value["role"] == "bestuurder"


def test_observation_value_role_canonical() -> None:
    obs = function_holder_to_observation(_KBO, _BELLOCK_ROW, _RUN_ID, _SNAPSHOT, source_url=_URL)
    assert obs.value["role_canonical"] == "director"


def test_observation_value_since_iso() -> None:
    obs = function_holder_to_observation(_KBO, _BELLOCK_ROW, _RUN_ID, _SNAPSHOT, source_url=_URL)
    assert obs.value["since"] == "2024-03-27"


def test_observation_value_is_legal_person_false() -> None:
    obs = function_holder_to_observation(_KBO, _BELLOCK_ROW, _RUN_ID, _SNAPSHOT, source_url=_URL)
    assert obs.value["is_legal_person"] is False


def test_observation_value_linked_kbo_none() -> None:
    obs = function_holder_to_observation(_KBO, _BELLOCK_ROW, _RUN_ID, _SNAPSHOT, source_url=_URL)
    assert obs.value["linked_kbo"] is None


def test_observation_value_since_none_when_no_date() -> None:
    row = FunctionHolderRow(
        role="Commissaris",
        role_canonical="auditor",
        name="Audit Partners BV",
        is_legal_person=True,
        linked_kbo=None,
        since=None,
        raw_html="<tr><td>Commissaris</td><td>Audit Partners BV</td></tr>",
    )
    obs = function_holder_to_observation(_KBO, row, _RUN_ID, _SNAPSHOT)
    assert obs.value["since"] is None


def test_observation_legal_person_holder() -> None:
    row = FunctionHolderRow(
        role="Bestuurder",
        role_canonical="director",
        name="ACME BV met KBO 0502699332",
        is_legal_person=True,
        linked_kbo="0502699332",
        since=date(2022, 1, 1),
        raw_html="<tr><td>Bestuurder</td><td>ACME BV met KBO 0502699332</td></tr>",
    )
    obs = function_holder_to_observation(_KBO, row, _RUN_ID, _SNAPSHOT)
    assert obs.value["is_legal_person"] is True
    assert obs.value["linked_kbo"] == "0502699332"


def test_observation_url_pattern() -> None:
    obs = function_holder_to_observation(_KBO, _BELLOCK_ROW, _RUN_ID, _SNAPSHOT, source_url=_URL)
    assert obs.source_url is not None
    assert "kbopub.economie.fgov.be" in obs.source_url
    assert "0439401387" in obs.source_url
