# pages/2_signals.py — Detected Signals + LLM Thesis

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import pandas as pd
from datetime import date

from ui.components import (
    inject_global_css, section_header, empty_state,
    signal_badge, bias_badge, confidence_stars,
    fmt_oi, fmt_price, fmt_pct, metric_card,
)
from ui.queries import (
    get_today_signals, get_all_signals,
    get_signal_stats, get_news_for_signal,
)

st.set_page_config(page_title="Signals · OFA", layout="wide")
inject_global_css()

# ── Header ─────────────────────────────────────────────────────────────────────
col_h1, col_h2 = st.columns([3, 1])
with col_h1:
    st.markdown("""
    <div style="padding-bottom:8px;">
        <span style="font-family:'IBM Plex Mono',monospace; font-size:22px;
                     font-weight:600; color:#E8EAF0;">
            🎯 Signals
        </span>
        <span style="font-family:'IBM Plex Mono',monospace; font-size:11px;
                     color:#4B5268; margin-left:12px; letter-spacing:0.08em;">
            ANOMALY DETECTION · AI THESIS
        </span>
    </div>
    """, unsafe_allow_html=True)
with col_h2:
    if st.button("↻ Refresh", use_container_width=True):
        st.rerun()

# ── Stats row ──────────────────────────────────────────────────────────────────
stats = get_signal_stats()

m1, m2, m3, m4 = st.columns(4)
with m1:
    metric_card("Today's Signals", str(stats.get("today", 0)))
with m2:
    metric_card("Bullish Today", str(stats.get("bullish_today", 0)), style="bullish")
with m3:
    metric_card("Bearish Today", str(stats.get("bearish_today", 0)), style="bearish")
with m4:
    metric_card("With AI Thesis", str(stats.get("with_thesis", 0)), style="green")

st.markdown("<div style='margin-top:24px;'></div>", unsafe_allow_html=True)

# ── Filters ────────────────────────────────────────────────────────────────────
section_header("Signal Feed")

f1, f2, f3, f4 = st.columns([2, 2, 2, 2])
with f1:
    time_range = st.selectbox("Period", ["Today", "Last 3 days", "Last 7 days"], label_visibility="collapsed")
with f2:
    bias_filter = st.selectbox("Bias", ["All", "BULLISH", "BEARISH", "NEUTRAL"], label_visibility="collapsed")
with f3:
    type_filter = st.selectbox("Type", ["All", "OI_BUILDUP", "OI_UNWIND", "VOLUME_SPIKE", "IV_SPIKE"], label_visibility="collapsed")
with f4:
    thesis_only = st.checkbox("With thesis only", value=False)

# Load data
days_map = {"Today": 1, "Last 3 days": 3, "Last 7 days": 7}
days = days_map[time_range]
signals = get_all_signals(days=days)

# Apply filters
if not signals.empty:
    if bias_filter != "All":
        signals = signals[signals["bias"] == bias_filter]
    if type_filter != "All":
        signals = signals[signals["signal_type"] == type_filter]
    if thesis_only:
        signals = signals[signals["llm_thesis"].notna()]

# ── Signal cards ───────────────────────────────────────────────────────────────
if signals.empty:
    empty_state("NO SIGNALS · Detection runs every 5 minutes during market hours")
