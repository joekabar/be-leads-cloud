"""Unit tests for ui.components.progress (mocked streamlit)."""

from __future__ import annotations

from io import StringIO
from unittest.mock import MagicMock, patch


def test_pipeline_spinner_yields_string_io() -> None:
    """pipeline_spinner yields a StringIO buffer inside a spinner context."""
    mock_spinner = MagicMock()
    mock_spinner.__enter__ = MagicMock(return_value=None)
    mock_spinner.__exit__ = MagicMock(return_value=False)

    with patch("streamlit.spinner", return_value=mock_spinner):
        from scraper.ui.components.progress import pipeline_spinner

        with pipeline_spinner("Testing...") as buf:
            assert isinstance(buf, StringIO)
            buf.write("log line")

    mock_spinner.__enter__.assert_called_once()


def test_pipeline_spinner_default_label() -> None:
    """pipeline_spinner uses the default label when none is supplied."""
    mock_spinner = MagicMock()
    mock_spinner.__enter__ = MagicMock(return_value=None)
    mock_spinner.__exit__ = MagicMock(return_value=False)

    with patch("streamlit.spinner", return_value=mock_spinner) as patched:
        from importlib import reload

        import scraper.ui.components.progress as _mod

        reload(_mod)
        with _mod.pipeline_spinner() as buf:
            assert isinstance(buf, StringIO)
        patched.assert_called_once()
