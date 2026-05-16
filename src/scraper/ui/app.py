"""Belgian B2B Lead Generator — Streamlit UI."""

from __future__ import annotations

import asyncio
import json
import os

import streamlit as st

from scraper.ui.theme import inject_theme

st.set_page_config(page_title="Belgian B2B Lead Generator", layout="wide")
inject_theme()


def main() -> None:
    st.title("Belgian B2B Lead Generator")

    # ── Sidebar ───────────────────────────────────────────────────────────
    with st.sidebar:
        st.header("Search settings")

        from scraper.ui.components.pickers import (
            find_kbo_zips,
            load_city_options,
            load_sector_options,
        )

        sector_options = load_sector_options()
        sector_slugs = [slug for slug, _ in sector_options]

        selected_sector_slugs = st.multiselect(
            "Sector(s)",
            options=sector_slugs,
            default=[sector_slugs[0]] if sector_slugs else [],
            format_func=lambda s: next((lbl for slg, lbl in sector_options if slg == s), s),
        )

        city_options = load_city_options()
        city_labels = [display for _, display, _ in city_options]
        city_slugs = [slug for slug, _, _ in city_options]
        city_postcodes_by_idx = [postcodes for _, _, postcodes in city_options]
        city_idx = st.selectbox(
            "City",
            range(len(city_labels)),
            format_func=lambda i: city_labels[i],
        )
        city = city_labels[city_idx]
        city_slug = city_slugs[city_idx]
        available_postcodes = city_postcodes_by_idx[city_idx]
        selected_postcodes = st.multiselect(
            "Postcodes",
            options=available_postcodes,
            default=available_postcodes,
            help="Restrict results to these postal codes within the city",
        )

        lang = st.radio("Language", ["NL", "FR"], horizontal=True)
        max_pages = st.slider("Pages to scan", 1, 25, 5)

        st.markdown("---")
        st.subheader("KBO Open Data dump")
        zip_options = find_kbo_zips()
        selected_zip_path = None
        if zip_options:
            zip_labels = [label for _, label in zip_options]
            zip_idx = st.selectbox(
                "Select monthly dump",
                range(len(zip_labels)),
                format_func=lambda i: zip_labels[i],
            )
            selected_zip_path = zip_options[zip_idx][0]
        else:
            st.warning(
                "No KBO ZIPs found in `KBO_zip/`. "
                "Place a `KboOpenData_NNNN_YYYY_MM_DD_Full.zip` there to enable "
                "real-KBO enrichment (kbopub, NBB). Without it only goudengids "
                "placeholders will be returned."
            )

        st.markdown("---")
        with st.expander("Sources", expanded=False):
            do_kbo = st.checkbox(
                "KBO Open Data",
                value=selected_zip_path is not None,
                disabled=selected_zip_path is None,
            )
            do_goud = st.checkbox("Goudengids / Pagesdor", value=True)
            do_kbopub = st.checkbox("kbopub function holders", value=True)
            do_nbb = st.checkbox("NBB financials", value=True)
            do_web = st.checkbox("Company websites", value=True)
            do_search = st.checkbox("Search cross-validation", value=True)

        st.markdown("---")
        with st.expander("Filters", expanded=False):
            min_score = st.slider("Min lead score", 0.0, 1.0, 0.0, 0.05)
            require_phone = st.checkbox("Must have phone", value=False)
            require_website = st.checkbox("Must have website", value=False)
            require_email = st.checkbox("Must have email", value=False)
            active_only = st.checkbox(
                "Active companies only",
                value=True,
                help=(
                    "Rows with unknown status pass through; filter applies "
                    "only when status is recorded."
                ),
            )
            founded_range_enabled = st.checkbox("Filter by founding year", value=False)
            if founded_range_enabled:
                founded_after_year = st.number_input(
                    "Founded after", min_value=1900, max_value=2100, value=1980, step=1
                )
                founded_before_year = st.number_input(
                    "Founded before",
                    min_value=1900,
                    max_value=2100,
                    value=2100,
                    step=1,
                )
                founded_after = f"{int(founded_after_year):04d}-01-01"
                founded_before = f"{int(founded_before_year):04d}-12-31"
            else:
                founded_after = None
                founded_before = None
            st.markdown("**Financials** (requires NBB data)")
            min_revenue_val = st.number_input(
                "Min revenue (EUR)", min_value=0, value=0, step=10_000
            )
            min_employees_val = st.number_input("Min employees", min_value=0, value=0, step=1)
            min_revenue = float(min_revenue_val) if min_revenue_val > 0 else None
            min_employees = float(min_employees_val) if min_employees_val > 0 else None
            st.markdown("**Company size** (from KBO legal form)")
            _size_all = ["Solo", "SME", "Large"]
            selected_sizes = st.multiselect(
                "Size categories",
                options=_size_all,
                default=_size_all,
                help=(
                    "Solo = eenmanszaak / natural person; "
                    "Large = NV or SE; SME = all other legal forms. "
                    "Companies with no size data always pass through."
                ),
            )
            size_categories = selected_sizes if len(selected_sizes) < len(_size_all) else None

        run_btn = st.button(
            "Run pipeline",
            type="primary",
            use_container_width=True,
            disabled=not selected_sector_slugs,
        )

    # ── Main area ─────────────────────────────────────────────────────────
    if "last_report" not in st.session_state:
        st.session_state["last_report"] = None
        st.session_state["last_rows"] = []
        st.session_state["last_log"] = ""

    if not run_btn and st.session_state["last_report"] is None:
        st.markdown(
            '<p style="color:#505A5F;font-size:0.9rem;margin-top:1rem;">'
            "Configure your search in the sidebar and click <strong>Run pipeline</strong>."
            "</p>",
            unsafe_allow_html=True,
        )

    if run_btn and selected_sector_slugs:
        from scraper.pipeline.orchestrator import PipelineConfig, resolve_sector_slugs

        db_url = os.environ.get("DATABASE_URL", "")
        all_rows: list[dict[str, object]] = []
        last_report: object = None
        log_parts: list[str] = []

        for sector_slug in selected_sector_slugs:
            sector_label = next(
                (lbl for slg, lbl in sector_options if slg == sector_slug), sector_slug
            )
            try:
                nl_slug, _ = resolve_sector_slugs(sector_slug)
            except ValueError:
                nl_slug = sector_slug

            config = PipelineConfig(
                sector=sector_slug,
                city=city_slug,
                sector_slug=nl_slug,
                max_pages=max_pages,
                lang="nl" if lang == "NL" else "fr",
                use_fixture=False,
                fixture_zip_path=selected_zip_path,
                postcodes=tuple(selected_postcodes),
                do_kbo_dump=do_kbo and selected_zip_path is not None,
                do_goudengids=do_goud,
                do_kbopub=do_kbopub,
                do_nbb=do_nbb,
                do_website=do_web,
                do_search=do_search,
                nbb_subscription_key=os.environ.get("NBB_CBSO_API_KEY"),
                brave_subscription_key=os.environ.get("BRAVE_SEARCH_API_KEY"),
            )

            try:
                from scraper.pipeline.run import run

                with st.spinner(f"Running pipeline for {sector_label}…"):
                    report = asyncio.run(run(config))

                last_report = report
                log_parts.append(
                    json.dumps(
                        {
                            "sector": sector_slug,
                            "sources_run": report.sources_run,
                            "sources_failed": report.sources_failed,
                            "companies_in_view": report.companies_in_view,
                            "duration_s": round(report.duration_s, 2),
                        },
                        indent=2,
                    )
                )

                if db_url:
                    from scraper.db.pool import init_pool
                    from scraper.pipeline.orchestrator import PipelineReport
                    from scraper.ui.data import fetch_results_for_run

                    async def _fetch(
                        _slug: str = sector_slug,
                        _report: PipelineReport = report,
                    ) -> list[dict[str, object]]:
                        p = await init_pool(db_url)
                        try:
                            return await fetch_results_for_run(
                                p,
                                _report.started_at,
                                sector=_slug,
                                city=city,
                                postcodes=tuple(selected_postcodes) or None,
                                min_score=min_score,
                                require_phone=require_phone,
                                require_website=require_website,
                                require_email=require_email,
                                active_only=active_only,
                                founded_after=founded_after,
                                founded_before=founded_before,
                                min_revenue=min_revenue,
                                min_employees=min_employees,
                                size_categories=size_categories,
                            )
                        finally:
                            await p.close()

                    sector_rows = asyncio.run(_fetch())
                    for row in sector_rows:
                        row["sector"] = sector_label
                    all_rows.extend(sector_rows)

            except Exception as exc:
                st.error(f"Pipeline error ({sector_label}): {exc}")

        st.session_state["last_report"] = last_report
        st.session_state["last_rows"] = all_rows
        st.session_state["last_log"] = "\n\n".join(log_parts)

    last_report = st.session_state.get("last_report")
    if last_report is not None:
        from scraper.ui.components.diagnostics import render_diagnostics

        rows = st.session_state.get("last_rows", [])
        render_diagnostics(last_report, rows)

        log_text = st.session_state.get("last_log", "")
        if log_text:
            with st.expander("Pipeline log (raw JSON)", expanded=False):
                st.code(log_text, language="json")

        st.subheader(f"Results — {len(rows)} companies")

        from scraper.ui.components.results_table import render_results_table

        show_details = st.checkbox(
            "Show detailed per-company expanders",
            value=False,
            help=(
                "Renders an expandable card per row with summary, all "
                "phones/emails, all directors, status, NACE, and per-source counts."
            ),
        )
        show_diagnostic = st.checkbox(
            "Show diagnostic per row",
            value=False,
            help=(
                "Adds two columns to the table: 'Missing' (HVF fields with no "
                "data) and 'Sources' (which sources contributed observations)."
            ),
        )
        render_results_table(
            rows,
            show_details_per_row=show_details,
            show_diagnostic_per_row=show_diagnostic,
        )

    # ── Footer ────────────────────────────────────────────────────────────
    st.markdown("---")
    st.caption(
        "Search results powered by Brave Search API · "
        "Company data: KBO Open Data (economie.fgov.be)"
    )


if __name__ == "__main__":
    main()
