"""Belgian B2B Lead Generator — Streamlit UI."""

from __future__ import annotations

import asyncio
import json

import streamlit as st

st.set_page_config(page_title="Belgian B2B Lead Generator", layout="wide")


def main() -> None:
    st.title("Belgian B2B Lead Generator")

    # ── Sidebar ───────────────────────────────────────────────────────────
    with st.sidebar:
        st.header("Search settings")

        from scraper.ui.components.pickers import load_sector_options

        sector_options = load_sector_options()
        sector_labels = [f"{display}" for _, display in sector_options]
        sector_slugs = [slug for slug, _ in sector_options]

        sector_idx = st.selectbox(
            "Sector",
            range(len(sector_labels)),
            format_func=lambda i: sector_labels[i],
        )
        selected_sector_slug = sector_slugs[sector_idx]

        city = st.text_input("City", value="Antwerpen")
        lang = st.radio("Language", ["NL", "FR"], horizontal=True)
        max_pages = st.slider("Pages to scan", 1, 25, 5)
        use_fixture = st.checkbox("Use fixture (test data)", value=False)

        st.markdown("---")
        st.subheader("Sources")
        do_kbo = st.checkbox("KBO Open Data", value=True)
        do_goud = st.checkbox("Goudengids / Pagesdor", value=True)
        do_kbopub = st.checkbox("kbopub function holders", value=True)
        do_nbb = st.checkbox("NBB financials", value=True)
        do_web = st.checkbox("Company websites", value=True)
        do_search = st.checkbox("Search cross-validation", value=True)

        run_btn = st.button("Run pipeline", type="primary", use_container_width=True)

    # ── Main area ─────────────────────────────────────────────────────────
    if "last_report" not in st.session_state:
        st.session_state["last_report"] = None
        st.session_state["last_rows"] = []
        st.session_state["last_log"] = ""

    if not run_btn and st.session_state["last_report"] is None:
        st.info("Configure your search in the sidebar and click **Run pipeline**.")

    if run_btn:
        from scraper.pipeline.orchestrator import PipelineConfig, resolve_sector_slugs

        try:
            nl_slug, _ = resolve_sector_slugs(selected_sector_slug)
        except ValueError:
            nl_slug = selected_sector_slug

        config = PipelineConfig(
            sector=selected_sector_slug,
            city=city,
            sector_slug=nl_slug,
            max_pages=max_pages,
            lang="nl" if lang == "NL" else "fr",
            use_fixture=use_fixture,
            do_kbo_dump=do_kbo,
            do_goudengids=do_goud,
            do_kbopub=do_kbopub,
            do_nbb=do_nbb,
            do_website=do_web,
            do_search=do_search,
        )

        try:
            import os

            from scraper.db.pool import init_pool
            from scraper.pipeline.run import run

            db_url = os.environ.get("DATABASE_URL", "")

            with st.spinner("Running pipeline…"):
                report = asyncio.run(run(config))

            st.session_state["last_report"] = report
            st.session_state["last_log"] = json.dumps(
                {
                    "sources_run": report.sources_run,
                    "sources_failed": report.sources_failed,
                    "companies_in_view": report.companies_in_view,
                    "duration_s": round(report.duration_s, 2),
                },
                indent=2,
            )

            # Fetch results from DB
            pool = asyncio.run(init_pool(db_url)) if db_url else None
            if pool and report.run_id:
                from scraper.ui.data import fetch_results_for_run

                rows = asyncio.run(
                    fetch_results_for_run(
                        pool,
                        report.run_id,
                        sector=selected_sector_slug,
                        city=city,
                    )
                )
                asyncio.run(pool.close())
                st.session_state["last_rows"] = rows
            else:
                st.session_state["last_rows"] = []

        except Exception as exc:
            st.error(f"Pipeline error: {exc}")

    last_report: object = st.session_state.get("last_report")
    if last_report is not None:
        log_text = st.session_state.get("last_log", "")
        if log_text:
            with st.expander("Pipeline log", expanded=False):
                st.code(log_text, language="json")

        rows = st.session_state.get("last_rows", [])
        st.subheader(f"Results — {len(rows)} companies")

        from scraper.ui.components.results_table import render_results_table

        render_results_table(rows)

    # ── Footer ────────────────────────────────────────────────────────────
    st.markdown("---")
    st.caption(
        "Search results powered by Brave Search API · "
        "Company data: KBO Open Data (economie.fgov.be)"
    )


if __name__ == "__main__":
    main()
