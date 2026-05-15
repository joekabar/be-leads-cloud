"""Render the lead results table in Streamlit."""

from __future__ import annotations

from typing import Any


def render_results_table(
    rows: list[dict[str, Any]],
    *,
    show_score: bool = True,
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
