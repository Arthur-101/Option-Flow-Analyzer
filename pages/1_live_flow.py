# pages/1_live_flow.py — Live Options Flow

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timezone

from ui.components import (
    inject_global_css, metric_card, section_header,
    empty_state, fmt_oi, fmt_price, fmt_pct,
    compute_rsi, rsi_color, pcr_color, oi_change_color,
)
from ui.queries import (
    get_latest_spot, get_latest_timestamp, get_pcr,
    get_latest_chain, get_spot_series, get_oi_by_strike,
    get_available_expiries,
)

st.set_page_config(page_title="Live Flow · OFA", layout="wide")
inject_global_css()

# ── Auto-refresh ───────────────────────────────────────────────────────────────
REFRESH_SECS = 300  # 5 minutes matching poll cycle

# ── Header ─────────────────────────────────────────────────────────────────────
col_h1, col_h2 = st.columns([3, 1])
with col_h1:
    st.markdown("""
    <div style="padding-bottom:8px;">
        <span style="font-family:'IBM Plex Mono',monospace; font-size:22px;
                     font-weight:600; color:#E8EAF0;">
            <span class="live-dot"></span> Live Flow
        </span>
        <span style="font-family:'IBM Plex Mono',monospace; font-size:11px;
                     color:#4B5268; margin-left:12px; letter-spacing:0.08em;">
            NIFTY · NSE
        </span>
    </div>
    """, unsafe_allow_html=True)
with col_h2:
    if st.button("↻ Refresh", use_container_width=True):
        st.rerun()

# ── Key metrics row ────────────────────────────────────────────────────────────
spot    = get_latest_spot()
pcr     = get_pcr()
last_ts = get_latest_timestamp()
spot_df = get_spot_series()
rsi     = compute_rsi(spot_df["spot"].tolist()) if not spot_df.empty else None

# VWAP from spot series (simple average as proxy)
vwap = round(spot_df["spot"].mean(), 2) if not spot_df.empty else None

m1, m2, m3, m4, m5 = st.columns(5)
with m1:
    spot_str = f"₹{spot:,.2f}" if spot else "—"
    metric_card("NIFTY Spot", spot_str)
with m2:
    pcr_str = f"{pcr:.3f}" if pcr else "—"
    pcr_style = ""
    if pcr:
        pcr_style = "bearish" if pcr > 1.3 else ("bullish" if pcr < 0.7 else "")
    metric_card("Put/Call Ratio", pcr_str,
                sub="Bearish" if (pcr and pcr > 1.3) else ("Bullish" if (pcr and pcr < 0.7) else "Balanced"),
                style=pcr_style)
with m3:
    rsi_str = f"{rsi:.1f}" if rsi else "—"
    rsi_style = "bearish" if (rsi and rsi > 70) else ("bullish" if (rsi and rsi < 30) else "")
    rsi_sub = ""
    if rsi:
        if rsi >= 70: rsi_sub = "Overbought"
        elif rsi >= 60: rsi_sub = "Upper mid"
        elif rsi >= 40: rsi_sub = "Neutral"
        elif rsi >= 30: rsi_sub = "Lower mid"
        else: rsi_sub = "Oversold"
    metric_card("RSI (14)", rsi_str, sub=rsi_sub, style=rsi_style)
with m4:
    vwap_str = f"₹{vwap:,.2f}" if vwap else "—"
    vwap_sub = ""
    if spot and vwap:
        vwap_sub = "Above VWAP" if spot > vwap else "Below VWAP"
    metric_card("Session VWAP", vwap_str, sub=vwap_sub)
with m5:
    ts_str = last_ts[11:16] + " UTC" if last_ts else "No data"
    metric_card("Last Update", ts_str, sub="Auto-refreshes every 5min")

st.markdown("<div style='margin-top:24px;'></div>", unsafe_allow_html=True)

# ── Chain table ────────────────────────────────────────────────────────────────
section_header("Options Chain — Latest Snapshot")

chain = get_latest_chain()

