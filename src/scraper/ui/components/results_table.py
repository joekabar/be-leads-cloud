"""Render the lead results table in Streamlit."""

from __future__ import annotations

from typing import Any


def render_company_details(row: dict[str, Any]) -> None:
    """Render a single company's expanded detail block.

    Shows website summary, all function holders, all phones/emails, status,
    founding date, NACE code+description, and per-source observation counts.
    Caller is responsible for placing this inside an st.expander.
    """
    import streamlit as st

    name = row.get("name") or row.get("kbo_number", "")
    st.markdown(f"### {name}")
    kbo = row.get("kbo_number")
    if kbo:
        st.caption(f"KBO {kbo}")

    summary = row.get("website_summary")
    if summary:
        st.markdown("**Website summary**")
        st.write(summary)

    cols = st.columns(2)
    with cols[0]:
        phones_all = row.get("phones_all") or row.get("phone")
        if phones_all:
            st.markdown("**Phones**")
            for p in str(phones_all).split(" | "):
                if p.strip():
                    st.write(p.strip())
        emails_all = row.get("emails_all") or row.get("email")
        if emails_all:
            st.markdown("**Emails**")
            for e in str(emails_all).split(" | "):
                if e.strip():
                    st.write(e.strip())

    with cols[1]:
        st.markdown("**Identity**")
        founding = row.get("founding_date")
        if founding:
            st.write(f"Founded: {founding}")
        status = row.get("status")
        if status:
            st.write(f"Status: {status}")
        nace = row.get("nace_code")
        nace_desc = row.get("nace_description")
        if nace or nace_desc:
            st.write(f"NACE: {nace} — {nace_desc}" if nace_desc else f"NACE: {nace}")

    holders = row.get("function_holders_all") or row.get("function_holders")
    if holders:
        st.markdown("**Function holders / directors**")
        for h in str(holders).split("; "):
            if h.strip():
                st.write(h.strip())

    sources = row.get("sources_count") or {}
    if isinstance(sources, dict) and sources:
        st.markdown("**Sources** (observation counts)")
        st.write(", ".join(f"{k}: {v}" for k, v in sorted(sources.items())))


def render_results_table(
    rows: list[dict[str, Any]],
    *,
    show_score: bool = True,
    show_details_per_row: bool = False,
) -> None:
    """Render a Streamlit dataframe with column config and CSV download button."""
    import pandas as pd
    import streamlit as st

    if not rows:
        st.info("No results found.")
        return

    df = pd.DataFrame(rows)

    col_cfg: dict[str, Any] = {
        "kbo_number": st.column_config.TextColumn("KBO"),
        "name": st.column_config.TextColumn("Name", width="large"),
        "address": st.column_config.TextColumn("Address", width="large"),
        "phone": st.column_config.TextColumn("Phone"),
        "email": st.column_config.TextColumn("Email"),
        "website": st.column_config.LinkColumn("Website"),
        "founding_date": st.column_config.DateColumn("Founded"),
        "status": st.column_config.TextColumn("Status"),
        "nace_code": st.column_config.TextColumn("NACE"),
        "employees": st.column_config.NumberColumn("Employees", format="%d"),
        "revenue_latest": st.column_config.NumberColumn("Revenue (EUR)", format="€%,.0f"),
        "function_holders": st.column_config.TextColumn("Directors"),
    }
    if show_score:
        col_cfg["score_overall"] = st.column_config.ProgressColumn(
            "Score", min_value=0.0, max_value=1.0
        )

    display_cols = list(col_cfg.keys())
    available = [c for c in display_cols if c in df.columns]

    st.dataframe(df[available], column_config=col_cfg, use_container_width=True)

    csv = df.to_csv(index=False)
    st.download_button(
        label="Download CSV",
        data=csv,
        file_name="be_leads_results.csv",
        mime="text/csv",
    )

    if show_details_per_row:
        st.markdown("---")
        st.subheader("Detailed view")
        st.caption(
            f"Showing rich per-company details for {min(len(rows), 50)} of {{}} results.".format(
                len(rows)
            )
        )
        for row in rows[:50]:
            label = row.get("name") or row.get("kbo_number", "(unknown)")
            score = row.get("score_overall", 0.0)
            with st.expander(f"{label} — score {score:.3f}", expanded=False):
                render_company_details(row)
