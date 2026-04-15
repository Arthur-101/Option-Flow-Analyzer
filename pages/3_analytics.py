import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime, timezone, timedelta

import streamlit as st
import plotly.graph_objects as go
from ui.components import inject_global_css, section_header, empty_state, compute_rsi
from ui.queries import get_oi_by_strike, get_iv_skew, get_intraday_oi_timeline, get_spot_series, get_available_expiries, get_latest_spot

st.set_page_config(page_title="Analytics · OFA", layout="wide", initial_sidebar_state="expanded")
inject_global_css()

st.markdown("""
<div style="padding:24px 24px 0">
    <div style="font-size:20px;font-weight:700;color:#F0F4FF;letter-spacing:-0.02em">Analytics</div>
    <div style="font-size:12px;color:#505A75;margin-top:2px">OI distribution · IV skew · Intraday flow · RSI</div>
</div>""", unsafe_allow_html=True)

# Shared plotly theme
LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="#1C2333",
    font=dict(family="JetBrains Mono", color="#8B95B0", size=10),
    xaxis=dict(gridcolor="rgba(255,255,255,0.04)", zerolinecolor="rgba(255,255,255,0.08)", tickfont=dict(size=9), linecolor="rgba(255,255,255,0.06)"),
    yaxis=dict(gridcolor="rgba(255,255,255,0.04)", zerolinecolor="rgba(255,255,255,0.08)", tickfont=dict(size=9), linecolor="rgba(255,255,255,0.06)"),
    margin=dict(l=8, r=8, t=36, b=8),
    legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(size=9), orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    hoverlabel=dict(bgcolor="#1C2333", bordercolor="rgba(255,255,255,0.12)", font=dict(family="JetBrains Mono", size=11)),
)

def ist(ts):
    try:
        dt = datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        return (dt + timedelta(hours=5, minutes=30)).strftime("%H:%M")
    except: return ts[11:16]

spot = get_latest_spot()
expiries = get_available_expiries()
sel_exp = expiries[0] if expiries else None

# Expiry selector
if expiries:
    st.markdown("<div style='padding:12px 24px 0'>", unsafe_allow_html=True)
    ecol, _ = st.columns([2, 8])
    with ecol:
        sel_exp = st.selectbox("Expiry", expiries, label_visibility="collapsed")
    st.markdown("</div>", unsafe_allow_html=True)

# ── Row 1: OI Distribution + IV Skew ──────────────────────────────────────────
section_header("Open Interest Distribution")
col_oi, col_iv = st.columns(2, gap="small")

with col_oi:
    oi_data = get_oi_by_strike()
    if oi_data.empty:
        st.markdown("<div style='padding:0 12px 0 24px'>", unsafe_allow_html=True)
        empty_state("No OI data", "Load today's chain first")
        st.markdown("</div>", unsafe_allow_html=True)
    else:
        if spot:
            n = 20
            step = 50
            atm = round(spot / step) * step
            oi_data = oi_data[abs(oi_data["strike"] - atm) <= n * step]
        oi_data = oi_data.sort_values("strike")

        fig = go.Figure()
        if "CE" in oi_data.columns:
            fig.add_trace(go.Bar(x=oi_data["strike"], y=oi_data["CE"], name="CE OI", marker_color="#10B981", marker_opacity=0.75))
        if "PE" in oi_data.columns:
            fig.add_trace(go.Bar(x=oi_data["strike"], y=-oi_data["PE"], name="PE OI", marker_color="#F43F5E", marker_opacity=0.75))
        if spot:
            fig.add_vline(x=spot, line_dash="dot", line_color="#F59E0B", line_width=1.5, annotation_text="ATM", annotation_font_color="#F59E0B", annotation_font_size=9)

        fig.update_layout(**LAYOUT, barmode="overlay", height=300,
                          title=dict(text="CE vs PE Open Interest", font=dict(size=11, color="#8B95B0")))
        fig.update_yaxes(tickformat=".2s")
        st.markdown("<div style='padding:0 12px 0 24px'>", unsafe_allow_html=True)
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        st.markdown("</div>", unsafe_allow_html=True)

with col_iv:
    iv_data = get_iv_skew(expiry=sel_exp)
    if iv_data.empty:
        st.markdown("<div style='padding:0 24px 0 12px'>", unsafe_allow_html=True)
        empty_state("No IV data", "IV requires valid LTP and spot price")
        st.markdown("</div>", unsafe_allow_html=True)
    else:
        ce_iv = iv_data[iv_data["option_type"] == "CE"].sort_values("strike")
        pe_iv = iv_data[iv_data["option_type"] == "PE"].sort_values("strike")
        fig = go.Figure()
        if not ce_iv.empty:
            fig.add_trace(go.Scatter(x=ce_iv["strike"], y=ce_iv["iv"], mode="lines+markers", name="CE IV",
                                     line=dict(color="#10B981", width=2), marker=dict(size=4)))
        if not pe_iv.empty:
            fig.add_trace(go.Scatter(x=pe_iv["strike"], y=pe_iv["iv"], mode="lines+markers", name="PE IV",
                                     line=dict(color="#F43F5E", width=2), marker=dict(size=4)))
        if spot:
            fig.add_vline(x=spot, line_dash="dot", line_color="#F59E0B", line_width=1.5, annotation_text="ATM", annotation_font_color="#F59E0B", annotation_font_size=9)
        fig.update_layout(**LAYOUT, height=300,
                          title=dict(text=f"IV Skew · {sel_exp}", font=dict(size=11, color="#8B95B0")),
                          yaxis_title="IV %")
        st.markdown("<div style='padding:0 24px 0 12px'>", unsafe_allow_html=True)
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        st.markdown("</div>", unsafe_allow_html=True)

