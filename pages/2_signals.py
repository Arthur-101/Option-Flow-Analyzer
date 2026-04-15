import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime, timezone, timedelta

import streamlit as st
from ui.components import inject_global_css, metric_card_c, section_header, empty_state, sig_type_badge, bias_bdg, conf_pips, fmt_oi, fmt_oi_change, fmt_price, fmt_pct
from ui.queries import get_all_signals, get_signal_stats, get_news_for_signal

st.set_page_config(page_title="Signals · OFA", layout="wide", initial_sidebar_state="expanded")
inject_global_css()

st.markdown("""
<div style="padding:24px 24px 0">
    <div style="font-size:20px;font-weight:700;color:#F0F4FF;letter-spacing:-0.02em">Signals</div>
    <div style="font-size:12px;color:#505A75;margin-top:2px">Anomaly detection · AI-powered thesis generation</div>
</div>""", unsafe_allow_html=True)

# ── Stats ──────────────────────────────────────────────────────────────────────
stats = get_signal_stats()
st.markdown("<div style='padding:16px 24px 0'>", unsafe_allow_html=True)
cols = st.columns(4, gap="small")
with cols[0]: metric_card_c("Today's Signals", str(stats.get("today", 0)))
with cols[1]: metric_card_c("Bullish", str(stats.get("bullish", 0)), color="amber")
with cols[2]: metric_card_c("Bearish", str(stats.get("bearish", 0)), color="red")
with cols[3]: metric_card_c("With AI Thesis", str(stats.get("with_thesis", 0)), color="green")
st.markdown("</div>", unsafe_allow_html=True)
st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)

# ── Filters ────────────────────────────────────────────────────────────────────
section_header("Signal Feed")

st.markdown("<div style='padding:0 24px 12px'>", unsafe_allow_html=True)
f1, f2, f3, f4 = st.columns([2, 2, 2, 2])
with f1: period = st.selectbox("Period", ["Today", "Last 3 days", "Last 7 days"], label_visibility="collapsed")
with f2: bias_f = st.selectbox("Bias", ["All biases", "BULLISH", "BEARISH", "NEUTRAL"], label_visibility="collapsed")
with f3: type_f = st.selectbox("Type", ["All types", "OI_BUILDUP", "OI_UNWIND", "VOLUME_SPIKE", "IV_SPIKE"], label_visibility="collapsed")
with f4: thesis_only = st.checkbox("With thesis only", value=False)
st.markdown("</div>", unsafe_allow_html=True)

# ── Load + filter ──────────────────────────────────────────────────────────────
days_map = {"Today": 1, "Last 3 days": 3, "Last 7 days": 7}
signals = get_all_signals(days=days_map[period])

if not signals.empty:
    if bias_f != "All biases": signals = signals[signals["bias"] == bias_f]
    if type_f != "All types": signals = signals[signals["signal_type"] == type_f]
    if thesis_only: signals = signals[signals["llm_thesis"].notna()]

# ── Signal cards ───────────────────────────────────────────────────────────────
st.markdown("<div style='padding:0 24px 24px'>", unsafe_allow_html=True)

if signals.empty:
    empty_state("No signals found", "Detection runs every 5 minutes during market hours (9:15–15:30 IST)")
else:
    for _, sig in signals.iterrows():
        bias = (sig.get("bias") or "NEUTRAL").upper()
        bias_cls = {"BULLISH": "bull", "BEARISH": "bear"}.get(bias, "neutral")

        # Timestamp → IST
        ts_raw = sig.get("fired_at", "")
        try:
            dt = datetime.strptime(ts_raw[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            ts_ist = (dt + timedelta(hours=5, minutes=30)).strftime("%d %b · %H:%M IST")
        except: ts_ist = ts_raw[:16]

        # OI change color
        oi_ch = sig.get("oi_change")
        import math
        oi_cls = ""
        try:
            if oi_ch and not math.isnan(float(oi_ch)):
                oi_cls = "g" if float(oi_ch) > 0 else "r"
        except: pass

        # Thesis block
        thesis = sig.get("llm_thesis")
        llm_bias = sig.get("llm_bias")
        llm_conf = sig.get("llm_confidence")

        if thesis:
            thesis_html = (
                '<div class="sig-thesis">'
                '<div class="thesis-hd">'
                '<span class="thesis-lbl">AI Thesis</span>'
                + (bias_bdg(llm_bias) if llm_bias else "")
                + '<span style="margin-left:4px">' + conf_pips(llm_conf) + '</span>'
                + '</div>'
                + str(thesis)
                + '</div>'
            )
        else:
            thesis_html = '<div class="thesis-pending">Thesis generation pending...</div>'

        st.markdown(f"""
        <div class="sig {bias_cls}">
            <div class="sig-hd">
                {sig_type_badge(sig.get('signal_type',''))}
                {bias_bdg(bias)}
                <span class="sig-strike">{int(sig.get('strike',0))} {sig.get('option_type','')}</span>
                <span class="sig-exp">{sig.get('expiry','')}</span>
                <span class="sig-ts">{ts_ist}</span>
            </div>
            <div class="sig-stats">
                <div class="sig-stat"><div class="ss-label">Strength</div><div class="ss-val a">{sig.get('signal_strength',0):.2f}/5</div></div>
                <div class="sig-stat"><div class="ss-label">OI Δ</div><div class="ss-val {oi_cls}">{fmt_oi_change(oi_ch)}</div></div>
                <div class="sig-stat"><div class="ss-label">Volume</div><div class="ss-val">{fmt_oi(sig.get('volume'))}</div></div>
                <div class="sig-stat"><div class="ss-label">IV</div><div class="ss-val">{fmt_pct(sig.get('iv'))}</div></div>
                <div class="sig-stat"><div class="ss-label">Spot</div><div class="ss-val">{fmt_price(sig.get('spot_price'))}</div></div>
                <div class="sig-stat"><div class="ss-label">Mode</div><div class="ss-val" style="color:var(--text-tertiary);font-size:10px">{sig.get('mode','—')}</div></div>
            </div>
            {thesis_html}
        </div>""", unsafe_allow_html=True)

        # News expander
        with st.expander("Related news", expanded=False):
            news = get_news_for_signal(int(sig.get("id", 0)))
            if news:
                for item in news:
                    st.markdown(f"""
                    <div style="padding:8px 0;border-bottom:1px solid rgba(255,255,255,0.05)">
                        <div style="font-size:12px;color:#F0F4FF;line-height:1.5">{item['headline']}</div>
                        <div style="font-size:10px;color:#505A75;margin-top:3px;font-family:'JetBrains Mono',monospace">{item['source']} · {item.get('published_at','')[:16]}</div>
                    </div>""", unsafe_allow_html=True)
            else:
                st.markdown("<div style='font-size:11px;color:#353D55;padding:8px 0'>No news stored for this signal window.</div>", unsafe_allow_html=True)

st.markdown("</div>", unsafe_allow_html=True)