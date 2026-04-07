# app.py — OFA Dashboard entry point
#
# Run with: streamlit run app.py
# This is SEPARATE from main.py — run either independently.
# main.py = data collection + detection (no UI)
# app.py  = dashboard (reads local DB, no data collection)

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st
from ui.components import inject_global_css

st.set_page_config(
    page_title="OFA — Options Flow Analyzer",
    page_icon="🔥",
    layout="wide",
    initial_sidebar_state="expanded",
)

inject_global_css()

# ── Sidebar ────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("""
    <div style="padding: 8px 0 24px 0;">
        <div style="font-family:'IBM Plex Mono',monospace; font-size:18px;
                    font-weight:600; color:#F59E0B; letter-spacing:-0.02em;">
            OFA
        </div>
        <div style="font-family:'IBM Plex Mono',monospace; font-size:10px;
                    color:#4B5268; letter-spacing:0.12em; text-transform:uppercase;
                    margin-top:2px;">
            Options Flow Analyzer
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("""
    <div style="font-family:'IBM Plex Mono',monospace; font-size:10px;
                letter-spacing:0.1em; text-transform:uppercase;
                color:#4B5268; margin-bottom:8px;">
        Navigation
    </div>
    """, unsafe_allow_html=True)

    st.page_link("pages/1_live_flow.py",  label="Live Flow",  icon="⚡")
    st.page_link("pages/2_signals.py",    label="Signals",    icon="🎯")
    st.page_link("pages/3_analytics.py",  label="Analytics",  icon="📊")

    st.markdown("<div style='margin-top:32px;'></div>", unsafe_allow_html=True)
    st.markdown("""
    <div style="font-family:'IBM Plex Mono',monospace; font-size:10px;
                letter-spacing:0.1em; text-transform:uppercase;
                color:#4B5268; margin-bottom:8px;">
        System
    </div>
    """, unsafe_allow_html=True)

    from ui.queries import get_db_stats, get_latest_timestamp
    stats = get_db_stats()
    last_ts = get_latest_timestamp()

    st.markdown(f"""
    <div style="font-family:'IBM Plex Mono',monospace; font-size:11px;
                color:#8B92A8; line-height:1.8;">
        <div>Rows: <span style="color:#E8EAF0">{stats.get('total_rows', 0):,}</span></div>
        <div>Days: <span style="color:#E8EAF0">{stats.get('trading_days', 0)}</span></div>
        <div style="margin-top:8px; font-size:10px; color:#4B5268;">
            Last update<br>
            <span style="color:#6B7280">{last_ts[:16] if last_ts else 'No data'} UTC</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("<div style='margin-top:24px;'></div>", unsafe_allow_html=True)
    st.markdown("""
    <div style="font-family:'IBM Plex Mono',monospace; font-size:9px;
                color:#2E3547; text-align:center; padding-top:16px;
                border-top:1px solid #1E2330;">
        FOR EDUCATIONAL PURPOSES ONLY<br>NOT FINANCIAL ADVICE
    </div>
    """, unsafe_allow_html=True)

# ── Home ───────────────────────────────────────────────────────────────────────

st.markdown("""
<div style="text-align:center; padding:80px 0 40px 0;">
    <div style="font-family:'IBM Plex Mono',monospace; font-size:48px;
                font-weight:600; color:#F59E0B; letter-spacing:-0.03em;">
        OFA
    </div>
    <div style="font-family:'IBM Plex Mono',monospace; font-size:12px;
                color:#4B5268; letter-spacing:0.2em; text-transform:uppercase;
                margin-top:8px;">
        Options Flow Analyzer · NSE NIFTY
    </div>
    <div style="font-family:'IBM Plex Sans',sans-serif; font-size:14px;
                color:#6B7280; margin-top:24px; max-width:480px; margin-left:auto;
                margin-right:auto; line-height:1.6;">
        Institutional options flow monitor. Detects unusual OI buildup,
        volume spikes, and IV anomalies in real time.
    </div>
</div>
""", unsafe_allow_html=True)

col1, col2, col3 = st.columns(3)
with col1:
    st.page_link("pages/1_live_flow.py", label="⚡  Live Flow — Options chain + metrics", use_container_width=True)
with col2:
    st.page_link("pages/2_signals.py",   label="🎯  Signals — Detected anomalies + AI thesis", use_container_width=True)
with col3:
    st.page_link("pages/3_analytics.py", label="📊  Analytics — OI charts + IV skew", use_container_width=True)