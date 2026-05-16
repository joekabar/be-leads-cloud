"""Gov.uk-inspired CSS theme for the Belgian B2B Lead Generator UI."""

from __future__ import annotations

# ── Token reference ────────────────────────────────────────────────────────
# Primary:      #1D70B8  (gov.uk blue)
# Primary dark: #003078  (headings, table headers)
# Background:   #F3F2F1  (page — also set in config.toml)
# Surface:      #FFFFFF  (sidebar, cards)
# Border:       #B1B4B6
# Text:         #0B0C0C
# Text muted:   #505A5F
# Score high:   #00703C  (≥ 0.75)
# Score mid:    #F47738  (0.50-0.75)
# Score low:    #D4351C  (< 0.50)
# Flag black:   #000000
# Flag yellow:  #FAD205
# Flag red:     #EF3340

CSS = """
/* ── Belgian flag accent bar ─────────────────────────────────── */
[data-testid="stAppViewContainer"]::before {
    content: "";
    display: block;
    height: 5px;
    background: linear-gradient(
        to right,
        #000000 33.3%,
        #FAD205 33.3% 66.6%,
        #EF3340 66.6%
    );
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    z-index: 9999;
}

/* ── Global typography ───────────────────────────────────────── */
html, body, [data-testid="stAppViewContainer"] {
    font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
}

/* ── Page title ──────────────────────────────────────────────── */
[data-testid="stAppViewContainer"] h1 {
    color: #003078;
    font-size: 1.75rem;
    font-weight: 700;
    border-bottom: 2px solid #1D70B8;
    padding-bottom: 0.4rem;
    margin-bottom: 1rem;
}

/* ── Sidebar ─────────────────────────────────────────────────── */
[data-testid="stSidebar"] {
    background-color: #FFFFFF;
    border-right: 1px solid #B1B4B6;
}
[data-testid="stSidebar"] h2 {
    color: #003078;
    font-size: 1rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 0.75rem;
}
[data-testid="stSidebar"] h3 {
    color: #003078;
    font-size: 0.875rem;
    font-weight: 600;
    border-left: 4px solid #1D70B8;
    padding-left: 0.5rem;
    margin: 0.75rem 0 0.5rem;
}

/* ── Run pipeline button — square, gov.uk blue ───────────────── */
[data-testid="stBaseButton-primary"] {
    background-color: #1D70B8 !important;
    border-color: #1D70B8 !important;
    border-radius: 0 !important;
    font-weight: 600 !important;
    letter-spacing: 0.02em;
}
[data-testid="stBaseButton-primary"]:hover {
    background-color: #003078 !important;
    border-color: #003078 !important;
}

/* ── Secondary buttons (Download CSV, expander toggles) ──────── */
[data-testid="stBaseButton-secondary"] {
    border-radius: 0 !important;
    border-color: #B1B4B6 !important;
    color: #0B0C0C !important;
}

/* ── Score progress bars ─────────────────────────────────────── */
[data-testid="stDataFrame"] progress {
    accent-color: #1D70B8;
}

/* ── Score colour tokens (used by Approach C per-row colouring) ─ */
/* high: #00703C  mid: #F47738  low: #D4351C */

/* ── Section headings in main area ───────────────────────────── */
[data-testid="stAppViewContainer"] h2,
[data-testid="stAppViewContainer"] h3 {
    color: #003078;
}

/* ── Info / warning / error boxes ───────────────────────────── */
[data-testid="stAlert"] {
    border-radius: 0;
    border-left-width: 4px;
}

/* ── Expander headers ────────────────────────────────────────── */
[data-testid="stExpander"] summary {
    font-weight: 600;
    color: #003078;
}

/* ── Footer caption ──────────────────────────────────────────── */
[data-testid="stCaptionContainer"] {
    color: #505A5F;
    font-size: 0.75rem;
}
"""


def inject_theme() -> None:
    """Inject the gov.uk CSS theme into the Streamlit page."""
    import streamlit as st

    st.markdown(f"<style>{CSS}</style>", unsafe_allow_html=True)
