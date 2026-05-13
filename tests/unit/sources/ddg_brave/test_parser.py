"""Unit tests for ddg_brave.parser."""

from __future__ import annotations

import json
from pathlib import Path

from scraper.sources.ddg_brave.parser import parse_brave, parse_ddg

_GOLDEN = Path("tests/golden/ddg_brave")


def _load(name: str) -> dict | list:  # type: ignore[type-arg]
    return json.loads((_GOLDEN / name).read_text(encoding="utf-8"))


class TestParseBrave:
    def test_bellock_fixture_returns_eight_results(self) -> None:
        payload = _load("brave_bellock_antwerpen.json")
        results = parse_brave(payload)  # type: ignore[arg-type]
        assert len(results) == 8

    def test_domains_stripped_of_www(self) -> None:
        payload = _load("brave_bellock_antwerpen.json")
        results = parse_brave(payload)  # type: ignore[arg-type]
        for r in results:
            assert not r.domain.startswith("www.")

    def test_language_preserved(self) -> None:
        payload = _load("brave_bellock_antwerpen.json")
        results = parse_brave(payload)  # type: ignore[arg-type]
        langs = {r.language for r in results}
        assert "nl" in langs

    def test_engine_field_is_brave(self) -> None:
        payload = _load("brave_bellock_antwerpen.json")
        results = parse_brave(payload)  # type: ignore[arg-type]
        assert all(r.engine == "brave" for r in results)

    def test_no_results_returns_empty_list(self) -> None:
        payload = _load("brave_no_results.json")
        results = parse_brave(payload)  # type: ignore[arg-type]
        assert results == []

    def test_missing_web_key_returns_empty_list(self) -> None:
        results = parse_brave({})
        assert results == []

    def test_first_result_is_bellock_dot_be(self) -> None:
        payload = _load("brave_bellock_antwerpen.json")
        results = parse_brave(payload)  # type: ignore[arg-type]
        assert results[0].domain == "bellock.be"
        assert results[0].url == "https://www.bellock.be/"


class TestParseDdg:
    def test_ddg_fixture_returns_correct_results(self) -> None:
        raw = _load("ddg_bellock_html.json")
        results = parse_ddg(raw)  # type: ignore[arg-type]
        assert len(results) == 3

    def test_domains_stripped_of_www(self) -> None:
        raw = _load("ddg_bellock_html.json")
        results = parse_ddg(raw)  # type: ignore[arg-type]
        assert not any(r.domain.startswith("www.") for r in results)

    def test_engine_field_is_ddg(self) -> None:
        raw = _load("ddg_bellock_html.json")
        results = parse_ddg(raw)  # type: ignore[arg-type]
        assert all(r.engine == "ddg" for r in results)

    def test_language_is_none_for_ddg(self) -> None:
        raw = _load("ddg_bellock_html.json")
        results = parse_ddg(raw)  # type: ignore[arg-type]
        assert all(r.language is None for r in results)

    def test_href_mapped_to_url(self) -> None:
        raw = _load("ddg_bellock_html.json")
        results = parse_ddg(raw)  # type: ignore[arg-type]
        assert results[0].url == "https://www.bellock.be/"


class TestParserEdgeCases:
    def test_brave_non_list_results_returns_empty(self) -> None:
        payload = {"web": {"results": "not-a-list"}}
        assert parse_brave(payload) == []

    def test_brave_non_dict_item_skipped(self) -> None:
        payload = {"web": {"results": ["not-a-dict", {"url": "https://bellock.be/", "title": "B"}]}}
        results = parse_brave(payload)
        assert len(results) == 1

    def test_brave_item_missing_url_skipped(self) -> None:
        payload = {"web": {"results": [{"title": "No URL item"}]}}
        assert parse_brave(payload) == []

    def test_ddg_non_dict_item_skipped(self) -> None:
        raw = ["not-a-dict", {"title": "OK", "href": "https://bellock.be/", "body": ""}]
        results = parse_ddg(raw)  # type: ignore[arg-type]
        assert len(results) == 1

    def test_ddg_item_missing_href_skipped(self) -> None:
        raw = [{"title": "No href", "body": "..."}]
        results = parse_ddg(raw)
        assert results == []