if chain.empty:
    empty_state("NO DATA · Run main.py or catchup.py to load today's options chain")
else:
    # Expiry filter
    expiries = get_available_expiries()
    selected_expiry = st.selectbox(
        "Expiry",
        options=expiries,
        index=0,
        label_visibility="collapsed"
    )

    filtered = chain[chain["expiry"] == selected_expiry].copy()

    # Split CE and PE
    ce = filtered[filtered["option_type"] == "CE"].set_index("strike")
    pe = filtered[filtered["option_type"] == "PE"].set_index("strike")

    # Build display table
    all_strikes = sorted(set(ce.index) | set(pe.index))

    rows = []
    for strike in all_strikes:
        ce_row = ce.loc[strike] if strike in ce.index else None
        pe_row = pe.loc[strike] if strike in pe.index else None

        # Highlight ATM
        is_atm = spot and abs(strike - spot) <= 50

        rows.append({
            "CE OI":      fmt_oi(ce_row["oi"]) if ce_row is not None else "—",
            "CE Δ OI":    fmt_oi(ce_row["oi_change"]) if ce_row is not None else "—",
            "CE Vol":     fmt_oi(ce_row["volume"]) if ce_row is not None else "—",
            "CE IV":      fmt_pct(ce_row["iv"]) if ce_row is not None else "—",
            "CE LTP":     fmt_price(ce_row["last_price"]) if ce_row is not None else "—",
            "STRIKE":     f"{'★ ' if is_atm else ''}{int(strike)}",
            "PE LTP":     fmt_price(pe_row["last_price"]) if pe_row is not None else "—",
            "PE IV":      fmt_pct(pe_row["iv"]) if pe_row is not None else "—",
            "PE Vol":     fmt_oi(pe_row["volume"]) if pe_row is not None else "—",
            "PE Δ OI":    fmt_oi(pe_row["oi_change"]) if pe_row is not None else "—",
            "PE OI":      fmt_oi(pe_row["oi"]) if pe_row is not None else "—",
        })

    df_display = pd.DataFrame(rows)

    st.dataframe(
        df_display,
        use_container_width=True,
        height=520,
        hide_index=True,
        column_config={
            "STRIKE": st.column_config.TextColumn("STRIKE", width=90),
        }
    )

    # Quick stats below table
    st.markdown("<div style='margin-top:12px;'></div>", unsafe_allow_html=True)
    s1, s2, s3, s4 = st.columns(4)
    with s1:
        total_ce_oi = filtered[filtered["option_type"]=="CE"]["oi"].sum()
        st.markdown(f"""<div style="font-family:'IBM Plex Mono',monospace; font-size:11px;
                        color:#8B92A8;">Total CE OI <span style="color:#F59E0B">{fmt_oi(total_ce_oi)}</span></div>""",
                    unsafe_allow_html=True)
    with s2:
        total_pe_oi = filtered[filtered["option_type"]=="PE"]["oi"].sum()
        st.markdown(f"""<div style="font-family:'IBM Plex Mono',monospace; font-size:11px;
                        color:#8B92A8;">Total PE OI <span style="color:#EF4444">{fmt_oi(total_pe_oi)}</span></div>""",
                    unsafe_allow_html=True)
    with s3:
        max_ce = filtered[filtered["option_type"]=="CE"].nlargest(1, "oi")
        if not max_ce.empty:
            st.markdown(f"""<div style="font-family:'IBM Plex Mono',monospace; font-size:11px;
                            color:#8B92A8;">Max CE OI <span style="color:#E8EAF0">{int(max_ce.iloc[0]['strike'])}</span></div>""",
                        unsafe_allow_html=True)
    with s4:
        max_pe = filtered[filtered["option_type"]=="PE"].nlargest(1, "oi")
        if not max_pe.empty:
            st.markdown(f"""<div style="font-family:'IBM Plex Mono',monospace; font-size:11px;
                            color:#8B92A8;">Max PE OI <span style="color:#E8EAF0">{int(max_pe.iloc[0]['strike'])}</span></div>""",
                        unsafe_allow_html=True)