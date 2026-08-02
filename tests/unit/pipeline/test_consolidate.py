from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from rapidfuzz import fuzz

from scraper.pipeline.consolidate import (
    ConsolidationMatch,
    _best_match,
    _gather_kbo_infos,
    _KboInfo,
    _normalize_for_match,
    _run_matching,
    _strip_diacritics,
    consolidate,
)


class TestStripDiacritics:
    def test_removes_accent(self) -> None:
        assert _strip_diacritics("Bückens") == "Buckens"

    def test_plain_ascii_unchanged(self) -> None:
        assert _strip_diacritics("hello") == "hello"

    def test_empty_string(self) -> None:
        assert _strip_diacritics("") == ""


class TestGatherKboInfos:
    async def test_placeholder_path_returns_infos(self) -> None:
        pool = _make_consolidate_pool(
            [{"kbo_number": "9000000001", "name": "Acme NV"}],
            [{"kbo_number": "9000000001", "postal_code": "2000", "city": "Antwerpen"}],
        )
        result = await _gather_kbo_infos(pool, is_placeholder=True)
        assert len(result) == 1
        assert result[0].kbo == "9000000001"
        assert result[0].postal_code == "2000"
        assert result[0].city == "antwerpen"

    async def test_real_path_uses_different_sql(self) -> None:
        pool = _make_consolidate_pool(
            [{"kbo_number": "0400000001", "name": "Real NV"}],
            [{"kbo_number": "0400000001", "postal_code": "1000", "city": "Brussel"}],
        )
        result = await _gather_kbo_infos(pool, is_placeholder=False)
        assert len(result) == 1
        assert result[0].kbo == "0400000001"

    async def test_missing_address_defaults_to_empty(self) -> None:
        pool = _make_consolidate_pool(
            [{"kbo_number": "9000000001", "name": "Acme NV"}],
            [],  # no address rows
        )
        result = await _gather_kbo_infos(pool, is_placeholder=True)
        assert len(result) == 1
        assert result[0].postal_code == ""
        assert result[0].city == ""


class TestRunMatching:
    def test_returns_match_for_identical_names(self) -> None:
        placeholder = _KboInfo(
            kbo="9000000001",
            name="Acme NV",
            name_norm=_normalize_for_match("Acme NV"),
            postal_code="2000",
            city="antwerpen",
        )
        real = _KboInfo(
            kbo="0400000001",
            name="Acme NV",
            name_norm=_normalize_for_match("Acme NV"),
            postal_code="2000",
            city="antwerpen",
        )
        postal_index = {"2000": [real]}
        city_index = {"antwerpen": [real]}
        real_name_norms = [real.name_norm]
        matches = _run_matching(
            [placeholder], [real], postal_index, city_index, real_name_norms, 80.0
        )
        assert len(matches) == 1
        assert matches[0].placeholder_kbo == "9000000001"
        assert matches[0].real_kbo == "0400000001"

    def test_skips_placeholder_with_empty_norm(self) -> None:
        placeholder = _KboInfo(kbo="9000000001", name="", name_norm="", postal_code="", city="")
        matches = _run_matching([placeholder], [], {}, {}, [], 80.0)
        assert matches == []

    def test_no_match_below_threshold(self) -> None:
        placeholder = _KboInfo(
            kbo="9000000001",
            name="Completely Different Name",
            name_norm=_normalize_for_match("Completely Different Name"),
            postal_code="",
            city="",
        )
        real = _KboInfo(
            kbo="0400000001",
            name="Nothing Like This",
            name_norm=_normalize_for_match("Nothing Like This"),
            postal_code="",
            city="",
        )
        matches = _run_matching([placeholder], [real], {}, {}, [real.name_norm], 80.0)
        assert matches == []


