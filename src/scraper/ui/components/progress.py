"""Live progress helpers for the Streamlit UI."""

from __future__ import annotations

from contextlib import contextmanager
from io import StringIO
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator


@contextmanager
def pipeline_spinner(label: str = "Running pipeline…") -> Iterator[StringIO]:
    """Context manager: shows a spinner while running; yields a log buffer."""
    import streamlit as st

    buf = StringIO()
    with st.spinner(label):
        yield buf
