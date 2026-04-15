import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st
from ui.components import inject_global_css
from ui.queries import get_db_stats, get_latest_timestamp, get_signal_stats

st.set_page_config(page_title="OFA — Options Flow Analyzer", page_icon="🔥", layout="wide", initial_sidebar_state="expanded")
inject_global_css()

# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("""
    <div style="padding:20px 16px 16px">
        <div style="font-family:'Inter',sans-serif;font-size:20px;font-weight:700;color:#F59E0B;letter-spacing:-0.03em">OFA</div>
        <div style="font-family:'JetBrains Mono',monospace;font-size:9px;color:#505A75;letter-spacing:0.14em;text-transform:uppercase;margin-top:2px">Options Flow Analyzer</div>
    </div>
    <div style="height:1px;background:rgba(255,255,255,0.06);margin:0 16px 12px"></div>
    """, unsafe_allow_html=True)

    st.page_link("pages/1_live_flow.py",  label="⚡  Live Flow",   use_container_width=True)
    st.page_link("pages/2_signals.py",    label="🎯  Signals",     use_container_width=True)
    st.page_link("pages/3_analytics.py",  label="📊  Analytics",   use_container_width=True)

    st.markdown("<div style='height:1px;background:rgba(255,255,255,0.06);margin:16px 16px 12px'></div>", unsafe_allow_html=True)

    db = get_db_stats()
    sig = get_signal_stats()
    last = get_latest_timestamp()

    st.markdown(f"""
    <div style="padding:0 16px 8px">
        <div style="font-size:9px;font-weight:600;letter-spacing:0.1em;text-transform:uppercase;color:#505A75;margin-bottom:10px">Database</div>
        <div style="display:flex;flex-direction:column;gap:6px">
            <div style="display:flex;justify-content:space-between;font-size:11px">
                <span style="color:#505A75">Rows</span>
                <span style="color:#8B95B0;font-family:'JetBrains Mono',monospace">{db.get('total_rows',0):,}</span>
            </div>
            <div style="display:flex;justify-content:space-between;font-size:11px">
                <span style="color:#505A75">Trading days</span>
                <span style="color:#8B95B0;font-family:'JetBrains Mono',monospace">{db.get('trading_days',0)}</span>
            </div>
            <div style="display:flex;justify-content:space-between;font-size:11px">
                <span style="color:#505A75">Signals today</span>
                <span style="color:#8B95B0;font-family:'JetBrains Mono',monospace">{sig.get('today',0)}</span>
            </div>
            <div style="display:flex;justify-content:space-between;font-size:11px">
                <span style="color:#505A75">Last update</span>
                <span style="color:#8B95B0;font-family:'JetBrains Mono',monospace">{last[11:16]+' UTC' if last else '—'}</span>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("""
    <div style="position:absolute;bottom:16px;left:16px;right:16px">
        <div style="font-size:9px;color:#353D55;text-align:center;line-height:1.5">
            For educational purposes only<br>Not financial advice
        </div>
    </div>""", unsafe_allow_html=True)

# ── Home ───────────────────────────────────────────────────────────────────────
st.markdown("""
<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:70vh;text-align:center;padding:40px">
    <div style="font-family:'Inter',sans-serif;font-size:56px;font-weight:700;color:#F59E0B;letter-spacing:-0.04em;line-height:1">OFA</div>
    <div style="font-family:'JetBrains Mono',monospace;font-size:11px;color:#505A75;letter-spacing:0.2em;text-transform:uppercase;margin-top:8px">Options Flow Analyzer · NSE NIFTY</div>
    <div style="font-family:'Inter',sans-serif;font-size:14px;color:#505A75;max-width:440px;margin-top:20px;line-height:1.7">
        Institutional options flow monitor. Detects unusual OI buildup, volume spikes, and IV anomalies. AI-powered thesis generation.
    </div>
    <div style="display:flex;gap:12px;margin-top:32px">
        <div style="background:#1C2333;border:1px solid rgba(255,255,255,0.08);border-radius:10px;padding:14px 24px;font-size:12px;color:#8B95B0;font-family:'JetBrains Mono',monospace">⚡ Live Flow →</div>
        <div style="background:#1C2333;border:1px solid rgba(255,255,255,0.08);border-radius:10px;padding:14px 24px;font-size:12px;color:#8B95B0;font-family:'JetBrains Mono',monospace">🎯 Signals →</div>
        <div style="background:#1C2333;border:1px solid rgba(255,255,255,0.08);border-radius:10px;padding:14px 24px;font-size:12px;color:#8B95B0;font-family:'JetBrains Mono',monospace">📊 Analytics →</div>
    </div>
</div>""", unsafe_allow_html=True)