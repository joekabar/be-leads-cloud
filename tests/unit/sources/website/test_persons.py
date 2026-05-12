"""Unit tests for website persons.py."""

from __future__ import annotations

from pathlib import Path

from scraper.sources.website.persons import extract_persons

_GOLDEN = Path("tests/golden/website")


def _html(name: str) -> str:
    return (_GOLDEN / name).read_text(encoding="utf-8")


class TestExtractPersons:
    def test_contact_page_microdata_three_persons(self) -> None:
        persons = extract_persons(_html("contact_page_with_team.html"))
        assert len(persons) == 3
        names = {p.name for p in persons}
        assert names == {"Marie Janssen", "Pieter De Wolf", "An Vermeersch"}

    def test_contact_page_microdata_source_label(self) -> None:
        persons = extract_persons(_html("contact_page_with_team.html"))
        assert all(p.source == "microdata" for p in persons)

    def test_contact_page_microdata_roles(self) -> None:
        persons = extract_persons(_html("contact_page_with_team.html"))
        role_map = {p.name: p.role for p in persons}
        assert role_map["Marie Janssen"] == "Directeur"
        assert role_map["Pieter De Wolf"] == "Sales Manager"

    def test_french_page_heuristic_two_persons(self) -> None:
        persons = extract_persons(_html("french_about_page.html"))
        assert len(persons) == 2
        names = {p.name for p in persons}
        assert names == {"Jean Dupont", "Marie Martin"}

    def test_french_page_heuristic_source_label(self) -> None:
        persons = extract_persons(_html("french_about_page.html"))
        assert all(p.source == "heuristic" for p in persons)

    def test_french_page_heuristic_roles_captured(self) -> None:
        persons = extract_persons(_html("french_about_page.html"))
        roles = {p.role for p in persons}
        # gérant or gérant role keyword detected
        assert any(r and "rant" in r.lower() for r in roles)

    def test_cap_at_four_persons(self) -> None:
        html = """
        <html><body>
        <div itemscope itemtype="https://schema.org/Person"><span itemprop="name">P1</span></div>
        <div itemscope itemtype="https://schema.org/Person"><span itemprop="name">P2</span></div>
        <div itemscope itemtype="https://schema.org/Person"><span itemprop="name">P3</span></div>
        <div itemscope itemtype="https://schema.org/Person"><span itemprop="name">P4</span></div>
        <div itemscope itemtype="https://schema.org/Person"><span itemprop="name">P5</span></div>
        </body></html>
        """
        persons = extract_persons(html)
        assert len(persons) == 4

    def test_no_persons_returns_empty(self) -> None:
        persons = extract_persons(_html("custom_no_jsonld.html"))
        assert persons == []

    def test_deduplication_by_name(self) -> None:
        person_tag = '<div itemscope itemtype="https://schema.org/Person">'
        name_tag = '<span itemprop="name">Jan Peeters</span></div>'
        html = f"<html><body>{person_tag}{name_tag}{person_tag}{name_tag}</body></html>"
        persons = extract_persons(html)
        assert len(persons) == 1
