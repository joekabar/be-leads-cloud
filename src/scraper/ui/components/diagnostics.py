"""Pipeline diagnostics panel for the Streamlit UI."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from scraper.pipeline.orchestrator import PipelineReport


_HIGH_VALUE_FIELDS = (
    "phone",
    "website",
    "address",
    "founding_date",
    "function_holders",
    "revenue_latest",
    "email",
)


def compute_coverage_matrix(rows: list[dict[str, Any]]) -> dict[str, float]:
    """Return {field: fraction-of-rows-with-non-empty-value} for HVF fields.

    Empty string and None both count as missing. Numeric 0 counts as present
    (e.g. revenue_latest=0 means we have the value).
    """
    if not rows:
        return dict.fromkeys(_HIGH_VALUE_FIELDS, 0.0)
    total = len(rows)
    counts: dict[str, int] = dict.fromkeys(_HIGH_VALUE_FIELDS, 0)
    for row in rows:
        for f in _HIGH_VALUE_FIELDS:
            v = row.get(f)
            if v is None:
                continue
            if isinstance(v, str) and not v.strip():
                continue
            counts[f] += 1
    return {f: counts[f] / total for f in _HIGH_VALUE_FIELDS}


def render_diagnostics(report: PipelineReport, rows: list[dict[str, Any]]) -> None:
    """Render an expander with per-source status, counts, durations + coverage."""
    import streamlit as st

    with st.expander("Diagnostics", expanded=True):
        cols = st.columns(4)
        cols[0].metric("Companies", report.companies_in_view)
        cols[1].metric("Sources run", len(report.sources_run))
        cols[2].metric("Sources skipped", len(report.sources_skipped))
        cols[3].metric("Sources failed", len(report.sources_failed))

        st.markdown("**Per-source summary**")
        rows_data: list[dict[str, Any]] = []
        all_sources = sorted(
            set(report.sources_run)
            | set(report.sources_skipped)
            | set(report.sources_failed.keys())
            | set(report.duration_per_source.keys())
            | set(report.observations_inserted_per_source.keys())
        )
        for src in all_sources:
            if src in report.sources_failed:
                status = "FAILED"
            elif src in report.sources_run:
                status = "ran"
            elif src in report.sources_skipped:
                status = "skipped"
            else:
                status = "?"
            rows_data.append(
                {
                    "source": src,
                    "status": status,
                    "observations": report.observations_inserted_per_source.get(src, 0),
                    "duration_s": round(report.duration_per_source.get(src, 0.0), 2),
                    "error": report.sources_failed.get(src, ""),
                }
            )
        if rows_data:
            import pandas as pd

            st.dataframe(pd.DataFrame(rows_data), use_container_width=True, hide_index=True)

        cols2 = st.columns(2)
        cols2[0].metric("Placeholders created", report.placeholders_created)
        cols2[1].metric("Placeholders resolved", report.placeholders_resolved)

        st.markdown("**Field coverage** (% of companies in result with each field)")
        coverage = compute_coverage_matrix(rows)
        cov_rows = [{"field": f, "coverage_pct": round(v * 100, 1)} for f, v in coverage.items()]
        import pandas as pd

        st.dataframe(pd.DataFrame(cov_rows), use_container_width=True, hide_index=True)
        st.caption(f"Total pipeline duration: {round(report.duration_s, 2)} s")