# ── Row 2: Intraday OI timeline ────────────────────────────────────────────────
section_header("Intraday OI Change Timeline")

oi_tl = get_intraday_oi_timeline(top_n=5)
if oi_tl.empty:
    st.markdown("<div style='padding:0 24px'>", unsafe_allow_html=True)
    empty_state("No intraday data", "Need 2+ flushes today to show OI changes")
    st.markdown("</div>", unsafe_allow_html=True)
else:
    oi_tl["label"] = oi_tl["strike"].astype(int).astype(str) + " " + oi_tl["option_type"]
    oi_tl["time_ist"] = oi_tl["timestamp"].apply(ist)
    COLORS = ["#10B981", "#F43F5E", "#3B82F6", "#F59E0B", "#8B5CF6"]
    fig = go.Figure()
    for i, label in enumerate(oi_tl["label"].unique()):
        sub = oi_tl[oi_tl["label"] == label]
        fig.add_trace(go.Scatter(x=sub["time_ist"], y=sub["oi_change"], mode="lines+markers", name=label,
                                 line=dict(color=COLORS[i % len(COLORS)], width=2), marker=dict(size=4)))
    fig.add_hline(y=0, line_color="rgba(255,255,255,0.08)", line_width=1)
    fig.update_layout(**LAYOUT, height=280, title=dict(text="OI Change per 5-min Interval (IST)", font=dict(size=11, color="#8B95B0")),
                      yaxis_title="Contracts")
    fig.update_yaxes(tickformat=".2s")
    st.markdown("<div style='padding:0 24px'>", unsafe_allow_html=True)
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    st.markdown("</div>", unsafe_allow_html=True)

# ── Row 3: Spot + RSI ─────────────────────────────────────────────────────────
section_header("NIFTY Spot Price · RSI (14)")

spot_df = get_spot_series()
if spot_df.empty or len(spot_df) < 3:
    st.markdown("<div style='padding:0 24px 24px'>", unsafe_allow_html=True)
    empty_state("Need more data", "RSI requires at least 15 data points (75 min)")
    st.markdown("</div>", unsafe_allow_html=True)
else:
    spot_df["time_ist"] = spot_df["timestamp"].apply(ist)
    prices = spot_df["spot"].tolist()
    rsi_vals = [None] * 14
    for i in range(14, len(prices)):
        rsi_vals.append(compute_rsi(prices[:i+1]))
    spot_df["rsi"] = rsi_vals

    col_sp, col_rsi = st.columns(2, gap="small")

    with col_sp:
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=spot_df["time_ist"], y=spot_df["spot"], mode="lines", name="Spot",
                                 line=dict(color="#F59E0B", width=2),
                                 fill="tozeroy", fillcolor="rgba(245,158,11,0.04)"))
        fig.update_layout(**LAYOUT, height=240,
                          title=dict(text="NIFTY Spot (IST)", font=dict(size=11, color="#8B95B0")),
                          yaxis_title="₹")
        st.markdown("<div style='padding:0 12px 24px 24px'>", unsafe_allow_html=True)
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        st.markdown("</div>", unsafe_allow_html=True)

    with col_rsi:
        rsi_df = spot_df.dropna(subset=["rsi"])
        fig = go.Figure()
        fig.add_hrect(y0=70, y1=100, fillcolor="rgba(244,63,94,0.06)", line_width=0)
        fig.add_hrect(y0=0, y1=30, fillcolor="rgba(16,185,129,0.06)", line_width=0)
        fig.add_hline(y=70, line_dash="dot", line_color="rgba(244,63,94,0.3)", line_width=1)
        fig.add_hline(y=30, line_dash="dot", line_color="rgba(16,185,129,0.3)", line_width=1)
        fig.add_hline(y=50, line_dash="dot", line_color="rgba(255,255,255,0.06)", line_width=1)
        if not rsi_df.empty:
            fig.add_trace(go.Scatter(x=rsi_df["time_ist"], y=rsi_df["rsi"], mode="lines", name="RSI(14)",
                                     line=dict(color="#3B82F6", width=2)))
        layout_rsi = {**{k: v for k, v in LAYOUT.items() if k != "yaxis"},
                      "yaxis": dict(range=[0, 100], gridcolor="rgba(255,255,255,0.04)", tickfont=dict(size=9), linecolor="rgba(255,255,255,0.06)")}
        fig.update_layout(**layout_rsi, height=240,
                          title=dict(text="RSI (14) — Overbought >70 · Oversold <30", font=dict(size=11, color="#8B95B0")))
        st.markdown("<div style='padding:0 24px 24px 12px'>", unsafe_allow_html=True)
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        st.markdown("</div>", unsafe_allow_html=True)