"""KBO Data Management — stage, monitor, clean up, and diff KBO Open Data snapshots."""

from __future__ import annotations

import asyncio
import csv
import io
import json
import os
import queue as _queue
import threading
import time
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

import streamlit as st

st.set_page_config(
    page_title="KBO Data Management — be-leads",
    layout="wide",
    page_icon="🗄️",
)

from scraper.ui.theme import inject_theme  # noqa: E402

inject_theme()

# ── DB helpers ─────────────────────────────────────────────────────────────────


def _get_dsn() -> str | None:
    return os.environ.get("DATABASE_URL")


async def _make_pool(dsn: str) -> Any:
    import asyncpg

    async def _init(conn: Any) -> None:
        await conn.set_type_codec(
            "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
        )

    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3, init=_init)
    if pool is None:
        raise RuntimeError("asyncpg.create_pool returned None")
    return pool


def _run_db(dsn: str, coro_factory: Any) -> Any:
    """Create a pool, run coro_factory(pool), close the pool. Returns the result."""

    async def _inner() -> Any:
        pool = await _make_pool(dsn)
        try:
            return await coro_factory(pool)
        finally:
            await pool.close()

    return asyncio.run(_inner())


def _stringify(v: Any) -> str:
    """Convert asyncpg row values to CSV-safe strings."""
    if v is None:
        return ""
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return str(v)


def _rows_to_csv(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    keys = list(rows[0].keys())
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=keys)
    w.writeheader()
    for row in rows:
        w.writerow({k: _stringify(v) for k, v in row.items()})
    return buf.getvalue()


# ── Staging background thread ──────────────────────────────────────────────────


def _bg_stage_zip(zip_path: Path, dsn: str, force: bool, q: _queue.Queue) -> None:  # type: ignore[type-arg]
    """Runs in a daemon thread; puts result dict into q when done."""
    from scraper.sources.kbo_dump.staging import stage_zip

    async def _inner() -> Any:
        import asyncpg

        async def _init(conn: Any) -> None:
            await conn.set_type_codec(
                "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
            )

        pool = await asyncpg.create_pool(dsn, min_size=2, max_size=5, init=_init)
        if pool is None:
            raise RuntimeError("asyncpg.create_pool returned None")
        try:
            return await stage_zip(zip_path, pool, force=force)
        finally:
            await pool.close()

    try:
        report = asyncio.run(_inner())
        q.put({"status": "success", "report": report})
    except Exception as exc:
        q.put({"status": "error", "error": str(exc)})


# ── Session-state defaults ─────────────────────────────────────────────────────

_SS_DEFAULTS: dict[str, Any] = {
    "stage_running": False,
    "stage_queue": None,
    "stage_result": None,
    "stage_zip_label": "",
}
for _k, _v in _SS_DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

# Poll the staging thread queue BEFORE rendering any UI so the completed result
# is picked up on the very first rerun after the thread finishes.
if st.session_state.stage_running:
    _q: _queue.Queue[dict[str, object]] = st.session_state.stage_queue
    if _q is not None:
        try:
            _res = _q.get_nowait()
            st.session_state.stage_running = False
            st.session_state.stage_result = _res
            st.session_state.stage_queue = None
        except _queue.Empty:
            pass

# ── Page layout ────────────────────────────────────────────────────────────────

st.title("KBO Data Management")

dsn = _get_dsn()
if not dsn:
    st.error(
        "**DATABASE_URL** is not set. "
        "Export it in your shell before launching Streamlit:  \n"
        "`export DATABASE_URL=postgresql://...`"
    )
    st.stop()

if st.session_state.stage_running:
    st.warning(
        f"Staging **{st.session_state.stage_zip_label}** in progress… "
        "This takes ~10-15 min for a full KBO ZIP. "
        "Check the **Live Progress** tab for real-time updates."
    )

tab_zips, tab_staged, tab_progress, tab_cleanup, tab_newleads = st.tabs(
    ["Available ZIPs", "Staged Snapshots", "Live Progress", "Cleanup", "New Leads"]
)

# ── Tab 1 — Available ZIPs ─────────────────────────────────────────────────────

