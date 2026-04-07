# ui/components.py — Shared Streamlit UI components and helpers

import streamlit as st
import pandas as pd
import numpy as np


# ── Theme constants ────────────────────────────────────────────────────────────

BULLISH_COLOR  = "#F59E0B"   # amber
BEARISH_COLOR  = "#EF4444"   # red
NEUTRAL_COLOR  = "#6B7280"   # gray
ACCENT_COLOR   = "#F59E0B"   # amber
BUILDUP_COLOR  = "#10B981"   # emerald green
UNWIND_COLOR   = "#EF4444"   # red
VOLUME_COLOR   = "#60A5FA"   # blue
IV_COLOR       = "#A78BFA"   # purple


# ── Global CSS ─────────────────────────────────────────────────────────────────

def inject_global_css():
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@300;400;500;600&display=swap');

    /* Root theme */
    :root {
        --bg-primary:    #0D0F14;
        --bg-secondary:  #13161E;
        --bg-card:       #181C26;
        --bg-hover:      #1E2330;
        --border:        #252A38;
        --border-bright: #2E3547;
        --text-primary:  #E8EAF0;
        --text-secondary:#8B92A8;
        --text-muted:    #4B5268;
        --amber:         #F59E0B;
        --amber-dim:     #92620A;
        --green:         #10B981;
        --red:           #EF4444;
        --blue:          #60A5FA;
        --purple:        #A78BFA;
        --font-mono:     'IBM Plex Mono', monospace;
        --font-sans:     'IBM Plex Sans', sans-serif;
    }

    /* Override Streamlit defaults */
    .stApp {
        background-color: var(--bg-primary) !important;
        font-family: var(--font-sans) !important;
    }

    .stSidebar {
        background-color: var(--bg-secondary) !important;
        border-right: 1px solid var(--border) !important;
    }

    /* Remove default padding */
    .block-container {
        padding-top: 1.5rem !important;
        padding-bottom: 2rem !important;
        max-width: 1400px !important;
    }

    /* Headers */
    h1, h2, h3 {
        font-family: var(--font-sans) !important;
        color: var(--text-primary) !important;
        letter-spacing: -0.02em !important;
    }

    /* Metric cards */
    .metric-card {
        background: var(--bg-card);
        border: 1px solid var(--border);
        border-radius: 8px;
        padding: 16px 20px;
        transition: border-color 0.2s;
    }
    .metric-card:hover { border-color: var(--border-bright); }
    .metric-label {
        font-family: var(--font-mono);
        font-size: 10px;
        font-weight: 500;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        color: var(--text-muted);
        margin-bottom: 6px;
    }
    .metric-value {
        font-family: var(--font-mono);
        font-size: 24px;
        font-weight: 600;
        color: var(--text-primary);
        line-height: 1;
    }
    .metric-sub {
        font-family: var(--font-mono);
        font-size: 11px;
        color: var(--text-secondary);
        margin-top: 4px;
    }
    .metric-value.bullish { color: var(--amber); }
    .metric-value.bearish { color: var(--red); }
    .metric-value.green   { color: var(--green); }

    /* Signal badge */
    .signal-badge {
        display: inline-block;
        font-family: var(--font-mono);
        font-size: 10px;
        font-weight: 600;
        letter-spacing: 0.08em;
        padding: 2px 8px;
        border-radius: 3px;
        text-transform: uppercase;
    }
    .badge-buildup  { background: rgba(16,185,129,0.15); color: #10B981; border: 1px solid rgba(16,185,129,0.3); }
    .badge-unwind   { background: rgba(239,68,68,0.15);  color: #EF4444; border: 1px solid rgba(239,68,68,0.3); }
    .badge-volume   { background: rgba(96,165,250,0.15); color: #60A5FA; border: 1px solid rgba(96,165,250,0.3); }
    .badge-iv       { background: rgba(167,139,250,0.15);color: #A78BFA; border: 1px solid rgba(167,139,250,0.3); }
    .badge-bullish  { background: rgba(245,158,11,0.15); color: #F59E0B; border: 1px solid rgba(245,158,11,0.3); }
    .badge-bearish  { background: rgba(239,68,68,0.15);  color: #EF4444; border: 1px solid rgba(239,68,68,0.3); }
    .badge-neutral  { background: rgba(107,114,128,0.15);color: #6B7280; border: 1px solid rgba(107,114,128,0.3); }

    /* Signal card */
    .signal-card {
        background: var(--bg-card);
        border: 1px solid var(--border);
        border-radius: 10px;
        padding: 20px;
        margin-bottom: 12px;
        transition: border-color 0.2s, background 0.2s;
    }
    .signal-card:hover {
        border-color: var(--border-bright);
        background: var(--bg-hover);
    }
    .signal-card.bullish { border-left: 3px solid var(--amber); }
    .signal-card.bearish { border-left: 3px solid var(--red); }
    .signal-card.neutral { border-left: 3px solid var(--text-muted); }

    /* Thesis text */
    .thesis-text {
        font-family: var(--font-sans);
        font-size: 13px;
        line-height: 1.6;
        color: var(--text-secondary);
        margin-top: 10px;
        padding: 12px 14px;
        background: var(--bg-secondary);
        border-radius: 6px;
        border-left: 2px solid var(--border-bright);
    }

    /* Data table overrides */
    .stDataFrame {
        background: var(--bg-card) !important;
    }
    .stDataFrame thead th {
        font-family: var(--font-mono) !important;
        font-size: 10px !important;
        letter-spacing: 0.08em !important;
        text-transform: uppercase !important;
        color: var(--text-muted) !important;
        background: var(--bg-secondary) !important;
    }
    .stDataFrame tbody td {
        font-family: var(--font-mono) !important;
        font-size: 12px !important;
        color: var(--text-primary) !important;
    }

    /* Divider */
    .ofa-divider {
        border: none;
        border-top: 1px solid var(--border);
        margin: 20px 0;
    }

    /* Section header */
    .section-header {
        font-family: var(--font-mono);
        font-size: 10px;
        font-weight: 600;
        letter-spacing: 0.15em;
        text-transform: uppercase;
        color: var(--text-muted);
        margin-bottom: 16px;
        padding-bottom: 8px;
        border-bottom: 1px solid var(--border);
    }

    /* Live indicator */
    .live-dot {
        display: inline-block;
        width: 7px;
        height: 7px;
        background: var(--green);
        border-radius: 50%;
        margin-right: 6px;
        animation: pulse 2s infinite;
    }
    @keyframes pulse {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.3; }
    }

    /* Streamlit selectbox/input theming */
    .stSelectbox > div > div {
        background-color: var(--bg-card) !important;
        border-color: var(--border) !important;
        color: var(--text-primary) !important;
        font-family: var(--font-mono) !important;
    }

    /* Hide streamlit branding */
    #MainMenu, footer, header { visibility: hidden; }
    .stDeployButton { display: none; }

    /* Tabs */
    .stTabs [data-baseweb="tab-list"] {
        background: var(--bg-secondary) !important;
        border-radius: 8px !important;
        padding: 4px !important;
        gap: 4px !important;
    }
    .stTabs [data-baseweb="tab"] {
        font-family: var(--font-mono) !important;
        font-size: 11px !important;
        font-weight: 500 !important;
        letter-spacing: 0.06em !important;
        text-transform: uppercase !important;
        color: var(--text-muted) !important;
        background: transparent !important;
        border-radius: 6px !important;
        padding: 8px 16px !important;
    }
    .stTabs [aria-selected="true"] {
        background: var(--bg-card) !important;
        color: var(--text-primary) !important;
    }
    </style>
    """, unsafe_allow_html=True)


# ── Metric card ────────────────────────────────────────────────────────────────

def metric_card(label: str, value: str, sub: str = "", style: str = ""):
    cls = f"metric-value {style}" if style else "metric-value"
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-label">{label}</div>
        <div class="{cls}">{value}</div>
        {"<div class='metric-sub'>" + sub + "</div>" if sub else ""}
    </div>
    """, unsafe_allow_html=True)


# ── Signal badge ───────────────────────────────────────────────────────────────

def signal_badge(signal_type: str) -> str:
    mapping = {
        "OI_BUILDUP":   ("badge-buildup",  "OI BUILDUP"),
        "OI_UNWIND":    ("badge-unwind",   "OI UNWIND"),
        "VOLUME_SPIKE": ("badge-volume",   "VOL SPIKE"),
        "IV_SPIKE":     ("badge-iv",       "IV SPIKE"),
    }
    cls, label = mapping.get(signal_type, ("badge-neutral", signal_type))
    return f'<span class="signal-badge {cls}">{label}</span>'


def bias_badge(bias: str) -> str:
    mapping = {
        "BULLISH": "badge-bullish",
        "BEARISH": "badge-bearish",
        "NEUTRAL": "badge-neutral",
    }
    cls = mapping.get(bias, "badge-neutral")
    return f'<span class="signal-badge {cls}">{bias}</span>'


# ── Confidence stars ───────────────────────────────────────────────────────────

def confidence_stars(confidence: int | None) -> str:
    if not confidence:
        return '<span style="color:#4B5268">—</span>'
    filled = "★" * int(confidence)
    empty  = "☆" * (5 - int(confidence))
    return f'<span style="color:#F59E0B;font-size:13px">{filled}</span><span style="color:#2E3547;font-size:13px">{empty}</span>'


# ── RSI gauge ─────────────────────────────────────────────────────────────────

def rsi_color(rsi: float | None) -> str:
    if rsi is None:
        return "var(--text-muted)"
    if rsi >= 70:
        return "var(--red)"
    elif rsi >= 60:
        return "var(--amber)"
    elif rsi >= 40:
        return "var(--green)"
    elif rsi >= 30:
        return "var(--amber)"
    else:
        return "var(--red)"


# ── PCR color ─────────────────────────────────────────────────────────────────

def pcr_color(pcr: float | None) -> str:
    if pcr is None:
        return "var(--text-muted)"
    if pcr > 1.3:
        return "var(--red)"
    elif pcr > 1.0:
        return "var(--amber)"
    elif pcr > 0.7:
        return "var(--green)"
    else:
        return "var(--amber)"


# ── Compute RSI from series ────────────────────────────────────────────────────

def compute_rsi(prices: list[float], period: int = 14) -> float | None:
    if len(prices) < period + 1:
        return None
    deltas = np.diff(prices)
    gains  = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 1)


# ── Section header ─────────────────────────────────────────────────────────────

def section_header(title: str):
    st.markdown(f'<div class="section-header">{title}</div>', unsafe_allow_html=True)


# ── Empty state ────────────────────────────────────────────────────────────────

def empty_state(message: str):
    st.markdown(f"""
    <div style="text-align:center; padding:60px 0; color:var(--text-muted);
                font-family:var(--font-mono); font-size:12px; letter-spacing:0.08em;">
        {message}
    </div>
    """, unsafe_allow_html=True)


# ── Format helpers ─────────────────────────────────────────────────────────────

def fmt_oi(val) -> str:
    try:
        if val is None:
            return "—"
        import math
        if isinstance(val, float) and math.isnan(val):
            return "—"
        val = int(val)
        if val == 0:
            return "—"
        if abs(val) >= 1_000_000:
            return f"{val/1_000_000:.2f}M"
        elif abs(val) >= 1_000:
            return f"{val/1_000:.1f}K"
        return str(val)
    except (TypeError, ValueError):
        return "—"


def fmt_price(val) -> str:
    try:
        import math
        if val is None or (isinstance(val, float) and math.isnan(val)):
            return "—"
        return f"₹{float(val):,.2f}"
    except (TypeError, ValueError):
        return "—"


def fmt_pct(val) -> str:
    try:
        import math
        if val is None or (isinstance(val, float) and math.isnan(val)):
            return "—"
        return f"{float(val):.2f}%"
    except (TypeError, ValueError):
        return "—"


def oi_change_color(val) -> str:
    if val is None or val == 0:
        return "var(--text-muted)"
    return "var(--green)" if val > 0 else "var(--red)"