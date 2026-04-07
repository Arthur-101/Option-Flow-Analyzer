# pages/3_analytics.py — Analytics: OI Charts + IV Skew + Intraday Timeline

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

from ui.components import (
    inject_global_css, section_header, empty_state,
    compute_rsi, fmt_oi,
)
from ui.queries import (
    get_oi_by_strike, get_iv_skew, get_intraday_oi_timeline,
    get_spot_series, get_available_expiries, get_latest_spot,
)

st.set_page_config(page_title="Analytics · OFA", layout="wide")
inject_global_css()

# ── Plotly theme ───────────────────────────────────────────────────────────────
PLOTLY_LAYOUT = dict(
    paper_bgcolor="#0D0F14",
    plot_bgcolor="#13161E",
    font=dict(family="IBM Plex Mono", color="#8B92A8", size=11),
    xaxis=dict(gridcolor="#1E2330", zerolinecolor="#252A38", tickfont=dict(size=10)),
    yaxis=dict(gridcolor="#1E2330", zerolinecolor="#252A38", tickfont=dict(size=10)),
    margin=dict(l=0, r=0, t=32, b=0),
    legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(size=10)),
)

# ── Header ─────────────────────────────────────────────────────────────────────
col_h1, col_h2 = st.columns([3, 1])
with col_h1:
    st.markdown("""
    <div style="padding-bottom:8px;">
        <span style="font-family:'IBM Plex Mono',monospace; font-size:22px;
                     font-weight:600; color:#E8EAF0;">
            📊 Analytics
        </span>
        <span style="font-family:'IBM Plex Mono',monospace; font-size:11px;
                     color:#4B5268; margin-left:12px; letter-spacing:0.08em;">
            OI DISTRIBUTION · IV SKEW · INTRADAY FLOW
        </span>
    </div>
    """, unsafe_allow_html=True)
with col_h2:
    if st.button("↻ Refresh", use_container_width=True):
        st.rerun()

spot = get_latest_spot()
expiries = get_available_expiries()
selected_expiry = expiries[0] if expiries else None

if expiries and len(expiries) > 1:
    selected_expiry = st.selectbox(
        "Expiry", expiries, label_visibility="collapsed"
    )

st.markdown("<div style='margin-top:8px;'></div>", unsafe_allow_html=True)

# ── Row 1: OI Distribution + IV Skew ──────────────────────────────────────────
col_oi, col_iv = st.columns(2)

with col_oi:
    section_header("CE vs PE OI Distribution")
    oi_data = get_oi_by_strike()

    if oi_data.empty:
        empty_state("NO DATA")
    else:
        # Filter to ±10 strikes from ATM
        if spot:
            atm_strikes = sorted(oi_data["strike"].tolist(),
                                 key=lambda x: abs(x - spot))[:20]
            oi_data = oi_data[oi_data["strike"].isin(atm_strikes)]
        oi_data = oi_data.sort_values("strike")

        fig = go.Figure()

        if "CE" in oi_data.columns:
            fig.add_trace(go.Bar(
                x=oi_data["strike"],
                y=oi_data["CE"],
                name="CE OI",
                marker_color="#F59E0B",
                opacity=0.8,
            ))
        if "PE" in oi_data.columns:
            fig.add_trace(go.Bar(
                x=oi_data["strike"],
                y=-oi_data["PE"],   # negative for mirrored waterfall effect
                name="PE OI",
                marker_color="#EF4444",
                opacity=0.8,
            ))

        # ATM line
        if spot:
            fig.add_vline(
                x=spot, line_dash="dash",
                line_color="#60A5FA", line_width=1,
                annotation_text="ATM",
                annotation_font_color="#60A5FA",
                annotation_font_size=10,
            )

        fig.update_layout(
            **PLOTLY_LAYOUT,
            barmode="overlay",
            title=dict(text="Open Interest by Strike", font=dict(size=12, color="#8B92A8")),
            yaxis_title="OI (↑CE · ↓PE)",
            height=320,
        )
        fig.update_yaxes(tickformat=".2s")
        st.plotly_chart(fig, use_container_width=True)

with col_iv:
    section_header("IV Skew")
    iv_data = get_iv_skew(expiry=selected_expiry)

    if iv_data.empty:
        empty_state("NO IV DATA · IV requires spot price and valid LTP")
    else:
        ce_iv = iv_data[iv_data["option_type"] == "CE"].sort_values("strike")
        pe_iv = iv_data[iv_data["option_type"] == "PE"].sort_values("strike")

        fig = go.Figure()

        if not ce_iv.empty:
            fig.add_trace(go.Scatter(
                x=ce_iv["strike"], y=ce_iv["iv"],
                mode="lines+markers",
                name="CE IV",
                line=dict(color="#F59E0B", width=2),
                marker=dict(size=5),
            ))
        if not pe_iv.empty:
            fig.add_trace(go.Scatter(
                x=pe_iv["strike"], y=pe_iv["iv"],
                mode="lines+markers",
                name="PE IV",
                line=dict(color="#EF4444", width=2),
                marker=dict(size=5),
            ))

        if spot:
            fig.add_vline(
                x=spot, line_dash="dash",
                line_color="#60A5FA", line_width=1,
                annotation_text="ATM",
                annotation_font_color="#60A5FA",
                annotation_font_size=10,
            )

        fig.update_layout(
            **PLOTLY_LAYOUT,
            title=dict(text=f"Implied Volatility · {selected_expiry}", font=dict(size=12, color="#8B92A8")),
            yaxis_title="IV %",
            height=320,
        )
        st.plotly_chart(fig, use_container_width=True)