with tab_zips:
    from scraper.ui.components.pickers import find_kbo_zips

    st.subheader("Available KBO Open Data ZIPs")
    zips = find_kbo_zips()

    if not zips:
        st.info(
            "No KBO ZIPs found in `KBO_zip/`. "
            "Download a monthly full dump from the "
            "[KBO Open Data portal](https://kbopub.economie.fgov.be/kbo-open-data/) "
            "and save it to the `KBO_zip/` folder."
        )
    else:
        # Build display table
        table_rows = []
        for zip_path, label in zips:
            stat = zip_path.stat()
            size_mb = stat.st_size / (1024 * 1024)
            mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
            table_rows.append({"ZIP": label, "Size (MB)": f"{size_mb:,.1f}", "Modified": mtime})
        st.dataframe(table_rows, use_container_width=True, hide_index=True)

        st.markdown("---")
        st.markdown("**Stage a ZIP into the database**")
        st.caption(
            "Staging reads the ZIP once and writes all 5 CSV files into `kbo_stage_*` tables. "
            "Run this once per monthly KBO release."
        )

        zip_labels = [lbl for _, lbl in zips]
        selected_zip_label = st.selectbox("Select ZIP", zip_labels, key="stage_zip_select")
        selected_zip_path = next(p for p, lbl in zips if lbl == selected_zip_label)
        force_stage = st.checkbox(
            "Force re-stage (delete + overwrite existing data for this snapshot_date)",
            key="force_stage_cb",
        )

        stage_btn = st.button(
            "Stage this ZIP",
            type="primary",
            key="do_stage_btn",
            disabled=st.session_state.stage_running,
        )

        if stage_btn:
            q: _queue.Queue = _queue.Queue()  # type: ignore[type-arg]
            st.session_state.stage_queue = q
            st.session_state.stage_running = True
            st.session_state.stage_result = None
            st.session_state.stage_zip_label = selected_zip_label
            threading.Thread(
                target=_bg_stage_zip,
                args=(selected_zip_path, dsn, force_stage, q),
                daemon=True,
            ).start()
            st.rerun()

    # Show result of the last completed staging operation
    if st.session_state.stage_result is not None:
        res = st.session_state.stage_result
        if res["status"] == "success":
            rep = res["report"]
            if rep.skipped:
                st.warning(
                    f"ZIP already staged for snapshot **{rep.snapshot_date}**. "
                    "Enable **Force re-stage** to overwrite."
                )
            else:
                st.success(
                    f"Staged snapshot **{rep.snapshot_date}** — "
                    f"{rep.rows_enterprise:,} enterprises / "
                    f"{rep.rows_address:,} addresses / "
                    f"{rep.rows_denomination:,} names / "
                    f"{rep.rows_contact:,} contacts / "
                    f"{rep.rows_activity:,} activities — "
                    f"in {rep.duration_s:.0f}s"
                )
        else:
            st.error(f"Staging failed: {res['error']}")
        st.session_state.stage_result = None


# ── Tab 2 — Staged Snapshots ──────────────────────────────────────────────────

with tab_staged:
    st.subheader("Staged Snapshots")
    st.caption("Each row is one monthly KBO snapshot loaded into `kbo_stage_*` tables.")

    try:
        from scraper.ui.queries.snapshots import list_staged_snapshots

        snapshots: list[dict[str, Any]] = _run_db(dsn, lambda p: list_staged_snapshots(p))
    except Exception as exc:
        st.error(f"Failed to query staged snapshots: {exc}")
        snapshots = []

    if not snapshots:
        st.info("No staged snapshots found. Use the **Available ZIPs** tab to stage one.")
    else:
        snap_table = [
            {
                "Snapshot date": s["snapshot_date"].isoformat()
                if hasattr(s["snapshot_date"], "isoformat")
                else str(s["snapshot_date"]),
                "Enterprises": f"{s['enterprise_count']:,}",
            }
            for s in snapshots
        ]
        st.dataframe(snap_table, use_container_width=True, hide_index=True)

        st.markdown("---")
        st.markdown("**Force re-stage a specific snapshot**")
        snap_dates = [
            s["snapshot_date"]
            if isinstance(s["snapshot_date"], date)
            else date.fromisoformat(str(s["snapshot_date"]))
            for s in snapshots
        ]
        snap_labels = [str(d) for d in snap_dates]
        sel_snap_label = st.selectbox("Snapshot to re-stage", snap_labels, key="restage_select")
        sel_snap_date = snap_dates[snap_labels.index(sel_snap_label)]

        # Find the corresponding ZIP for this snapshot date
        matching_zips = [
            (p, lbl)
            for p, lbl in find_kbo_zips()
            if sel_snap_label.replace("-", "_") in lbl or sel_snap_label in lbl
        ]
        if not matching_zips:
            st.caption("No matching ZIP found for this date — stage from the Available ZIPs tab.")
        else:
            if st.button(
                "Force re-stage this snapshot",
                key="restage_btn",
                disabled=st.session_state.stage_running,
            ):
                rezip_path, rezip_lbl = matching_zips[0]
                q2: _queue.Queue = _queue.Queue()  # type: ignore[type-arg]
                st.session_state.stage_queue = q2
                st.session_state.stage_running = True
                st.session_state.stage_result = None
                st.session_state.stage_zip_label = rezip_lbl
                threading.Thread(
                    target=_bg_stage_zip,
                    args=(rezip_path, dsn, True, q2),
                    daemon=True,
                ).start()
                st.rerun()


