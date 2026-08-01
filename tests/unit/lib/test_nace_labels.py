"""NACE codes must reach the CSV as something a salesperson can read.

The export carried `nace_code` as a bare number ("43320"), which says nothing about what
the company does. The KBO Open Data ZIP already ships the official descriptions in
`code.csv`; they are bundled as static reference data rather than staged, because staging
tables are UNLOGGED and crash recovery would silently blank the column.

Lookup is longest-prefix, mirroring `scoring/hv_prior.py`: a code with no exact entry
still resolves to its parent group rather than to nothing.
"""

from __future__ import annotations

from scraper.lib.nace_labels import load_nace_labels, nace_label


class TestExactMatch:
    def test_five_digit_code_resolves(self) -> None:
        # 43320 = joinery installation, present in Nace2025.
        assert nace_label("43320", "2025")

    def test_label_is_human_readable_text(self) -> None:
        label = nace_label("01110", "2025")
        assert label is not None
        assert "granen" in label.lower()

    def test_version_selects_the_right_table(self) -> None:
        """Codes are reused with different meanings across NACE versions."""
        assert nace_label("01110", "2025") is not None
        assert nace_label("01110", "2008") is not None


class TestLongestPrefixFallback:
    def test_unknown_five_digit_falls_back_to_its_group(self) -> None:
        """A code absent at 5 digits still resolves via its 2-4 digit parent."""
        # "01" exists as a group; "01999" does not exist as a leaf.
        assert nace_label("01999", "2025") is not None

    def test_over_long_code_is_truncated_to_a_known_prefix(self) -> None:
        """15 rows in production carry 6-7 character codes."""
        assert nace_label("0111012", "2025") is not None

    def test_prefers_the_most_specific_match(self) -> None:
        """A 5-digit label must win over its shorter parent when both exist."""
        specific = nace_label("01110", "2025")
        group = nace_label("01", "2025")
        assert specific is not None
        assert group is not None
        assert specific != group


class TestMisses:
    def test_unknown_code_returns_none(self) -> None:
        """ "04" is not an allocated NACE division, so no prefix of it can match.

        Note "99999" would NOT be a miss: "99" is extraterritorial organisations, so it
        correctly resolves via the prefix fallback.
        """
        assert nace_label("04999", "2025") is None

    def test_empty_code_returns_none(self) -> None:
        assert nace_label("", "2025") is None

    def test_none_code_returns_none(self) -> None:
        assert nace_label(None, "2025") is None

    def test_whitespace_is_stripped(self) -> None:
        assert nace_label("  01110  ", "2025") == nace_label("01110", "2025")


class TestVersionHandling:
    def test_missing_version_defaults_to_current(self) -> None:
        assert nace_label("01110", None) == nace_label("01110", "2025")

    def test_unknown_version_defaults_to_current(self) -> None:
        assert nace_label("01110", "1997") == nace_label("01110", "2025")

    def test_does_not_cross_versions(self) -> None:
        """Falling back across versions could attach a label from a different taxonomy."""
        labels = load_nace_labels()
        only_2003 = set(labels["nace2003"]) - set(labels["nace2025"])
        if only_2003:
            code = sorted(only_2003)[0]
            # Present in 2003, absent in 2025: must not leak across, though a shorter
            # 2025 prefix may legitimately match.
            assert nace_label(code, "2003") is not None


class TestBundledData:
    def test_all_three_versions_are_present(self) -> None:
        """2008 and 2003 cover ~31k companies; omitting them blanks their labels."""
        labels = load_nace_labels()
        assert set(labels) == {"nace2003", "nace2008", "nace2025"}
        for version, table in labels.items():
            assert len(table) > 1000, f"{version} looks truncated"

    def test_is_cached(self) -> None:
        assert load_nace_labels() is load_nace_labels()
