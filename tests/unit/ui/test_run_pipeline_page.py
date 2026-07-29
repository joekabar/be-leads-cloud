"""Import-smoke test for ui/pages/run_pipeline.py (Streamlit mocked)."""

from __future__ import annotations

import contextlib
import importlib
import sys
from unittest.mock import MagicMock, patch


class _SessionState(dict):
    """Mimic Streamlit's session_state: both dict and attribute access."""

    def __getattr__(self, key: str) -> object:
        try:
            return self[key]
        except KeyError as exc:
            raise AttributeError(key) from exc

    def __setattr__(self, key: str, value: object) -> None:
        self[key] = value


def _ctx(mock: MagicMock) -> MagicMock:
    mock.__enter__ = MagicMock(return_value=mock)
    mock.__exit__ = MagicMock(return_value=False)
    return mock


def _make_st_mock() -> MagicMock:
    st = MagicMock()
    st.selectbox.return_value = 0
    st.multiselect.return_value = []
    st.checkbox.return_value = False
    st.button.return_value = False  # don't trigger the run path
    st.radio.return_value = "nl"
    st.slider.return_value = 25
    st.number_input.return_value = 720
    st.text_input.return_value = ""
    st.columns.return_value = [_ctx(MagicMock()), _ctx(MagicMock())]
    st.expander.return_value = _ctx(MagicMock())
    st.session_state = _SessionState()
    return st


class TestRunPipelinePageImport:
    def test_page_importable_with_db_url_set(self) -> None:
        st = _make_st_mock()
        city_options = [("antwerpen", "Antwerpen", ["2000"])]
        sector_options = [("elektriciens", "Elektriciens")]

        with (
            patch.dict(sys.modules, {"streamlit": st}),
            patch.dict("os.environ", {"DATABASE_URL": "postgresql://x/y"}),
            patch("scraper.ui.components.pickers.load_city_options", return_value=city_options),
            patch(
                "scraper.ui.components.pickers.load_sector_options",
                return_value=sector_options,
            ),
        ):
            sys.modules.pop("scraper.ui.pages.run_pipeline", None)
            mod = importlib.import_module("scraper.ui.pages.run_pipeline")
            # Module executed its top-level Streamlit script without raising.
            assert mod is not None
            # st.stop must NOT have been hit (DATABASE_URL present, options present).
            st.stop.assert_not_called()

    def test_page_stops_without_db_url(self) -> None:
        st = _make_st_mock()
        # st.stop is a no-op MagicMock here, so the script continues; we only
        # assert it was called when no DSN is configured.
        #
        # The page resolves the DSN through database_url(), which loads .env from the
        # project root — so clearing os.environ is not enough to simulate "unset" on a
        # developer machine that has a .env. Patch the resolver itself.
        with (
            patch.dict(sys.modules, {"streamlit": st}),
            patch.dict("os.environ", {}, clear=True),
            patch("scraper.lib.config.database_url", return_value=""),
            patch(
                "scraper.ui.components.pickers.load_city_options",
                return_value=[("antwerpen", "Antwerpen", ["2000"])],
            ),
            patch(
                "scraper.ui.components.pickers.load_sector_options",
                return_value=[("elektriciens", "Elektriciens")],
            ),
        ):
            sys.modules.pop("scraper.ui.pages.run_pipeline", None)
            with contextlib.suppress(Exception):
                importlib.import_module("scraper.ui.pages.run_pipeline")
            st.stop.assert_called()
