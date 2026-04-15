import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import pandas as pd
from ui.components import inject_global_css, metric_card_c, section_header, empty_state, fmt_oi, fmt_price, fmt_pct, fmt_oi_change, compute_rsi
from ui.queries import get_latest_spot, get_latest_timestamp, get_pcr, get_latest_chain, get_spot_series, get_available_expiries

st.set_page_config(page_title="Live Flow · OFA", layout="wide", initial_sidebar_state="expanded")
inject_global_css()

# ── Header ─────────────────────────────────────────────────────────────────────
c1, c2 = st.columns([1, 0])
st.markdown("""
<div style="padding:24px 24px 0">
    <div style="display:flex;align-items:center;justify-content:space-between">
        <div>
            <div style="font-size:20px;font-weight:700;color:#F0F4FF;letter-spacing:-0.02em">Live Flow</div>
            <div style="font-size:12px;color:#505A75;margin-top:2px">NIFTY Index Options · Real-time options chain</div>
        </div>
        <div style="display:flex;align-items:center;gap:12px">
            <div class="live"><div class="live-dot"></div>WebSocket Active</div>
        </div>
    </div>
</div>""", unsafe_allow_html=True)

# ── Fetch data ─────────────────────────────────────────────────────────────────
spot = get_latest_spot()
pcr  = get_pcr()
last = get_latest_timestamp()
spot_df = get_spot_series()
rsi = compute_rsi(spot_df["spot"].tolist()) if not spot_df.empty else None
vwap = round(spot_df["spot"].mean(), 2) if not spot_df.empty else None

st.markdown("<div style='padding:16px 24px 0'>", unsafe_allow_html=True)

# ── Metrics strip ──────────────────────────────────────────────────────────────
cols = st.columns(5, gap="small")

with cols[0]:
    metric_card_c("NIFTY Spot", fmt_price(spot) if spot else "—", meta="Index price" if spot else "No data")

with cols[1]:
    if pcr:
        if pcr > 1.3: pcr_color, pcr_meta, pcr_mc = "red", f"Bearish · PCR {pcr}", "down"
        elif pcr < 0.7: pcr_color, pcr_meta, pcr_mc = "green", f"Bullish · PCR {pcr}", "up"
        else: pcr_color, pcr_meta, pcr_mc = "", f"Balanced · PCR {pcr}", ""
        metric_card_c("Put/Call Ratio", f"{pcr:.3f}", color=pcr_color, meta=pcr_meta, meta_cls=pcr_mc)
    else:
        metric_card_c("Put/Call Ratio", "—", meta="No data today")

with cols[2]:
    if rsi:
        if rsi >= 70: r_color, r_meta = "red", f"Overbought · {rsi}"
        elif rsi >= 60: r_color, r_meta = "amber", f"Upper mid · {rsi}"
        elif rsi >= 40: r_color, r_meta = "green", f"Neutral · {rsi}"
        elif rsi >= 30: r_color, r_meta = "amber", f"Lower mid · {rsi}"
        else: r_color, r_meta = "red", f"Oversold · {rsi}"
        metric_card_c("RSI (14)", str(rsi), color=r_color, meta=r_meta)
    else:
        metric_card_c("RSI (14)", "—", meta="Need 15+ data points")

with cols[3]:
    if vwap and spot:
        vwap_meta = "▲ Above VWAP" if spot > vwap else "▼ Below VWAP"
        vwap_mc = "up" if spot > vwap else "down"
        metric_card_c("Session VWAP", fmt_price(vwap), meta=vwap_meta, meta_cls=vwap_mc)
    else:
        metric_card_c("Session VWAP", "—")

with cols[4]:
    ts_str = last[11:16] + " UTC" if last else "—"
    flushes = len(spot_df) if not spot_df.empty else 0
    metric_card_c("Last Update", ts_str, meta=f"{flushes} flushes today")

st.markdown("</div>", unsafe_allow_html=True)
st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

# ── Options chain ──────────────────────────────────────────────────────────────
section_header("Options Chain — Latest Snapshot")

chain = get_latest_chain()

if chain.empty:
    st.markdown("<div style='padding:0 24px'>", unsafe_allow_html=True)
    empty_state("No chain data for today", "Run main.py or catchup.py to load data")
    st.markdown("</div>", unsafe_allow_html=True)
