"""Unit tests for website structured.py (JSON-LD extractor)."""

from __future__ import annotations

from pathlib import Path

from scraper.sources.website.structured import extract_jsonld

_GOLDEN = Path("tests/golden/website")


def _html(name: str) -> str:
    return (_GOLDEN / name).read_text(encoding="utf-8")


class TestExtractJsonld:
    def test_wordpress_finds_one_entity(self) -> None:
        entities = extract_jsonld(_html("wordpress_local_business.html"))
        assert len(entities) == 1

    def test_wordpress_type_and_name(self) -> None:
        e = extract_jsonld(_html("wordpress_local_business.html"))[0]
        assert e.type == "LocalBusiness"
        assert e.name == "Bellock"

    def test_wordpress_two_phones(self) -> None:
        e = extract_jsonld(_html("wordpress_local_business.html"))[0]
        assert len(e.telephones) == 2
        assert "+3232361306" in e.telephones
        assert "+32474123456" in e.telephones

    def test_wordpress_one_email(self) -> None:
        e = extract_jsonld(_html("wordpress_local_business.html"))[0]
        assert e.emails == ["info@bellock.be"]

    def test_wordpress_address(self) -> None:
        e = extract_jsonld(_html("wordpress_local_business.html"))[0]
        assert len(e.addresses) == 1
        a = e.addresses[0]
        assert a["streetAddress"] == "Lange Van Bloerstraat 116"
        assert a["postalCode"] == "2060"
        assert a["addressLocality"] == "Antwerpen"
        assert a["addressCountry"] == "BE"

    def test_wordpress_opening_hours(self) -> None:
        e = extract_jsonld(_html("wordpress_local_business.html"))[0]
        assert len(e.opening_hours) == 2
        assert "Mo-Fr 08:00-17:00" in e.opening_hours
        assert "Sa 09:00-12:00" in e.opening_hours

    def test_squarespace_org_employee(self) -> None:
        entities = extract_jsonld(_html("squarespace_org.html"))
        assert len(entities) == 1
        e = entities[0]
        assert e.type == "Organization"
        assert e.employees == ["Jan Boonen"]

    def test_custom_no_jsonld_returns_empty(self) -> None:
        entities = extract_jsonld(_html("custom_no_jsonld.html"))
        assert entities == []

    def test_malformed_script_skipped(self) -> None:
        good = '{"@type":"LocalBusiness","name":"OK","telephone":"+3232000001"}'
        html = (
            "<html><body>"
            '<script type="application/ld+json">{bad json,,}</script>'
            f'<script type="application/ld+json">{good}</script>'
            "</body></html>"
        )
        entities = extract_jsonld(html)
        assert len(entities) == 1
        assert entities[0].name == "OK"

    def test_graph_wrapper_flattened(self) -> None:
        html = """
        <html><body>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@graph": [
            {"@type": "LocalBusiness", "name": "A", "telephone": "+3232000001"},
            {"@type": "Organization", "name": "B"}
          ]
        }
        </script>
        </body></html>
        """
        entities = extract_jsonld(html)
        assert len(entities) == 2
        names = {e.name for e in entities}
        assert names == {"A", "B"}

    def test_telephone_as_string(self) -> None:
        html = """
        <html><body>
        <script type="application/ld+json">
        {"@type": "LocalBusiness", "name": "X", "telephone": "+3232000001"}
        </script></body></html>
        """
        e = extract_jsonld(html)[0]
        assert e.telephones == ["+3232000001"]

    def test_telephone_as_list(self) -> None:
        html = """
        <html><body>
        <script type="application/ld+json">
        {"@type": "LocalBusiness", "name": "X", "telephone": ["+3232000001", "+3232000002"]}
        </script></body></html>
        """
        e = extract_jsonld(html)[0]
        assert len(e.telephones) == 2

    def test_schema_org_url_prefix_stripped(self) -> None:
        html = """
        <html><body>
        <script type="application/ld+json">
        {"@type": "https://schema.org/LocalBusiness", "name": "PrefixTest"}
        </script></body></html>
        """
        entities = extract_jsonld(html)
        assert len(entities) == 1
        assert entities[0].type == "LocalBusiness"

    def test_type_as_list(self) -> None:
        html = """
        <html><body>
        <script type="application/ld+json">
        {"@type": ["LocalBusiness", "Store"], "name": "TypeList"}
        </script></body></html>
        """
        entities = extract_jsonld(html)
        assert len(entities) == 1
        assert entities[0].name == "TypeList"

    def test_address_as_list(self) -> None:
        html = """
        <html><body>
        <script type="application/ld+json">
        {"@type": "LocalBusiness", "name": "X",
         "address": [
           {"streetAddress": "Str 1", "postalCode": "2000",
            "addressLocality": "City", "addressCountry": "BE"}
         ]}
        </script></body></html>
        """
        e = extract_jsonld(html)[0]
        assert len(e.addresses) == 1
        assert e.addresses[0]["streetAddress"] == "Str 1"

    def test_opening_hours_specification_dict(self) -> None:
        html = """
        <html><body>
        <script type="application/ld+json">
        {"@type": "LocalBusiness", "name": "X",
         "openingHoursSpecification": [
           {"dayOfWeek": "Monday", "opens": "09:00", "closes": "17:00"}
         ]}
        </script></body></html>
        """
        e = extract_jsonld(html)[0]
        assert "Monday 09:00-17:00" in e.opening_hours

    def test_opening_hours_specification_day_as_list(self) -> None:
        html = """
        <html><body>
        <script type="application/ld+json">
        {"@type": "LocalBusiness", "name": "X",
         "openingHoursSpecification": [
           {"dayOfWeek": ["Monday", "Tuesday"], "opens": "09:00", "closes": "17:00"}
         ]}
        </script></body></html>
        """
        e = extract_jsonld(html)[0]
        assert len(e.opening_hours) == 1
        assert "09:00-17:00" in e.opening_hours[0]

    def test_founder_single_dict(self) -> None:
        html = """
        <html><body>
        <script type="application/ld+json">
        {"@type": "Organization", "name": "X",
         "founder": {"@type": "Person", "name": "Jan Peeters"}}
        </script></body></html>
        """
        e = extract_jsonld(html)[0]
        assert "Jan Peeters" in e.founders

    def test_nested_list_in_graph(self) -> None:
        html = """
        <html><body>
        <script type="application/ld+json">
        [
          {"@type": "LocalBusiness", "name": "A"},
          {"@type": "Organization", "name": "B"}
        ]
        </script></body></html>
        """
        entities = extract_jsonld(html)
        assert len(entities) == 2
