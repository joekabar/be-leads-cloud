"""Unit tests for ddg_brave.classifier."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scraper.sources.ddg_brave.classifier import classify, normalize_name
from scraper.sources.ddg_brave.parser import parse_brave, parse_ddg

_GOLDEN = Path("tests/golden/ddg_brave")


def _load_brave(name: str):  # type: ignore[return]
    payload = json.loads((_GOLDEN / name).read_text(encoding="utf-8"))
    return parse_brave(payload)


def _load_ddg(name: str):  # type: ignore[return]
    raw = json.loads((_GOLDEN / name).read_text(encoding="utf-8"))
    return parse_ddg(raw)


class TestNormalizeName:
    def test_simple_name(self) -> None:
        assert normalize_name("Bellock") == "bellock"

    def test_strips_legal_form_bv(self) -> None:
        assert normalize_name("Acme BV") == "acme"

    def test_strips_legal_form_nv(self) -> None:
        assert normalize_name("Groep NV") == "groep"

    def test_strips_diacritics(self) -> None:
        assert normalize_name("Bückens & Zoon") == "buckenszoon"

    def test_strips_ampersand(self) -> None:
        assert normalize_name("Smith & Jones") == "smithjones"

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            normalize_name("")


class TestClassifyBellockFixture:
    def setup_method(self) -> None:
        self.results = _load_brave("brave_bellock_antwerpen.json")

    def test_bellock_be_is_official(self) -> None:
        r = next(r for r in self.results if r.domain == "bellock.be")
        assert classify(r, "Bellock").bucket == "official_website"

    def test_goudengids_is_directory(self) -> None:
        r = next(r for r in self.results if "goudengids" in r.domain)
        assert classify(r, "Bellock").bucket == "directory"

    def test_pagesdor_is_directory(self) -> None:
        r = next(r for r in self.results if "pagesdor" in r.domain)
        assert classify(r, "Bellock").bucket == "directory"

    def test_kompass_is_directory(self) -> None:
        r = next(r for r in self.results if "kompass" in r.domain)
        assert classify(r, "Bellock").bucket == "directory"

    def test_facebook_is_social(self) -> None:
        r = next(r for r in self.results if "facebook" in r.domain)
        assert classify(r, "Bellock").bucket == "social"

    def test_linkedin_is_social(self) -> None:
        r = next(r for r in self.results if "linkedin" in r.domain)
        assert classify(r, "Bellock").bucket == "social"

    def test_blog_is_other(self) -> None:
        r = next(r for r in self.results if "elektriciensblog" in r.domain)
        assert classify(r, "Bellock").bucket == "other"

    def test_wikipedia_is_other(self) -> None:
        r = next(r for r in self.results if "wikipedia" in r.domain)
        assert classify(r, "Bellock").bucket == "other"


class TestClassifySpecialCases:
    def test_legal_form_suffix_stripped(self) -> None:
        results = _load_brave("brave_legal_form_suffix.json")
        official = next(r for r in results if r.domain == "acme.be")
        assert classify(official, "Acme BV").bucket == "official_website"

    def test_ambiguous_both_classified_as_official(self) -> None:
        results = _load_brave("brave_ambiguous_name.json")
        for r in results:
            if r.domain in ("mediapro.com", "mediapro.be"):
                assert classify(r, "Mediapro").bucket == "official_website", r.domain

    def test_social_before_official_facebook_wins(self) -> None:
        results = _load_brave("brave_bellock_antwerpen.json")
        fb = next(r for r in results if "facebook" in r.domain)
        # URL contains "bellock" but social wins
        assert classify(fb, "Bellock").bucket == "social"

    def test_diacritic_normalisation(self) -> None:
        # Construct a synthetic result with buckens-zoon.be domain
        from scraper.sources.ddg_brave.parser import SearchResult

        r = SearchResult(
            title="Bückens & Zoon",
            url="https://www.buckens-zoon.be/",
            domain="buckens-zoon.be",
            language="nl",
            engine="brave",
        )
        assert classify(r, "Bückens & Zoon").bucket == "official_website"

    def test_empty_company_name_raises(self) -> None:
        results = _load_brave("brave_bellock_antwerpen.json")
        with pytest.raises(ValueError):
            classify(results[0], "")

    def test_news_path_fragment(self) -> None:
        from scraper.sources.ddg_brave.parser import SearchResult

        r = SearchResult(
            title="Nieuws artikel",
            url="https://example.be/nieuws/elektriciens-gent",
            domain="example.be",
            language="nl",
            engine="brave",
        )
        assert classify(r, "SomeCo").bucket == "news"

    def test_hln_is_news(self) -> None:
        results = _load_brave("brave_bakk_brugge.json")
        hln = next(r for r in results if "hln" in r.domain)
        assert classify(hln, "Bakk").bucket == "news"

    def test_single_label_domain_handled(self) -> None:
        from scraper.sources.ddg_brave.classifier import _domain_stem_normalized

        assert _domain_stem_normalized("localhost") == "localhost"

    def test_is_official_empty_stem_returns_false(self) -> None:
        from scraper.sources.ddg_brave.classifier import _is_official

        assert _is_official(".", "bellock") is False

    def test_is_official_empty_company_returns_false(self) -> None:
        from scraper.sources.ddg_brave.classifier import _is_official

        assert _is_official("bellock.be", "") is False

    def test_non_be_contains_match_not_official(self) -> None:
        from scraper.sources.ddg_brave.parser import SearchResult

        r = SearchResult(
            title="Bellock cars",
            url="https://www.bellockcars.com/",
            domain="bellockcars.com",
            language="en",
            engine="brave",
        )
        assert classify(r, "Bellock").bucket == "other"