# ── Tab 3 — Live Progress ─────────────────────────────────────────────────────

with tab_progress:
    st.subheader("Live Pipeline Progress")
    st.caption(
        "Updated by any running `be-leads-pipeline-batch` or `be-leads-kbo-stage` process. "
        "Shows activity within the last 30 minutes."
    )

    col_refresh, col_auto = st.columns([1, 3])
    with col_refresh:
        refresh_btn = st.button("Refresh", key="refresh_progress")
    with col_auto:
        auto_refresh = st.checkbox("Auto-refresh every 3 s", key="auto_refresh_progress")

    try:
        from scraper.ui.queries.snapshots import get_latest_progress

        prog = _run_db(dsn, lambda p: get_latest_progress(p))
    except Exception as exc:
        st.error(f"Cannot read progress: {exc}")
        prog = None

    if prog is None:
        st.info("No active pipeline run in the last 30 minutes.")
    else:
        phase = prog.get("phase", "")
        stage = prog.get("stage", "")
        message = prog.get("message") or ""
        current_val = prog.get("current_val")
        total_val = prog.get("total_val")
        updated_at = prog.get("updated_at")
        started_at = prog.get("started_at")
        source = prog.get("source", "")

        col_a, col_b, col_c = st.columns(3)
        with col_a:
            st.metric("Phase", phase or "—")
        with col_b:
            st.metric("Stage", stage or "—")
        with col_c:
            if updated_at is not None:
                now_utc = datetime.now(tz=UTC)
                if hasattr(updated_at, "tzinfo") and updated_at.tzinfo is not None:
                    elapsed = (now_utc - updated_at).total_seconds()
                else:
                    elapsed = (now_utc - updated_at.replace(tzinfo=UTC)).total_seconds()
                st.metric("Last update", f"{int(elapsed)}s ago")

        if message:
            st.markdown(f"_{message}_")

        if current_val is not None and total_val and total_val > 0:
            pct = min(current_val / total_val, 1.0)
            st.progress(pct, text=f"{current_val:,} / {total_val:,}")

        if started_at is not None:
            started_str = (
                started_at.strftime("%Y-%m-%d %H:%M:%S")
                if hasattr(started_at, "strftime")
                else str(started_at)
            )
            st.caption(f"Run started: {started_str}  ·  Source: {source}")

    if auto_refresh:
        time.sleep(3)
        st.rerun()


# ── Tab 4 — Cleanup ───────────────────────────────────────────────────────────