class TestPhoneVeto:
    """A disagreeing phone number vetoes a name match, at any score.

    Measured on production: matched pairs where both sides carry a phone agree 2,954
    times and disagree 303 times. The disagreements are concentrated in genuine false
    matches -- "Bakkerij Desmedt" (a bakery, +3259704201) was matched to "DRUKKERIJ
    DESMET" (a printing works, +3259332224) at score exactly 80.00 via name+postal,
    because both sit in 8400 Oostende.

    Name similarity alone cannot separate those: raising the threshold does not help
    (score-100 pairs still disagree 8.4% of the time) and neither does geography
    (same-province name_only matches disagree 15.2% vs 17.4% for cross-province). The
    phone is the discriminator. For a dataset that gets sold, a missed link is far
    cheaper than attaching one company's phone number to another company's record.
    """

    def _pair(
        self,
        *,
        name: str = "Acme NV",
        real_name: str = "Acme NV",
        ph_phone: str = "",
        real_phone: str = "",
    ) -> tuple[_KboInfo, _KboInfo]:
        placeholder = _KboInfo(
            kbo="9000000001",
            name=name,
            name_norm=_normalize_for_match(name),
            postal_code="2000",
            city="antwerpen",
            phone=ph_phone,
        )
        real = _KboInfo(
            kbo="0400000001",
            name=real_name,
            name_norm=_normalize_for_match(real_name),
            postal_code="2000",
            city="antwerpen",
            phone=real_phone,
        )
        return placeholder, real

    def _match(self, placeholder: _KboInfo, real: _KboInfo) -> list:
        return _run_matching(
            [placeholder],
            [real],
            {real.postal_code: [real]},
            {real.city: [real]},
            [real.name_norm],
            80.0,
        )

    def test_agreeing_phones_still_match(self) -> None:
        p, r = self._pair(ph_phone="+3221234567", real_phone="+3221234567")
        assert len(self._match(p, r)) == 1

    def test_conflicting_phones_veto_the_match(self) -> None:
        p, r = self._pair(ph_phone="+3221234567", real_phone="+3229999999")
        assert self._match(p, r) == []

    def test_veto_applies_even_to_a_perfect_name_score(self) -> None:
        """Identical names are not enough: two firms can share a trading name."""
        p, r = self._pair(
            name="Acme NV", real_name="Acme NV", ph_phone="+3221111111", real_phone="+3222222222"
        )
        assert self._match(p, r) == []

    def test_the_bakkerij_drukkerij_false_match_is_now_rejected(self) -> None:
        p, r = self._pair(
            name="Bakkerij Desmedt",
            real_name="DRUKKERIJ DESMET",
            ph_phone="+3259704201",
            real_phone="+3259332224",
        )
        assert self._match(p, r) == []

    def test_missing_placeholder_phone_cannot_veto(self) -> None:
        """No phone on one side means no evidence either way -- fall back to the name."""
        p, r = self._pair(ph_phone="", real_phone="+3221234567")
        assert len(self._match(p, r)) == 1

    def test_missing_real_phone_cannot_veto(self) -> None:
        p, r = self._pair(ph_phone="+3221234567", real_phone="")
        assert len(self._match(p, r)) == 1

    def test_both_phones_missing_matches_on_name(self) -> None:
        p, r = self._pair(ph_phone="", real_phone="")
        assert len(self._match(p, r)) == 1

    def test_veto_applies_on_the_name_only_pass(self) -> None:
        """Pass 3 has the worst false-match rate (17.8%), so it needs the veto most."""
        p = _KboInfo(
            kbo="9000000001",
            name="Acme NV",
            name_norm=_normalize_for_match("Acme NV"),
            postal_code="",
            city="",
            phone="+3221111111",
        )
        r = _KboInfo(
            kbo="0400000001",
            name="Acme NV",
            name_norm=_normalize_for_match("Acme NV"),
            postal_code="9999",
            city="elsewhere",
            phone="+3222222222",
        )
        assert _run_matching([p], [r], {}, {}, [r.name_norm], 80.0) == []


class TestConsolidate:
    async def test_returns_empty_when_no_placeholders(self) -> None:
        pool = _make_consolidate_pool(
            [],  # placeholder names
            [],  # placeholder addrs
            [{"kbo_number": "0400000001", "name": "Acme NV"}],  # real names
            [{"kbo_number": "0400000001", "postal_code": "2000", "city": "antwerpen"}],
        )
        matches = await consolidate(pool)
        assert matches == []

    async def test_returns_empty_when_no_reals(self) -> None:
        pool = _make_consolidate_pool(
            [{"kbo_number": "9000000001", "name": "Acme NV"}],
            [{"kbo_number": "9000000001", "postal_code": "2000", "city": "antwerpen"}],
            [],  # real names
            [],  # real addrs
        )
        matches = await consolidate(pool)
        assert matches == []

    async def test_matches_and_re_emits_observations(self) -> None:
        now = datetime.now(tz=UTC)
        pool = _make_consolidate_pool(
            [{"kbo_number": "9000000001", "name": "Acme NV"}],
            [{"kbo_number": "9000000001", "postal_code": "2000", "city": "antwerpen"}],
            [{"kbo_number": "0400000001", "name": "Acme NV"}],
            [{"kbo_number": "0400000001", "postal_code": "2000", "city": "antwerpen"}],
            # obs rows for the match
            [
                {
                    "field": "name",
                    "value": {"text": "Acme NV"},
                    "raw_value": None,
                    "source": "goudengids",
                    "source_url": None,
                    "observed_at": now,
                    "confidence": 0.80,
                }
            ],
        )
        # insert_many needs the acquire/transaction path to work
        matches = await consolidate(pool)
        assert len(matches) == 1
        assert matches[0].placeholder_kbo == "9000000001"
        assert matches[0].real_kbo == "0400000001"


# ── helpers shared by new tests ───────────────────────────────────────────────


