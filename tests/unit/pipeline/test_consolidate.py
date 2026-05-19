from __future__ import annotations

from rapidfuzz import fuzz

from scraper.pipeline.consolidate import (
    ConsolidationMatch,
    _best_match,
    _KboInfo,
    _normalize_for_match,
)


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
