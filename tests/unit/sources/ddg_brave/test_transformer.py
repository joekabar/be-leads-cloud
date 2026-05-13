"""Unit tests for ddg_brave.transformer."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from scraper.sources.ddg_brave.classifier import classify
from scraper.sources.ddg_brave.parser import parse_brave, parse_ddg
from scraper.sources.ddg_brave.transformer import query_to_observations

_GOLDEN = Path("tests/golden/ddg_brave")

_RUN_ID = uuid4()
_SNAPSHOT = datetime(2026, 5, 12, 15, 30, 0, tzinfo=UTC)
_KBO_BELLOCK = "0439401387"
_KBO_PLACEHOLDER = "9123456789"


def _classified_from_brave(fixture: str, name: str):  # type: ignore[return]
    payload = json.loads((_GOLDEN / fixture).read_text(encoding="utf-8"))
    results = parse_brave(payload)
    return [classify(r, name) for r in results]


def _classified_from_ddg(fixture: str, name: str):  # type: ignore[return]
    raw = json.loads((_GOLDEN / fixture).read_text(encoding="utf-8"))
    results = parse_ddg(raw)
    return [classify(r, name) for r in results]


class TestBellockBrave:
    def setup_method(self) -> None:
        classified = _classified_from_brave("brave_bellock_antwerpen.json", "Bellock")
        self.obs = query_to_observations(
            _KBO_BELLOCK,
            "Bellock",
            '"Bellock" Antwerpen',
            "brave",
            classified,
            _RUN_ID,
            _SNAPSHOT,
        )

    def test_two_observations_total(self) -> None:
        assert len(self.obs) == 2

    def test_one_website_observation(self) -> None:
        website_obs = [o for o in self.obs if o.field == "website"]
        assert len(website_obs) == 1

    def test_one_cross_validation_observation(self) -> None:
        cv_obs = [o for o in self.obs if o.field == "cross_validation"]
        assert len(cv_obs) == 1

    def test_website_confidence_brave(self) -> None:
        website_obs = next(o for o in self.obs if o.field == "website")
        assert website_obs.confidence == 0.55

    def test_website_url_is_bellock_be(self) -> None:
        website_obs = next(o for o in self.obs if o.field == "website")
        assert website_obs.value["url"] == "https://www.bellock.be/"

    def test_website_via_search_flag(self) -> None:
        website_obs = next(o for o in self.obs if o.field == "website")
        assert website_obs.value["via_search"] is True
        assert website_obs.value["search_engine"] == "brave"

    def test_cross_validation_counts(self) -> None:
        cv = next(o for o in self.obs if o.field == "cross_validation")
        assert cv.value["official_websites_count"] == 1
        assert cv.value["directory_hits_count"] == 3
        assert cv.value["social_links_count"] == 2
        assert cv.value["news_mentions"] == 0
        assert cv.value["total_results"] == 8

    def test_cross_validation_first_official_website(self) -> None:
        cv = next(o for o in self.obs if o.field == "cross_validation")
        assert cv.value["first_official_website"] == "https://www.bellock.be/"

    def test_source_is_brave(self) -> None:
        assert all(o.source == "brave" for o in self.obs)


class TestConfidenceDdg:
    def test_ddg_website_confidence_is_050(self) -> None:
        classified = _classified_from_ddg("ddg_bellock_html.json", "Bellock")
        obs = query_to_observations(
            _KBO_BELLOCK,
            "Bellock",
            '"Bellock" Antwerpen',
            "ddg",
            classified,
            _RUN_ID,
            _SNAPSHOT,
        )
        website_obs = [o for o in obs if o.field == "website"]
        assert len(website_obs) == 1
        assert website_obs[0].confidence == 0.50
        assert all(o.source == "ddg" for o in obs)


class TestNoResults:
    def test_no_results_emits_only_cv_observation(self) -> None:
        obs = query_to_observations(
            _KBO_BELLOCK,
            "Bellock",
            '"Bellock" Antwerpen',
            "brave",
            [],
            _RUN_ID,
            _SNAPSHOT,
        )
        assert len(obs) == 1
        assert obs[0].field == "cross_validation"
        assert obs[0].value["official_websites_count"] == 0
        assert obs[0].value["first_official_website"] is None


class TestPlaceholderKbo:
    def test_placeholder_kbo_accepted(self) -> None:
        classified = _classified_from_brave("brave_bellock_antwerpen.json", "Bellock")
        obs = query_to_observations(
            _KBO_PLACEHOLDER,
            "Bellock",
            '"Bellock" Antwerpen',
            "brave",
            classified,
            _RUN_ID,
            _SNAPSHOT,
        )
        assert all(o.kbo_number == _KBO_PLACEHOLDER for o in obs)


class TestAmbiguousTieBreaker:
    def test_be_tld_wins_over_com(self) -> None:
        classified = _classified_from_brave("brave_ambiguous_name.json", "Mediapro")
        obs = query_to_observations(
            _KBO_PLACEHOLDER,
            "Mediapro",
            '"Mediapro" Brussel',
            "brave",
            classified,
            _RUN_ID,
            _SNAPSHOT,
        )
        cv = next(o for o in obs if o.field == "cross_validation")
        assert cv.value["first_official_website"] == "https://www.mediapro.be/"
        assert cv.value["official_websites_count"] == 2