with tab_cleanup:
    st.subheader("Cleanup Old Snapshots")
    st.caption(
        "Deletes staging rows for all but the N most-recent snapshot dates. "
        "Three snapshots ≈ 6-12 GB Postgres footprint."
    )

    keep_n = st.number_input(
        "Keep last N snapshots",
        min_value=1,
        max_value=12,
        value=3,
        step=1,
        key="cleanup_keep_n",
    )

    if st.button("Run cleanup", key="cleanup_btn"):
        with st.spinner("Deleting old snapshots…"):
            try:
                from scraper.sources.kbo_dump.staging import cleanup_old_snapshots

                deleted: dict[str, int] = _run_db(
                    dsn,
                    lambda p: cleanup_old_snapshots(p, keep_n=int(keep_n)),
                )
                total = sum(deleted.values())
                if total == 0:
                    st.info(f"Nothing to delete — fewer than {keep_n} snapshots present.")
                else:
                    st.success(f"Deleted {total:,} rows across {len(deleted)} tables.")
                    detail_rows = [
                        {"Table": tbl, "Rows deleted": f"{cnt:,}"} for tbl, cnt in deleted.items()
                    ]
                    st.dataframe(detail_rows, use_container_width=True, hide_index=True)
            except Exception as exc:
                st.error(f"Cleanup failed: {exc}")


# ── Tab 5 — New Leads ─────────────────────────────────────────────────────────