else:
    for _, sig in signals.iterrows():
        bias = sig.get("bias", "NEUTRAL") or "NEUTRAL"
        bias_cls = bias.lower()

        # Convert UTC timestamp to IST for display
        ts_raw = sig.get("fired_at", "")
        try:
            from datetime import datetime, timezone, timedelta
            ts_dt = datetime.strptime(ts_raw[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            ts_ist = ts_dt + timedelta(hours=5, minutes=30)
            ts_display = ts_ist.strftime("%d %b %Y · %H:%M IST")
        except:
            ts_display = ts_raw[:16]

        # Build thesis HTML
        thesis = sig.get("llm_thesis")
        llm_bias = sig.get("llm_bias")
        llm_conf = sig.get("llm_confidence")

        if thesis:
            thesis_html = (
                '<div style="margin-top:12px;">'
                '<div style="display:flex;align-items:center;gap:10px;margin-bottom:6px;">'
                '<span style="font-family:IBM Plex Mono,monospace;font-size:9px;'
                'letter-spacing:0.12em;text-transform:uppercase;color:#4B5268;">AI Thesis</span>'
                + (bias_badge(llm_bias) if llm_bias else '')
                + '<span style="font-size:13px;">' + confidence_stars(llm_conf) + '</span>'
                '</div>'
                '<div style="font-family:IBM Plex Sans,sans-serif;font-size:13px;line-height:1.6;'
                'color:#8B92A8;margin-top:4px;padding:12px 14px;background:#13161E;'
                'border-radius:6px;border-left:2px solid #2E3547;">'
                + str(thesis)
                + '</div></div>'
            )
        else:
            thesis_html = (
                '<div style="margin-top:8px;font-family:IBM Plex Mono,monospace;'
                'font-size:10px;color:#4B5268;font-style:italic;">thesis pending...</div>'
            )

        # Render entire card in ONE st.markdown call — Streamlit strips unclosed divs between calls
        st.markdown(f"""
        <div class="signal-card {bias_cls}">
            <div style="display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:8px;">
                <div>
                    {signal_badge(sig.get('signal_type', ''))}
                    &nbsp;
                    {bias_badge(bias)}
                    &nbsp;&nbsp;
                    <span style="font-family:'IBM Plex Mono',monospace; font-size:13px;
                                 font-weight:600; color:#E8EAF0;">
                        {int(sig.get('strike', 0))} {sig.get('option_type', '')}
                    </span>
                    <span style="font-family:'IBM Plex Mono',monospace; font-size:11px;
                                 color:#6B7280; margin-left:8px;">
                        {sig.get('expiry', '')}
                    </span>
                </div>
                <div style="font-family:'IBM Plex Mono',monospace; font-size:10px; color:#4B5268;">
                    {ts_display}
                </div>
            </div>
            <div style="display:flex; gap:24px; margin-top:12px; flex-wrap:wrap;">
                <div style="font-family:'IBM Plex Mono',monospace; font-size:11px; color:#8B92A8;">
                    Strength &nbsp;<span style="color:#E8EAF0">{sig.get('signal_strength', 0):.2f}/5</span>
                </div>
                <div style="font-family:'IBM Plex Mono',monospace; font-size:11px; color:#8B92A8;">
                    OI Δ &nbsp;<span style="color:#E8EAF0">{fmt_oi(sig.get('oi_change'))}</span>
                </div>
                <div style="font-family:'IBM Plex Mono',monospace; font-size:11px; color:#8B92A8;">
                    Volume &nbsp;<span style="color:#E8EAF0">{fmt_oi(sig.get('volume'))}</span>
                </div>
                <div style="font-family:'IBM Plex Mono',monospace; font-size:11px; color:#8B92A8;">
                    IV &nbsp;<span style="color:#E8EAF0">{fmt_pct(sig.get('iv'))}</span>
                </div>
                <div style="font-family:'IBM Plex Mono',monospace; font-size:11px; color:#8B92A8;">
                    Spot &nbsp;<span style="color:#E8EAF0">{fmt_price(sig.get('spot_price'))}</span>
                </div>
                <div style="font-family:'IBM Plex Mono',monospace; font-size:11px; color:#8B92A8;">
                    Mode &nbsp;<span style="color:#6B7280">{sig.get('mode', '—')}</span>
                </div>
            </div>
            {thesis_html}
        </div>
        """, unsafe_allow_html=True)

        # Expandable news section
        sig_id = int(sig.get("id", 0))
        with st.expander("📰 Related News", expanded=False):
            news = get_news_for_signal(sig_id)
            if news:
                for item in news:
                    st.markdown(f"""
                    <div style="font-family:'IBM Plex Sans',sans-serif; font-size:12px;
                                color:#8B92A8; padding:6px 0; border-bottom:1px solid #1E2330;">
                        <span style="color:#E8EAF0">{item['headline']}</span>
                        <span style="font-family:'IBM Plex Mono',monospace; font-size:10px;
                                     color:#4B5268; margin-left:8px;">{item['source']}</span>
                    </div>
                    """, unsafe_allow_html=True)
            else:
                st.markdown("""
                <div style="font-family:'IBM Plex Mono',monospace; font-size:11px;
                            color:#4B5268; padding:8px 0;">
                    No news stored for this signal window
                </div>
                """, unsafe_allow_html=True)

        st.markdown("<div style='margin-bottom:4px;'></div>", unsafe_allow_html=True)