"""Run Batch Pipeline — trigger a production batch run from the browser.

Thin Streamlit wrapper. All non-widget logic lives in importable, tested helpers:
- input validation / config mapping: ``ui/run_config.py::build_batch_config``
- pool + PoliteClient wiring:        ``ui/batch_runner.py::run_batch_job``
- daemon-thread job + queue:         ``ui/background.py``

Progress is shown by the **KBO Data Management → Live Progress** tab, which reads
``pipeline_progress`` — ``run_batch`` writes there via ``ProgressReporter``.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any

import streamlit as st

st.set_page_config(page_title="Run Batch Pipeline — be-leads", layout="wide", page_icon="🚀")

from scraper.ui.theme import inject_theme  # noqa: E402

inject_theme()

from scraper.db.pool import check_reachable  # noqa: E402
from scraper.lib.config import database_url  # noqa: E402
from scraper.ui.background import poll_job, start_async_job  # noqa: E402
from scraper.ui.batch_runner import run_batch_job  # noqa: E402
from scraper.ui.components.pickers import load_city_options, load_sector_options  # noqa: E402
from scraper.ui.run_config import build_batch_config  # noqa: E402

# ── Session state ───────────────────────────────────────────────────────────────
_DEFAULTS: dict[str, Any] = {
    "batch_running": False,
    "batch_queue": None,
    "batch_result": None,
}
for _k, _v in _DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

# Pick up a finished job before rendering, so the result shows on the first rerun.
if st.session_state.batch_running:
    _msg = poll_job(st.session_state.batch_queue)
    if _msg is not None:
        st.session_state.batch_running = False
        st.session_state.batch_result = _msg
        st.session_state.batch_queue = None

# ── Page ──────────────────────────────────────────────────────────────────────
st.title("Run Batch Pipeline")
st.caption(
    "Production stage-once batch run for a city x sectors. Watch progress on the "
    "**KBO Data Management -> Live Progress** tab."
)

# Must go through database_url(): it loads .env from the project root. A raw
# os.environ read executes before anything loads .env and yields "" on first click.
_raw_dsn = database_url()
if not _raw_dsn:
    st.error("**DATABASE_URL** is not set. Add it to `.env` or export it before launching.")
    st.stop()
dsn: str = str(_raw_dsn)  # st.stop() above halts the script when DSN is missing

city_options = load_city_options()
sector_options = load_sector_options()

if not city_options or not sector_options:
    st.error("No cities or sectors configured (check postcodes.toml / sectors.toml).")
    st.stop()

city_labels = [display for _, display, _ in city_options]
city_slugs = [slug for slug, _, _ in city_options]
city_idx = st.selectbox("City", range(len(city_labels)), format_func=lambda i: city_labels[i])
city_slug = city_slugs[city_idx]

all_sectors = st.checkbox("All sectors", value=False)
sector_slugs = [slug for slug, _ in sector_options]
selected_sectors = st.multiselect(
    "Sectors",
    options=sector_slugs,
    default=[],
    format_func=lambda s: next((lbl for slg, lbl in sector_options if slg == s), s),
    disabled=all_sectors,
)

extra_nace_raw = st.text_input(
    "Extra NACE codes (optional)",
    value="",
    placeholder="e.g. 3511, 35.12, 201",
    help=(
        "Target NACE codes directly, instead of or alongside the sector list. "
        "Comma/space/newline separated; dots optional (43.21 and 4321 both work). "
        "Each entry matches as a prefix, so '43' covers the whole division. "
        "With codes entered you may leave Sectors empty."
    ),
)

col_lang, col_pages = st.columns(2)
with col_lang:
    lang = st.radio("Language", ["nl", "fr"], horizontal=True)
with col_pages:
    max_pages = st.slider("Goudengids pages per sector", 1, 25, 25)

with st.expander("Sources", expanded=False):
    st.caption("Goudengids is blocked on datacenter IPs — leave it OFF on the server.")
    do_kbo = st.checkbox("KBO dump (re-emit from staged data)", value=True)
    do_goud = st.checkbox("Goudengids / Pagesdor", value=False)
    do_kbopub = st.checkbox("kbopub function holders", value=True)
    do_nbb = st.checkbox("NBB financials", value=True)
    do_web = st.checkbox("Company websites", value=True)
    do_search = st.checkbox("Search cross-validation", value=True)

with st.expander("Advanced", expanded=False):
    goud_hours = st.number_input(
        "Skip goudengids scraped within (hours)", min_value=0, value=720, step=24
    )
    ddg_hours = st.number_input(
        "Skip ddg/brave validated within (hours)", min_value=0, value=168, step=24
    )
    export_dir_str = st.text_input(
        "Export directory (optional)",
        value="",
        help="Server path, e.g. /data/exports/2026-06-01. Leave empty to skip CSV export.",
    )

run_btn = st.button("Run batch", type="primary", disabled=st.session_state.batch_running)

if run_btn:
    try:
        config = build_batch_config(
            city=city_slug,
            sectors=selected_sectors,
            all_sectors=all_sectors,
            extra_nace_raw=extra_nace_raw,
            lang="fr" if lang == "fr" else "nl",
            max_pages=int(max_pages),
            do_kbo_dump=do_kbo,
            do_goudengids=do_goud,
            do_kbopub=do_kbopub,
            do_nbb=do_nbb,
            do_website=do_web,
            do_search=do_search,
            export_dir=Path(export_dir_str) if export_dir_str.strip() else None,
            goudengids_skip_recent_hours=int(goud_hours),
            ddg_brave_skip_recent_hours=int(ddg_hours),
            nbb_subscription_key=os.environ.get("NBB_CBSO_API_KEY"),
            brave_subscription_key=os.environ.get("BRAVE_SEARCH_API_KEY"),
        )
    except ValueError as exc:
        st.error(str(exc))
    else:
        # Preflight the database before spawning the daemon thread. Without this a
        # stopped Postgres surfaces as a raw WinError 1225 from inside the thread,
        # minutes into a run that was never going to work.
        _db_problem = asyncio.run(check_reachable(dsn))
        if _db_problem is not None:
            st.error(_db_problem)
        else:
            st.session_state.batch_queue = start_async_job(lambda: run_batch_job(dsn, config))
            st.session_state.batch_running = True
            st.session_state.batch_result = None
            st.rerun()

if st.session_state.batch_running:
    st.warning(
        "Batch run in progress. A full city x all-sectors run takes ~1.5 h. "
        "Open the **Live Progress** tab to follow it. Keep this server container running."
    )

# ── Last result ─────────────────────────────────────────────────────────────────
res = st.session_state.batch_result
if res is not None:
    if res["status"] == "success":
        rep = res["result"]
        st.success(
            f"Batch done — city **{rep.city}**, {len(rep.sectors)} sector(s), "
            f"{rep.phase_a_kbos:,} KBOs, {rep.companies_in_view:,} companies in view, "
            f"{rep.placeholders_resolved:,} placeholders resolved, "
            f"in {rep.duration_s:.0f}s"
        )
        if rep.export_files:
            st.caption(f"Exported {len(rep.export_files)} CSV file(s).")
        if rep.sources_failed:
            st.warning(f"Failed sources: {list(rep.sources_failed.keys())}")
    else:
        st.error(f"Batch failed: {res['error']}")

# Auto-refresh while running so the finished result is picked up promptly.
if st.session_state.batch_running:
    time.sleep(3)
    st.rerun()
