"""Tests for the UI theme module."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

from scraper.ui.theme import CSS, inject_theme


class TestCssTokens:
    def test_primary_color_present(self) -> None:
        assert "#1D70B8" in CSS

    def test_dark_heading_color_present(self) -> None:
        assert "#003078" in CSS

    def test_run_button_square(self) -> None:
        assert "border-radius: 0" in CSS

    def test_flag_bar_colors(self) -> None:
        assert "#000000" in CSS
        assert "#FAD205" in CSS
        assert "#EF3340" in CSS

    def test_score_high_green(self) -> None:
        assert "#00703C" in CSS

    def test_score_mid_orange(self) -> None:
        assert "#F47738" in CSS


class TestInjectTheme:
    def test_inject_theme_calls_markdown(self) -> None:
        stub = MagicMock()
        sys.modules["streamlit"] = stub
        inject_theme()
        stub.markdown.assert_called_once()
        call_args = stub.markdown.call_args
        html_arg = call_args[0][0]
        assert "<style>" in html_arg
        assert "unsafe_allow_html" in str(call_args)