with tab_newleads:
    st.subheader("New Leads — KBO Diff View")
    st.caption(
        "Identify companies that appear in a newer KBO snapshot but not in an older one. "
        "These are newly-registered or newly-visible businesses."
    )

    try:
        from scraper.ui.queries.snapshots import list_staged_snapshots as _list_snaps

        _snaps: list[dict[str, Any]] = _run_db(dsn, lambda p: _list_snaps(p))
    except Exception as exc:
        st.error(f"Cannot load staged snapshots: {exc}")
        _snaps = []

    if len(_snaps) < 1:
        st.info("Stage at least one KBO snapshot to use the diff view.")
    else:
        _snap_dates = [
            s["snapshot_date"]
            if isinstance(s["snapshot_date"], date)
            else date.fromisoformat(str(s["snapshot_date"]))
            for s in _snaps
        ]
        _snap_labels = [str(d) for d in _snap_dates]

        diff_mode = st.radio(
            "Diff mode",
            ["Since date", "Between two snapshots"],
            horizontal=True,
            key="diff_mode",
        )

        if diff_mode == "Since date":
            since_d = st.date_input(
                "Show companies first seen after",
                value=_snap_dates[-1],  # oldest available
                min_value=_snap_dates[-1],
                max_value=_snap_dates[0],
                key="since_date_input",
            )

            if st.button("Find new leads", key="find_since_btn"):
                with st.spinner("Counting…"):
                    try:
                        from scraper.ui.queries.snapshots import (
                            count_new_kbos_since,
                            fetch_new_kbo_details_since,
                        )

                        cnt: int = _run_db(
                            dsn,
                            lambda p: count_new_kbos_since(p, since_d),
                        )
                        st.session_state["diff_count"] = cnt
                        st.session_state["diff_mode_stored"] = "since"
                        st.session_state["diff_since"] = since_d
                        st.session_state["diff_rows"] = None
                    except Exception as exc:
                        st.error(f"Count failed: {exc}")
                        st.session_state["diff_count"] = None

            if (
                st.session_state.get("diff_count") is not None
                and st.session_state.get("diff_mode_stored") == "since"
            ):
                cnt_val = st.session_state["diff_count"]
                st.metric("New companies found", f"{cnt_val:,}")

                if cnt_val > 0:
                    show_n = st.slider(
                        "Show top N (by prospect score)",
                        min_value=50,
                        max_value=1000,
                        value=200,
                        step=50,
                        key="since_show_n",
                    )
                    if st.button("Load details", key="load_since_btn"):
                        with st.spinner(f"Fetching top {show_n} leads…"):
                            try:
                                from scraper.ui.queries.snapshots import fetch_new_kbo_details_since

                                rows_data: list[dict[str, Any]] = _run_db(
                                    dsn,
                                    lambda p: fetch_new_kbo_details_since(
                                        p, st.session_state["diff_since"], limit=show_n
                                    ),
                                )
                                st.session_state["diff_rows"] = rows_data
                            except Exception as exc:
                                st.error(f"Detail fetch failed: {exc}")

        else:  # Between two snapshots
            if len(_snaps) < 2:
                st.info("Need at least 2 staged snapshots for a between-snapshots diff.")
            else:
                col_prior, col_latest = st.columns(2)
                with col_prior:
                    prior_label = st.selectbox(
                        "Prior (older) snapshot",
                        _snap_labels,
                        index=len(_snap_labels) - 1,
                        key="prior_snap",
                    )
                with col_latest:
                    latest_label = st.selectbox(
                        "Latest (newer) snapshot",
                        _snap_labels,
                        index=0,
                        key="latest_snap",
                    )

                prior_d = _snap_dates[_snap_labels.index(prior_label)]
                latest_d = _snap_dates[_snap_labels.index(latest_label)]

                if prior_d >= latest_d:
                    st.warning("Prior snapshot must be older than the latest snapshot.")
                elif st.button("Find new leads", key="find_between_btn"):
                    with st.spinner("Counting…"):
                        try:
                            from scraper.ui.queries.snapshots import count_new_kbos_between

                            cnt2: int = _run_db(
                                dsn,
                                lambda p: count_new_kbos_between(p, prior_d, latest_d),
                            )
                            st.session_state["diff_count"] = cnt2
                            st.session_state["diff_mode_stored"] = "between"
                            st.session_state["diff_prior"] = prior_d
                            st.session_state["diff_latest"] = latest_d
                            st.session_state["diff_rows"] = None
                        except Exception as exc:
                            st.error(f"Count failed: {exc}")
                            st.session_state["diff_count"] = None

                if (
                    st.session_state.get("diff_count") is not None
                    and st.session_state.get("diff_mode_stored") == "between"
                ):
                    cnt_val2 = st.session_state["diff_count"]
                    st.metric("New companies found", f"{cnt_val2:,}")

                    if cnt_val2 > 0:
                        show_n2 = st.slider(
                            "Show top N (by prospect score)",
                            min_value=50,
                            max_value=1000,
                            value=200,
                            step=50,
                            key="between_show_n",
                        )
                        if st.button("Load details", key="load_between_btn"):
                            with st.spinner(f"Fetching top {show_n2} leads…"):
                                try:
                                    from scraper.ui.queries.snapshots import (
                                        fetch_new_kbo_details_between,
                                    )

                                    rows_data2: list[dict[str, Any]] = _run_db(
                                        dsn,
                                        lambda p: fetch_new_kbo_details_between(
                                            p,
                                            st.session_state["diff_prior"],
                                            st.session_state["diff_latest"],
                                            limit=show_n2,
                                        ),
                                    )
                                    st.session_state["diff_rows"] = rows_data2
                                except Exception as exc:
                                    st.error(f"Detail fetch failed: {exc}")

        # Display loaded rows (shared between both modes)
        diff_rows: list[dict[str, Any]] | None = st.session_state.get("diff_rows")
        if diff_rows is not None:
            if not diff_rows:
                st.info(
                    "No enriched details found yet. "
                    "Run the batch pipeline to populate prospect scores."
                )
            else:
                display_rows = [
                    {
                        "KBO": r.get("entity_number", ""),
                        "Name": r.get("name") or "",
                        "City": r.get("city") or "",
                        "ZIP": r.get("zipcode") or "",
                        "NACE": r.get("nace_code") or "",
                        "Start date": _stringify(r.get("start_date")),
                        "Prospect score": f"{float(r.get('overall_prospect') or 0):.3f}",
                        "HV probability": f"{float(r.get('hv_probability') or 0):.3f}",
                    }
                    for r in diff_rows
                ]
                st.dataframe(display_rows, use_container_width=True, hide_index=True)

                csv_bytes = _rows_to_csv(
                    [
                        {
                            "kbo_number": r.get("entity_number", ""),
                            "name": r.get("name") or "",
                            "city": r.get("city") or "",
                            "zipcode": r.get("zipcode") or "",
                            "nace_code": r.get("nace_code") or "",
                            "start_date": _stringify(r.get("start_date")),
                            "overall_prospect": round(float(r.get("overall_prospect") or 0), 4),
                            "hv_probability": round(float(r.get("hv_probability") or 0), 4),
                        }
                        for r in diff_rows
                    ]
                ).encode()
                st.download_button(
                    "Download CSV",
                    data=csv_bytes,
                    file_name="new_leads.csv",
                    mime="text/csv",
                    key="download_new_leads",
                )


# ── Auto-refresh when staging is running ──────────────────────────────────────
# Placed at the very bottom so all UI renders before the 3-second delay.
if st.session_state.stage_running:
    time.sleep(3)
    st.rerun()
