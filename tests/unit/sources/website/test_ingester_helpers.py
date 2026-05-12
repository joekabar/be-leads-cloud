"""Unit tests for ingester helper functions (pure, no DB needed)."""

from __future__ import annotations

from scraper.sources.website.ingester import (
    _extract_activity_summary,
    _extract_phones_and_emails,
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