# ── Row 2: Intraday OI Change Timeline ────────────────────────────────────────
st.markdown("<div style='margin-top:8px;'></div>", unsafe_allow_html=True)
section_header("Intraday OI Change Timeline — Top 5 Active Strikes")

oi_timeline = get_intraday_oi_timeline(top_n=5)

if oi_timeline.empty:
    empty_state("NO INTRADAY DATA · Need 2+ flushes today to show OI changes")
else:
    oi_timeline["label"] = (
        oi_timeline["strike"].astype(int).astype(str)
        + " "
        + oi_timeline["option_type"]
    )
    # Convert timestamp to IST
    from datetime import datetime, timezone, timedelta
    def to_ist(ts):
        try:
            dt = datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            return (dt + timedelta(hours=5, minutes=30)).strftime("%H:%M")
        except:
            return ts[11:16]

    oi_timeline["time_ist"] = oi_timeline["timestamp"].apply(to_ist)

    COLORS = ["#F59E0B", "#EF4444", "#10B981", "#60A5FA", "#A78BFA"]

    fig = go.Figure()
    for i, label in enumerate(oi_timeline["label"].unique()):
        subset = oi_timeline[oi_timeline["label"] == label]
        color = COLORS[i % len(COLORS)]
        fig.add_trace(go.Scatter(
            x=subset["time_ist"],
            y=subset["oi_change"],
            mode="lines+markers",
            name=label,
            line=dict(color=color, width=2),
            marker=dict(size=5),
        ))

    fig.add_hline(y=0, line_color="#252A38", line_width=1)

    fig.update_layout(
        **PLOTLY_LAYOUT,
        title=dict(text="OI Change per 5-min Interval (IST)", font=dict(size=12, color="#8B92A8")),
        yaxis_title="OI Change (contracts)",
        height=340,
        xaxis_title="Time (IST)",
    )
    fig.update_yaxes(tickformat=".2s")
    st.plotly_chart(fig, use_container_width=True)

# ── Row 3: RSI chart ───────────────────────────────────────────────────────────
st.markdown("<div style='margin-top:8px;'></div>", unsafe_allow_html=True)
section_header("NIFTY Spot + RSI (Intraday)")

spot_df = get_spot_series()

if spot_df.empty or len(spot_df) < 3:
    empty_state("NEED MORE DATA · RSI requires at least 15 data points")
else:
    from datetime import datetime, timezone, timedelta
    def ts_to_ist(ts):
        try:
            dt = datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            return (dt + timedelta(hours=5, minutes=30)).strftime("%H:%M")
        except:
            return ts[11:16]

    spot_df["time_ist"] = spot_df["timestamp"].apply(ts_to_ist)

    # Compute rolling RSI
    prices = spot_df["spot"].tolist()
    rsi_values = [None] * 14
    for i in range(14, len(prices)):
        rsi_val = compute_rsi(prices[:i+1])
        rsi_values.append(rsi_val)

    spot_df["rsi"] = rsi_values

    col_spot, col_rsi = st.columns(2)

    with col_spot:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=spot_df["time_ist"],
            y=spot_df["spot"],
            mode="lines",
            name="NIFTY Spot",
            line=dict(color="#F59E0B", width=2),
            fill="tozeroy",
            fillcolor="rgba(245,158,11,0.05)",
        ))
        fig.update_layout(
            **PLOTLY_LAYOUT,
            title=dict(text="NIFTY Spot Price (IST)", font=dict(size=12, color="#8B92A8")),
            height=260,
            yaxis_title="₹",
        )
        st.plotly_chart(fig, use_container_width=True)

    with col_rsi:
        rsi_df = spot_df.dropna(subset=["rsi"])
        fig = go.Figure()

        # Overbought/oversold zones
        fig.add_hrect(y0=70, y1=100, fillcolor="rgba(239,68,68,0.08)",
                      line_width=0, annotation_text="Overbought",
                      annotation_font_size=9, annotation_font_color="#EF4444")
        fig.add_hrect(y0=0, y1=30, fillcolor="rgba(16,185,129,0.08)",
                      line_width=0, annotation_text="Oversold",
                      annotation_font_size=9, annotation_font_color="#10B981")
        fig.add_hline(y=50, line_dash="dot", line_color="#252A38", line_width=1)

        fig.add_trace(go.Scatter(
            x=rsi_df["time_ist"],
            y=rsi_df["rsi"],
            mode="lines",
            name="RSI(14)",
            line=dict(color="#60A5FA", width=2),
        ))

        fig.update_layout(
            **{k: v for k, v in PLOTLY_LAYOUT.items() if k != "yaxis"},
            title=dict(text="RSI (14) — NIFTY Spot", font=dict(size=12, color="#8B92A8")),
            height=260,
            yaxis=dict(range=[0, 100], gridcolor="#1E2330", tickfont=dict(size=10)),
        )
        st.plotly_chart(fig, use_container_width=True)