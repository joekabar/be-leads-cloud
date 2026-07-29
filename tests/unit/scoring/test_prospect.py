from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from scraper.scoring.prospect import ProspectScore, compute_prospect_score, refresh_prospect_scores

_WEIGHTS = (0.45, 0.20, 0.20, 0.15)


def _pool_with_fetch(rows: list[dict[str, Any]]) -> tuple[AsyncMock, AsyncMock]:
    """Pool whose ``companies_current`` read returns *rows*, plus the acquired connection.

    The upsert runs in bounded batches on a single acquired connection, so the assertions
    belong on ``conn.executemany`` rather than on the pool.
    """
    pool = AsyncMock()
    pool.fetch.return_value = rows

    conn = AsyncMock()
    acquire_cm = MagicMock()
    acquire_cm.__aenter__ = AsyncMock(return_value=conn)
    acquire_cm.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=acquire_cm)
    return pool, conn


class TestRefreshProspectScores:
    async def test_returns_zero_when_view_empty(self) -> None:
        pool, conn = _pool_with_fetch([])
        result = await refresh_prospect_scores(pool)
        assert result == 0
        conn.executemany.assert_not_called()

    async def test_upserts_one_kbo_and_returns_count(self) -> None:
        pool, conn = _pool_with_fetch(
            [
                {"kbo_number": "0123456789", "field": "nace_code", "value": {"code": "35110"}},
                {"kbo_number": "0123456789", "field": "status", "value": {"value": "active"}},
            ]
        )
        result = await refresh_prospect_scores(pool)
        assert result == 1
        conn.executemany.assert_called_once()
        rows = conn.executemany.call_args[0][1]
        assert len(rows) == 1
        assert rows[0][0] == "0123456789"

    async def test_upserts_multiple_kbos(self) -> None:
        pool, _conn = _pool_with_fetch(
            [
                {"kbo_number": "0100000001", "field": "status", "value": {"value": "active"}},
                {"kbo_number": "0200000002", "field": "status", "value": {"value": "active"}},
            ]
        )
        result = await refresh_prospect_scores(pool)
        assert result == 2


def _score(**fields: object) -> ProspectScore:
    return compute_prospect_score("0123456789", dict(fields))


class TestStatusValueKey:
    """The status observation is written as {"value": ...}, not {"text": ...}.

    Both producers (kbo_dump transformer and ingester) emit {"value": "active"} /
    {"value": "deleted"}, but the scorer only read the "text" key — so is_active was
    False for every company in the database and business_activity was pinned at 0.0,
    silently zeroing 20% of the prospect score. The pre-existing tests all used the
    "text" shape, which is why they passed while production was wrong.
    """

    def test_value_key_active_counts_as_active(self) -> None:
        assert _score(status={"value": "active"}).business_activity == pytest.approx(0.5)

    def test_value_key_with_financial_gives_full_activity(self) -> None:
        s = _score(status={"value": "active"}, revenue_2024={"amount": 1_000_000})
        assert s.business_activity == pytest.approx(1.0)

    def test_value_key_deleted_is_not_active(self) -> None:
        assert _score(status={"value": "deleted"}).business_activity == 0.0

    def test_value_key_is_case_insensitive(self) -> None:
        assert _score(status={"value": "Actief"}).business_activity == pytest.approx(0.5)

    def test_text_key_still_supported(self) -> None:
        """Kept working so any other source using "text" is not silently dropped."""
        assert _score(status={"text": "active"}).business_activity == pytest.approx(0.5)

    def test_real_shape_lifts_overall_score(self) -> None:
        """Regression: this combination scored 0.133 in production, not 0.233."""
        s = _score(status={"value": "active"}, phone={"e164": "+3290000000"})
        assert s.business_activity == pytest.approx(0.5)
        assert s.overall_prospect > 0.15


