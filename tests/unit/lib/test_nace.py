"""Unit tests for NACE code parsing/normalisation used by the UI search parameters."""

from __future__ import annotations

import pytest

from scraper.lib.errors import InvalidNaceError
from scraper.lib.nace import normalize_nace, parse_nace_input


class TestNormalizeNace:
    def test_strips_dots(self) -> None:
        """KBO Open Data stores NACE without dots (43211, not 43.21)."""
        assert normalize_nace("43.21") == "4321"

    def test_strips_surrounding_whitespace(self) -> None:
        assert normalize_nace("  4321 ") == "4321"

    def test_passes_through_plain_digits(self) -> None:
        assert normalize_nace("43211") == "43211"

    @pytest.mark.parametrize("bad", ["", "   ", "abc", "43a1", "43-21", "43,21", "."])
    def test_rejects_non_numeric(self, bad: str) -> None:
        with pytest.raises(InvalidNaceError):
            normalize_nace(bad)

    def test_rejects_too_long(self) -> None:
        """NACE codes are at most 5 digits; longer is a typo, not a prefix."""
        with pytest.raises(InvalidNaceError):
            normalize_nace("123456")


class TestParseNaceInput:
    def test_empty_input_returns_empty_list(self) -> None:
        assert parse_nace_input("") == []
        assert parse_nace_input("   ") == []

    def test_comma_separated(self) -> None:
        assert parse_nace_input("4321,4322") == ["4321", "4322"]

    def test_space_and_newline_separated(self) -> None:
        assert parse_nace_input("4321 4322\n4329") == ["4321", "4322", "4329"]

    def test_mixed_separators_and_dots(self) -> None:
        assert parse_nace_input("43.21, 43.22\n4329;4399") == ["4321", "4322", "4329", "4399"]

    def test_deduplicates_preserving_order(self) -> None:
        assert parse_nace_input("4321, 43.21, 4322") == ["4321", "4322"]

    def test_raises_on_any_invalid_entry(self) -> None:
        with pytest.raises(InvalidNaceError, match="oops"):
            parse_nace_input("4321, oops")
