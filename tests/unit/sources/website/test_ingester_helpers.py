"""Unit tests for ingester helper functions (pure, no DB needed)."""

from __future__ import annotations

from scraper.sources.website.ingester import (
    _extract_activity_summary,
    _extract_phones_and_emails,
    _visible_text,
)


class TestExtractPhonesAndEmails:
    def test_tel_href_extracted(self) -> None:
        html = '<a href="tel:+3232361306">bel ons</a>'
        phones, _ = _extract_phones_and_emails(html)
        assert any(raw == "+3232361306" for raw, _ in phones)

    def test_tel_href_confidence_0_85(self) -> None:
        html = '<a href="tel:+3232361306">bel ons</a>'
        phones, _ = _extract_phones_and_emails(html)
        conf = next(c for r, c in phones if r == "+3232361306")
        assert conf == 0.85

    def test_phone_text_regex_confidence_0_60(self) -> None:
        html = "<p>Bel ons op 03 236 13 06 voor meer info.</p>"
        phones, _ = _extract_phones_and_emails(html)
        assert any(c == 0.60 for _, c in phones)

    def test_mailto_href_extracted(self) -> None:
        html = '<a href="mailto:info@bellock.be">mail</a>'
        _, emails = _extract_phones_and_emails(html)
        assert any(raw == "info@bellock.be" for raw, _ in emails)

    def test_mailto_confidence_0_85(self) -> None:
        html = '<a href="mailto:info@bellock.be">mail</a>'
        _, emails = _extract_phones_and_emails(html)
        conf = next(c for r, c in emails if r == "info@bellock.be")
        assert conf == 0.85

    def test_email_text_regex_confidence_0_50(self) -> None:
        html = "<p>Contact us at support@example.be for help.</p>"
        _, emails = _extract_phones_and_emails(html)
        assert any(c == 0.50 for _, c in emails)

    def test_deduplication_href_vs_text(self) -> None:
        html = '<a href="mailto:info@x.be">info@x.be</a>'
        _, emails = _extract_phones_and_emails(html)
        # href wins (0.85), text should be deduplicated
        assert len([r for r, _ in emails if r == "info@x.be"]) == 1
        assert emails[0][1] == 0.85

    def test_empty_html(self) -> None:
        phones, emails = _extract_phones_and_emails("<html></html>")
        assert phones == []
        assert emails == []

    def test_subject_stripped_from_mailto(self) -> None:
        html = '<a href="mailto:info@x.be?subject=hello">mail</a>'
        _, emails = _extract_phones_and_emails(html)
        assert any("?" not in r for r, _ in emails)

    # False-positive regression tests — patterns seen in production logs.

    def test_svg_viewbox_not_a_phone(self) -> None:
        # SVG viewBox "0 0 512 512" was matching _PHONE_TEXT_RE against raw HTML.
        html = '<svg viewBox="0 0 512 512"><path d="M0 0"/></svg><p>Info.</p>'
        phones, _ = _extract_phones_and_emails(html)
        assert not any("512" in r for r, _ in phones)

    def test_css_decimal_not_a_phone(self) -> None:
        # CSS calc values with decimals (e.g. "0.326-1.527") were matching.
        html = "<style>.a { transform: translate(0.326, -1.527); }</style><p>Info.</p>"
        phones, _ = _extract_phones_and_emails(html)
        assert not any("." in r for r, _ in phones)

    def test_script_number_not_a_phone(self) -> None:
        # Numbers in JavaScript were matching (e.g. "0 0 640 512" in SVG viewBox vars).
        html = "<script>var w=640, h=512; var o=0;</script><p>Contact: 03 236 13 06</p>"
        phones, _ = _extract_phones_and_emails(html)
        phone_raws = [r for r, _ in phones]
        assert not any("640" in r for r in phone_raws)
        assert any("03 236 13 06" in r for r in phone_raws)

    def test_decimal_phone_skipped_by_regex(self) -> None:
        # Decimal values like "0.9393 12.0001" (SVG coordinates) must not match
        # because '.' is no longer in the character class.
        html = "<p>0.9393 12.0001</p>"
        phones, _ = _extract_phones_and_emails(html)
        assert not any("0.9" in r for r, _ in phones)


class TestVisibleText:
    def test_strips_script_content(self) -> None:
        html = "<script>var x = 0640512;</script><p>Hello</p>"
        text = _visible_text(html)
        assert "0640512" not in text
        assert "Hello" in text

    def test_strips_style_content(self) -> None:
        html = "<style>.phone { font-size: 0.875em; }</style><p>World</p>"
        text = _visible_text(html)
        assert "0.875" not in text
        assert "World" in text

    def test_strips_svg_content(self) -> None:
        html = '<svg viewBox="0 0 512 512"><path d="M0 0 L512 512"/></svg><p>Text</p>'
        text = _visible_text(html)
        assert "512" not in text
        assert "Text" in text

    def test_keeps_paragraph_text(self) -> None:
        html = "<html><body><p>Bel 03 236 13 06</p></body></html>"
        text = _visible_text(html)
        assert "03 236 13 06" in text


class TestExtractActivitySummary:
    def test_meta_description(self) -> None:
        content = "Electrical installations in Antwerp."
        html = f'<html><head><meta name="description" content="{content}"></head></html>'
        result = _extract_activity_summary(html)
        assert result == content

    def test_og_description(self) -> None:
        content = "Great products for your home."
        html = f'<html><head><meta property="og:description" content="{content}"></head></html>'
        result = _extract_activity_summary(html)
        assert result == content

    def test_falls_back_to_main_paragraph(self) -> None:
        body = "We are a Belgian company offering electrical services to homes and businesses."
        html = f"<html><body><main><p>{body}</p></main></body></html>"
        result = _extract_activity_summary(html)
        assert result is not None
        assert "electrical" in result.lower()

    def test_truncates_at_300(self) -> None:
        long_text = "A" * 400
        html = f'<html><head><meta name="description" content="{long_text}"></head></html>'
        result = _extract_activity_summary(html)
        assert result is not None
        assert len(result) == 300

    def test_short_description_skipped(self) -> None:
        html = '<html><head><meta name="description" content="Short."></head></html>'
        result = _extract_activity_summary(html)
        assert result is None

    def test_no_content_returns_none(self) -> None:
        html = "<html><body><p>Hi.</p></body></html>"
        result = _extract_activity_summary(html)
        assert result is None