def _make_consolidate_pool(
    placeholder_names: list[dict[str, str]] | None = None,
    placeholder_addrs: list[dict[str, str]] | None = None,
    real_names: list[dict[str, str]] | None = None,
    real_addrs: list[dict[str, str]] | None = None,
    obs_rows: list[dict[str, object]] | None = None,
    state_rows: list[dict[str, object]] | None = None,
    placeholder_phones: list[dict[str, str]] | None = None,
    real_phones: list[dict[str, str]] | None = None,
) -> AsyncMock:
    pool = AsyncMock()
    pool.execute.return_value = None

    tx_cm = MagicMock()
    tx_cm.__aenter__ = AsyncMock(return_value=None)
    tx_cm.__aexit__ = AsyncMock(return_value=False)

    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value={"id": 1})
    conn.transaction = MagicMock(return_value=tx_cm)

    acquire_cm = MagicMock()
    acquire_cm.__aenter__ = AsyncMock(return_value=conn)
    acquire_cm.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=acquire_cm)

    # Order mirrors _gather_kbo_infos: names, addresses, then phones -- once for the
    # placeholder population and once for the real one.
    fetch_sequence = [
        placeholder_names or [],
        placeholder_addrs or [],
        placeholder_phones or [],
        real_names or [],
        real_addrs or [],
        real_phones or [],
        # consolidate() then reads consolidation_state to skip placeholders already
        # processed for this snapshot. An empty table means "process everything".
        state_rows or [],
    ]
    if obs_rows is not None:
        fetch_sequence.append(obs_rows)

    pool.fetch = AsyncMock(side_effect=fetch_sequence)
    pool.fetchrow.return_value = None  # start_run uses execute, not fetchrow
    return pool


def _info(kbo: str, name: str, postal: str = "", city: str = "") -> _KboInfo:
    return _KboInfo(
        kbo=kbo,
        name=name,
        name_norm=_normalize_for_match(name),
        postal_code=postal,
        city=city.lower(),
    )


def _build_indexes(
    reals: list[_KboInfo],
) -> tuple[dict[str, list[_KboInfo]], dict[str, list[_KboInfo]], list[str]]:
    postal_index: dict[str, list[_KboInfo]] = {}
    city_index: dict[str, list[_KboInfo]] = {}
    for r in reals:
        if r.postal_code:
            postal_index.setdefault(r.postal_code, []).append(r)
        if r.city:
            city_index.setdefault(r.city, []).append(r)
    return postal_index, city_index, [r.name_norm for r in reals]


class TestNormalizeForMatch:
    def test_strips_legal_form(self) -> None:
        result = _normalize_for_match("Bellock NV")
        assert "nv" not in result
        assert "bellock" in result

    def test_lowercases(self) -> None:
        assert _normalize_for_match("BELLOCK") == _normalize_for_match("bellock")

    def test_strips_diacritics(self) -> None:
        result = _normalize_for_match("Bückens")
        assert "u" in result or "buckens" in result

    def test_empty_string_returns_empty(self) -> None:
        # normalize_name raises ValueError on empty; _normalize_for_match guards it
        result = _normalize_for_match("")
        assert result == ""


class TestBestMatch:
    def test_name_postal_match(self) -> None:
        placeholder = _info("9123456789", "Bellock", postal="2060")
        reals = [_info("0439401387", "Bellock NV", postal="2060")]
        match = _best_match(placeholder, reals, threshold=80.0)
        assert match is not None
        assert match.real_kbo == "0439401387"
        assert match.matched_on == "name+postal"
        assert match.score >= 80.0

    def test_name_city_match_when_postal_differs(self) -> None:
        placeholder = _info("9123456789", "Bellock", postal="2060", city="antwerpen")
        reals = [_info("0439401387", "Bellock NV", postal="9999", city="antwerpen")]
        match = _best_match(placeholder, reals, threshold=80.0)
        assert match is not None
        assert match.matched_on == "name+city"

    def test_no_match_different_names(self) -> None:
        placeholder = _info("9999999990", "Totally Different", postal="2060")
        reals = [_info("0439401387", "Bellock NV", postal="2060")]
        match = _best_match(placeholder, reals, threshold=80.0)
        assert match is None

    def test_acme_bv_vs_acme_nv_same_postal(self) -> None:
        placeholder = _info("9000000001", "Acme BV", postal="1000")
        reals = [_info("0400000197", "Acme NV", postal="1000")]
        match = _best_match(placeholder, reals, threshold=80.0)
        assert match is not None
        assert match.matched_on == "name+postal"

    def test_diacritic_match(self) -> None:
        placeholder = _info("9000000002", "Bückens", postal="3000")
        reals = [_info("0400000197", "Buckens NV", postal="3000")]
        match = _best_match(placeholder, reals, threshold=80.0)
        assert match is not None

    def test_name_only_match_high_threshold(self) -> None:
        placeholder = _info("9000000003", "Exact Same Company", postal="0000")
        reals = [_info("0400000197", "Exact Same Company NV", postal="9999")]
        match = _best_match(placeholder, reals, threshold=80.0)
        # name_only pass requires >= 90; "Exact Same Company" vs "Exact Same Company NV"
        score = fuzz.token_set_ratio(
            _normalize_for_match("Exact Same Company"),
            _normalize_for_match("Exact Same Company NV"),
        )
        if score >= 90:
            assert match is not None and match.matched_on == "name_only"
        else:
            assert match is None

    def test_empty_candidates_returns_none(self) -> None:
        placeholder = _info("9000000004", "Bellock", postal="2060")
        assert _best_match(placeholder, [], threshold=80.0) is None

    def test_consolidation_match_is_dataclass(self) -> None:
        placeholder = _info("9123456789", "Bellock", postal="2060")
        reals = [_info("0439401387", "Bellock NV", postal="2060")]
        match = _best_match(placeholder, reals, threshold=80.0)
        assert isinstance(match, ConsolidationMatch)