else:
    expiries = get_available_expiries()
    col_exp, col_range, _ = st.columns([2, 2, 6])
    with col_exp:
        sel_exp = st.selectbox("Expiry", expiries, label_visibility="collapsed")
    with col_range:
        strike_range = st.selectbox("Range", ["All strikes", "ATM ±10", "ATM ±5"], label_visibility="collapsed")

    filtered = chain[chain["expiry"] == sel_exp].copy()
    ce = filtered[filtered["option_type"] == "CE"].set_index("strike")
    pe = filtered[filtered["option_type"] == "PE"].set_index("strike")
    strikes = sorted(set(ce.index) | set(pe.index))

    # Apply strike range filter
    if spot and strike_range != "All strikes":
        n = 10 if "10" in strike_range else 5
        step = 50  # NIFTY strike step
        atm = round(spot / step) * step
        strikes = [s for s in strikes if abs(s - atm) <= n * step]

    # Build table HTML
    rows_html = ""
    for strike in strikes:
        cr = ce.loc[strike] if strike in ce.index else None
        pr = pe.loc[strike] if strike in pe.index else None
        is_atm = spot and abs(strike - spot) <= 25
        str_cls = "str atm" if is_atm else "str"

        def cv(row, col, fmt_fn=None, change=False):
            if row is None: return '<td class="ce dim">—</td>'
            v = row[col] if hasattr(row, '__getitem__') else getattr(row, col, None)
            if change:
                txt = fmt_oi_change(v)
                import math
                cls = "pos" if (v and not (isinstance(v,float) and math.isnan(v)) and v > 0) else ("neg" if (v and not (isinstance(v,float) and math.isnan(v)) and v < 0) else "dim")
                return f'<td class="ce {cls}">{txt}</td>'
            return f'<td class="ce">{fmt_fn(v) if fmt_fn else v}</td>'

        def pv(row, col, fmt_fn=None, change=False):
            if row is None: return '<td class="pe dim">—</td>'
            v = row[col] if hasattr(row, '__getitem__') else getattr(row, col, None)
            if change:
                txt = fmt_oi_change(v)
                import math
                cls = "pos" if (v and not (isinstance(v,float) and math.isnan(v)) and v > 0) else ("neg" if (v and not (isinstance(v,float) and math.isnan(v)) and v < 0) else "dim")
                return f'<td class="pe {cls}">{txt}</td>'
            return f'<td class="pe">{fmt_fn(v) if fmt_fn else v}</td>'

        atm_badge = '<span style="font-size:8px;color:#F59E0B;margin-left:4px;vertical-align:middle">ATM</span>' if is_atm else ""

        rows_html += f"""<tr>
            {cv(cr, 'oi', fmt_oi)}
            {cv(cr, 'oi_change', change=True)}
            {cv(cr, 'volume', fmt_oi)}
            {cv(cr, 'iv', fmt_pct)}
            {cv(cr, 'last_price', fmt_price)}
            <td class="{str_cls}">{int(strike)}{atm_badge}</td>
            {pv(pr, 'last_price', fmt_price)}
            {pv(pr, 'iv', fmt_pct)}
            {pv(pr, 'volume', fmt_oi)}
            {pv(pr, 'oi_change', change=True)}
            {pv(pr, 'oi', fmt_oi)}
        </tr>"""

    st.markdown(f"""
    <div style="padding:0 24px 24px">
    <div class="chain-wrap">
    <table class="chain">
        <thead><tr>
            <th class="ce-hd">OI</th><th class="ce-hd">Δ OI</th><th class="ce-hd">Volume</th><th class="ce-hd">IV</th><th class="ce-hd">LTP</th>
            <th class="str-hd">STRIKE</th>
            <th class="pe-hd">LTP</th><th class="pe-hd">IV</th><th class="pe-hd">Volume</th><th class="pe-hd">Δ OI</th><th class="pe-hd">OI</th>
        </tr></thead>
        <tbody>{rows_html}</tbody>
    </table>
    </div>
    """, unsafe_allow_html=True)

    # Summary row
    ce_df = filtered[filtered["option_type"] == "CE"]
    pe_df = filtered[filtered["option_type"] == "PE"]
    max_ce = ce_df.nlargest(1, "oi") if not ce_df.empty else pd.DataFrame()
    max_pe = pe_df.nlargest(1, "oi") if not pe_df.empty else pd.DataFrame()

    st.markdown(f"""
    <div style="display:flex;gap:24px;margin-top:12px;padding:10px 0;border-top:1px solid rgba(255,255,255,0.06)">
        <div style="font-size:11px;color:#505A75">Total CE OI <span style="color:#10B981;font-family:'JetBrains Mono',monospace;margin-left:4px">{fmt_oi(ce_df['oi'].sum() if not ce_df.empty else 0)}</span></div>
        <div style="font-size:11px;color:#505A75">Total PE OI <span style="color:#F43F5E;font-family:'JetBrains Mono',monospace;margin-left:4px">{fmt_oi(pe_df['oi'].sum() if not pe_df.empty else 0)}</span></div>
        <div style="font-size:11px;color:#505A75">Max CE strike <span style="color:#F0F4FF;font-family:'JetBrains Mono',monospace;margin-left:4px">{int(max_ce.iloc[0]['strike']) if not max_ce.empty else '—'}</span></div>
        <div style="font-size:11px;color:#505A75">Max PE strike <span style="color:#F0F4FF;font-family:'JetBrains Mono',monospace;margin-left:4px">{int(max_pe.iloc[0]['strike']) if not max_pe.empty else '—'}</span></div>
        <div style="font-size:11px;color:#505A75">Strikes shown <span style="color:#8B95B0;font-family:'JetBrains Mono',monospace;margin-left:4px">{len(strikes)}</span></div>
    </div>
    </div>""", unsafe_allow_html=True)