class TestComputeProspectScore:
    def test_empty_fields_returns_zeros(self) -> None:
        s = _score()
        assert s.hv_probability == 0.0
        assert s.business_activity == 0.0
        assert s.contact_quality == 0.0
        assert s.growth_signal == 0.0
        assert s.overall_prospect == 0.0

    def test_growth_signal_always_zero_phase0(self) -> None:
        s = _score(
            nace_code={"code": "35110"},
            status={"text": "active"},
            phone={"e164": "+3290000000"},
        )
        assert s.growth_signal == 0.0

    # ── hv_probability isolation ───────────────────────────────────────────────

    def test_t1_nace_drives_hv(self) -> None:
        s = _score(nace_code={"code": "35110"})
        assert s.hv_probability == pytest.approx(1.00)
        assert s.business_activity == 0.0
        assert s.contact_quality == 0.0

    def test_unknown_nace_gives_zero_hv(self) -> None:
        s = _score(nace_code={"code": "99999"})
        assert s.hv_probability == 0.0

    def test_missing_nace_gives_zero_hv(self) -> None:
        s = _score(status={"text": "active"})
        assert s.hv_probability == 0.0

    def test_nace_val_without_code_key(self) -> None:
        s = _score(nace_code={"description": "unknown"})
        assert s.hv_probability == 0.0

    # ── business_activity isolation ────────────────────────────────────────────

    def test_active_plus_financial_gives_1(self) -> None:
        s = _score(
            status={"text": "Actief"},
            revenue_2023={"eur": 500000},
        )
        assert s.business_activity == pytest.approx(1.0)
        assert s.hv_probability == 0.0
        assert s.contact_quality == 0.0

    def test_actief_nl_recognised(self) -> None:
        s = _score(status={"text": "actief"}, employees_2024={"count": 50})
        assert s.business_activity == pytest.approx(1.0)

    def test_active_without_financial_gives_half(self) -> None:
        s = _score(status={"text": "active"})
        assert s.business_activity == pytest.approx(0.5)

    def test_financial_without_active_gives_quarter(self) -> None:
        s = _score(revenue_2024={"eur": 100000})
        assert s.business_activity == pytest.approx(0.25)

    def test_inactive_status_gives_zero_activity(self) -> None:
        s = _score(status={"text": "stopped"})
        assert s.business_activity == 0.0

    def test_no_status_no_financial_gives_zero(self) -> None:
        s = _score(name={"text": "Acme"})
        assert s.business_activity == 0.0

    # ── contact_quality isolation ──────────────────────────────────────────────

    def test_all_three_contacts_gives_1(self) -> None:
        s = _score(
            phone={"e164": "+32470000000"},
            email={"address": "x@x.be"},
            website={"url": "https://x.be"},
        )
        assert s.contact_quality == pytest.approx(1.0)
        assert s.business_activity == 0.0

    def test_two_contacts(self) -> None:
        s = _score(phone={"e164": "+32470000000"}, email={"address": "x@x.be"})
        assert s.contact_quality == pytest.approx(2 / 3, abs=1e-5)

    def test_one_contact(self) -> None:
        s = _score(phone={"e164": "+32470000000"})
        assert s.contact_quality == pytest.approx(1 / 3, abs=1e-5)

    def test_no_contacts(self) -> None:
        s = _score(name={"text": "Acme"})
        assert s.contact_quality == 0.0

    # ── overall_prospect weighting ─────────────────────────────────────────────

    def test_weighting_formula_exact(self) -> None:
        s = _score(
            nace_code={"code": "35110"},  # hv=1.00
            status={"text": "active"},  # activity=0.5 (no financial)
            phone={"e164": "+32470"},  # cq=1/3
            email={"address": "x@x.be"},  # cq=2/3
            website={"url": "https://x"},  # cq=1.0
        )
        expected = (
            _WEIGHTS[0] * s.hv_probability
            + _WEIGHTS[1] * s.business_activity
            + _WEIGHTS[2] * s.contact_quality
            + _WEIGHTS[3] * s.growth_signal
        )
        assert s.overall_prospect == pytest.approx(expected, abs=1e-9)

    def test_overall_bounded_zero_to_one(self) -> None:
        for hv_code in ["35110", "43211", "99999"]:
            s = _score(
                nace_code={"code": hv_code},
                status={"text": "active"},
                revenue_2024={"eur": 1},
                phone={"e164": "+32470"},
                email={"address": "x@x.be"},
                website={"url": "https://x"},
            )
            assert 0.0 <= s.overall_prospect <= 1.0

    def test_kbo_number_preserved(self) -> None:
        s = compute_prospect_score("0987654321", {})
        assert s.kbo_number == "0987654321"

    def test_result_is_frozen_dataclass(self) -> None:
        s = _score()
        assert isinstance(s, ProspectScore)
        with pytest.raises((AttributeError, TypeError)):
            s.hv_probability = 0.99  # type: ignore[misc]