class TestBestMatchWithIndexes:
    """Verify that the index-optimised path produces identical results to the baseline."""

    def test_name_postal_match_with_index(self) -> None:
        placeholder = _info("9123456789", "Bellock", postal="2060")
        reals = [_info("0439401387", "Bellock NV", postal="2060")]
        pi, ci, norms = _build_indexes(reals)
        match = _best_match(
            placeholder, reals, 80.0, postal_index=pi, city_index=ci, real_name_norms=norms
        )
        assert match is not None
        assert match.real_kbo == "0439401387"
        assert match.matched_on == "name+postal"

    def test_name_city_match_with_index(self) -> None:
        placeholder = _info("9123456789", "Bellock", postal="2060", city="antwerpen")
        reals = [_info("0439401387", "Bellock NV", postal="9999", city="antwerpen")]
        pi, ci, norms = _build_indexes(reals)
        match = _best_match(
            placeholder, reals, 80.0, postal_index=pi, city_index=ci, real_name_norms=norms
        )
        assert match is not None
        assert match.matched_on == "name+city"

    def test_no_match_with_index(self) -> None:
        placeholder = _info("9999999990", "Totally Different", postal="2060")
        reals = [_info("0439401387", "Bellock NV", postal="2060")]
        pi, ci, norms = _build_indexes(reals)
        match = _best_match(
            placeholder, reals, 80.0, postal_index=pi, city_index=ci, real_name_norms=norms
        )
        assert match is None

    def test_name_only_via_extractone(self) -> None:
        placeholder = _info("9000000003", "Exact Same Company", postal="0000")
        reals = [_info("0400000197", "Exact Same Company NV", postal="9999")]
        pi, ci, norms = _build_indexes(reals)
        match = _best_match(
            placeholder, reals, 80.0, postal_index=pi, city_index=ci, real_name_norms=norms
        )
        score = fuzz.token_set_ratio(
            _normalize_for_match("Exact Same Company"),
            _normalize_for_match("Exact Same Company NV"),
        )
        if score >= 90:
            assert match is not None and match.matched_on == "name_only"
        else:
            assert match is None

    def test_empty_postal_placeholder_falls_through_to_city(self) -> None:
        """Placeholder with no postal_code skips Pass 1, still matches via city."""
        placeholder = _info("9000000005", "Bellock", postal="", city="gent")
        reals = [_info("0439401387", "Bellock NV", postal="9000", city="gent")]
        pi, ci, norms = _build_indexes(reals)
        match = _best_match(
            placeholder, reals, 80.0, postal_index=pi, city_index=ci, real_name_norms=norms
        )
        assert match is not None
        assert match.matched_on == "name+city"

    def test_index_and_baseline_agree_across_corpus(self) -> None:
        """Index path and baseline path produce identical results for a small corpus."""
        placeholders = [
            _info("9000000001", "Acme", postal="1000"),
            _info("9000000002", "Bückens", postal="3000"),
            _info("9000000003", "Unique Corp", postal="9999"),
        ]
        reals = [
            _info("0400000001", "Acme NV", postal="1000"),
            _info("0400000002", "Buckens NV", postal="3000"),
            _info("0400000003", "Other Co", postal="5000"),
        ]
        pi, ci, norms = _build_indexes(reals)

        for p in placeholders:
            baseline = _best_match(p, reals, 80.0)
            optimised = _best_match(
                p, reals, 80.0, postal_index=pi, city_index=ci, real_name_norms=norms
            )
            if baseline is None:
                assert optimised is None
            else:
                assert optimised is not None
                assert optimised.real_kbo == baseline.real_kbo
                assert optimised.matched_on == baseline.matched_on
