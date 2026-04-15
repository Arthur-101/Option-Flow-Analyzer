# ui/components.py — OFA Design System
import streamlit as st
import numpy as np
import math


def fmt_oi(val) -> str:
    try:
        if val is None: return "—"
        if isinstance(val, float) and math.isnan(val): return "—"
        val = int(val)
        if val == 0: return "—"
        if abs(val) >= 1_000_000: return f"{val/1_000_000:.2f}M"
        if abs(val) >= 1_000: return f"{val/1_000:.1f}K"
        return str(val)
    except: return "—"

def fmt_price(val) -> str:
    try:
        if val is None: return "—"
        if isinstance(val, float) and math.isnan(val): return "—"
        return f"₹{float(val):,.2f}"
    except: return "—"

def fmt_pct(val) -> str:
    try:
        if val is None: return "—"
        if isinstance(val, float) and math.isnan(val): return "—"
        return f"{float(val):.2f}%"
    except: return "—"

def fmt_oi_change(val) -> str:
    try:
        if val is None: return "—"
        if isinstance(val, float) and math.isnan(val): return "—"
        val = int(val)
        if val == 0: return "—"
        prefix = "+" if val > 0 else ""
        if abs(val) >= 1_000_000: return f"{prefix}{val/1_000_000:.2f}M"
        if abs(val) >= 1_000: return f"{prefix}{val/1_000:.1f}K"
        return f"{prefix}{val}"
    except: return "—"

def compute_rsi(prices: list, period: int = 14):
    if len(prices) < period + 1: return None
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0: return 100.0
    return round(100 - (100 / (1 + avg_gain / avg_loss)), 1)


def inject_global_css():
    st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

:root {
    --bg-base:#0F1117; --bg-surface:#161B27; --bg-elevated:#1C2333; --bg-hover:#222A3D;
    --border-subtle:rgba(255,255,255,0.06); --border-default:rgba(255,255,255,0.10); --border-strong:rgba(255,255,255,0.16);
    --text-primary:#F0F4FF; --text-secondary:#8B95B0; --text-tertiary:#505A75; --text-disabled:#353D55;
    --green:#10B981; --green-bg:rgba(16,185,129,0.10); --green-bd:rgba(16,185,129,0.25);
    --red:#F43F5E; --red-bg:rgba(244,63,94,0.10); --red-bd:rgba(244,63,94,0.25);
    --amber:#F59E0B; --amber-bg:rgba(245,158,11,0.10); --amber-bd:rgba(245,158,11,0.25);
    --blue:#3B82F6; --blue-bg:rgba(59,130,246,0.10); --blue-bd:rgba(59,130,246,0.25);
    --purple:#8B5CF6; --purple-bg:rgba(139,92,246,0.10); --purple-bd:rgba(139,92,246,0.25);
    --font-ui:'Inter',-apple-system,sans-serif; --font-data:'JetBrains Mono',monospace;
    --r-sm:4px; --r-md:8px; --r-lg:12px; --r-xl:16px;
}

.stApp { background:var(--bg-base) !important; }
.stApp > header { display:none !important; }
.stSidebar { background:var(--bg-surface) !important; border-right:1px solid var(--border-subtle) !important; }
.block-container { padding:0 !important; max-width:100% !important; }
#MainMenu,footer,.stDeployButton { display:none !important; }
html,body,[class*="css"] { font-family:var(--font-ui) !important; color:var(--text-primary) !important; }
::-webkit-scrollbar{width:4px;height:4px}::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:var(--border-default);border-radius:2px}

/* Metric card */
.mc { background:var(--bg-surface); border:1px solid var(--border-subtle); border-radius:var(--r-lg); padding:16px 20px; height:100%; transition:border-color 0.15s; }
.mc:hover { border-color:var(--border-default); }
.mc-label { font-size:10px; font-weight:600; letter-spacing:0.06em; text-transform:uppercase; color:var(--text-tertiary); margin-bottom:10px; }
.mc-value { font-size:24px; font-weight:700; color:var(--text-primary); line-height:1; font-family:var(--font-data); letter-spacing:-0.02em; }
.mc-value.green{color:var(--green)}.mc-value.red{color:var(--red)}.mc-value.amber{color:var(--amber)}.mc-value.blue{color:var(--blue)}
.mc-meta { font-size:11px; color:var(--text-tertiary); margin-top:6px; }
.mc-meta.up{color:var(--green)}.mc-meta.down{color:var(--red)}

/* Card */
.card { background:var(--bg-surface); border:1px solid var(--border-subtle); border-radius:var(--r-lg); overflow:hidden; }
.card-hd { display:flex; align-items:center; justify-content:space-between; padding:14px 20px; border-bottom:1px solid var(--border-subtle); }
.card-title { font-size:13px; font-weight:600; color:var(--text-primary); letter-spacing:-0.01em; }
.card-sub { font-size:11px; color:var(--text-tertiary); margin-top:1px; }
.card-body { padding:16px 20px; }

/* Section */
.sec-hd { display:flex; align-items:center; gap:10px; padding:20px 24px 12px; }
.sec-title { font-size:11px; font-weight:600; color:var(--text-tertiary); text-transform:uppercase; letter-spacing:0.08em; white-space:nowrap; }
.sec-line { flex:1; height:1px; background:var(--border-subtle); }

/* Badge */
.bdg { display:inline-flex; align-items:center; padding:2px 8px; border-radius:var(--r-sm); font-size:10px; font-weight:600; letter-spacing:0.05em; text-transform:uppercase; border:1px solid; white-space:nowrap; }
.bdg-green{background:var(--green-bg);color:var(--green);border-color:var(--green-bd)}
.bdg-red{background:var(--red-bg);color:var(--red);border-color:var(--red-bd)}
.bdg-amber{background:var(--amber-bg);color:var(--amber);border-color:var(--amber-bd)}
.bdg-blue{background:var(--blue-bg);color:var(--blue);border-color:var(--blue-bd)}
.bdg-purple{background:var(--purple-bg);color:var(--purple);border-color:var(--purple-bd)}
.bdg-neutral{background:rgba(255,255,255,0.05);color:var(--text-secondary);border-color:var(--border-default)}

/* Signal card */
.sig { background:var(--bg-surface); border:1px solid var(--border-subtle); border-radius:var(--r-lg); padding:16px 20px; margin-bottom:10px; transition:border-color 0.15s,background 0.15s; position:relative; overflow:hidden; }
.sig::before { content:''; position:absolute; left:0; top:0; bottom:0; width:3px; }
.sig.bull::before{background:var(--amber)}.sig.bear::before{background:var(--red)}.sig.neutral::before{background:var(--blue)}
.sig:hover { border-color:var(--border-default); background:var(--bg-elevated); }
.sig-hd { display:flex; align-items:center; gap:8px; flex-wrap:wrap; margin-bottom:12px; }
.sig-strike { font-size:16px; font-weight:700; color:var(--text-primary); font-family:var(--font-data); letter-spacing:-0.02em; }
.sig-exp { font-size:11px; color:var(--text-tertiary); font-family:var(--font-data); }
.sig-ts { margin-left:auto; font-size:11px; color:var(--text-tertiary); font-family:var(--font-data); }
.sig-stats { display:grid; grid-template-columns:repeat(6,1fr); background:var(--bg-elevated); border-radius:var(--r-md); border:1px solid var(--border-subtle); overflow:hidden; margin:10px 0; }
.sig-stat { padding:8px 12px; border-right:1px solid var(--border-subtle); }
.sig-stat:last-child{border-right:none}
.ss-label { font-size:9px; font-weight:600; letter-spacing:0.08em; text-transform:uppercase; color:var(--text-tertiary); margin-bottom:3px; }
.ss-val { font-size:12px; font-weight:600; color:var(--text-primary); font-family:var(--font-data); }
.ss-val.g{color:var(--green)}.ss-val.r{color:var(--red)}.ss-val.a{color:var(--amber)}
.sig-thesis { font-size:12px; line-height:1.65; color:var(--text-secondary); margin-top:10px; padding:12px 14px; background:var(--bg-elevated); border-radius:var(--r-md); border-left:2px solid var(--border-strong); }
.thesis-hd { display:flex; align-items:center; gap:8px; margin-bottom:6px; }
.thesis-lbl { font-size:9px; font-weight:600; letter-spacing:0.1em; text-transform:uppercase; color:var(--text-tertiary); }
.conf-pip { display:inline-block; width:6px; height:6px; border-radius:50%; margin-right:2px; }
.conf-pip.f{background:var(--amber)}.conf-pip.e{background:var(--border-default)}
.thesis-pending { font-size:11px; color:var(--text-disabled); margin-top:8px; font-style:italic; }

/* Chain table */
.chain-wrap { overflow-x:auto; }
table.chain { width:100%; border-collapse:collapse; font-family:var(--font-data); font-size:11px; }
table.chain thead tr { border-bottom:1px solid var(--border-default); }
table.chain th { padding:8px 10px; font-family:var(--font-ui); font-size:9px; font-weight:600; letter-spacing:0.08em; text-transform:uppercase; color:var(--text-tertiary); text-align:right; white-space:nowrap; }
table.chain th.ce-hd { color:var(--green); background:rgba(16,185,129,0.04); }
table.chain th.pe-hd { color:var(--red); background:rgba(244,63,94,0.04); }
table.chain th.str-hd { text-align:center; color:var(--text-secondary); background:var(--bg-elevated); }
table.chain tbody tr { border-bottom:1px solid var(--border-subtle); transition:background 0.1s; }
table.chain tbody tr:hover { background:var(--bg-hover); }
table.chain tbody tr:last-child { border-bottom:none; }
table.chain td { padding:6px 10px; text-align:right; color:var(--text-secondary); white-space:nowrap; }
table.chain td.ce { background:rgba(16,185,129,0.02); }
table.chain td.pe { background:rgba(244,63,94,0.02); }
table.chain td.str { text-align:center; font-weight:700; font-size:12px; color:var(--text-primary); background:var(--bg-elevated); }
table.chain td.str.atm { color:var(--amber); background:rgba(245,158,11,0.08); }
table.chain td.pos { color:var(--green); font-weight:600; }
table.chain td.neg { color:var(--red); font-weight:600; }
table.chain td.dim { color:var(--text-tertiary); }
table.chain td.hi { color:var(--text-primary); font-weight:600; }

/* Live dot */
.live { display:inline-flex; align-items:center; gap:6px; font-size:11px; color:var(--green); font-weight:500; }
.live-dot { width:7px; height:7px; background:var(--green); border-radius:50%; animation:lp 2s ease infinite; }
@keyframes lp{0%,100%{opacity:1}50%{opacity:0.4}}

/* Empty */
.empty { display:flex; flex-direction:column; align-items:center; justify-content:center; padding:56px 24px; text-align:center; }
.empty-t { font-size:13px; font-weight:600; color:var(--text-tertiary); margin-bottom:4px; }
.empty-s { font-size:11px; color:var(--text-disabled); font-family:var(--font-data); }

/* Page padding */
.page-pad { padding:24px; }
.page-hd { margin-bottom:24px; }
.page-title { font-size:22px; font-weight:700; color:var(--text-primary); letter-spacing:-0.03em; }
.page-sub { font-size:13px; color:var(--text-tertiary); margin-top:4px; }

/* Streamlit overrides */
.stSelectbox>div>div { background:var(--bg-elevated) !important; border:1px solid var(--border-default) !important; border-radius:var(--r-md) !important; color:var(--text-primary) !important; font-family:var(--font-ui) !important; font-size:13px !important; }
.stButton>button { background:var(--bg-elevated) !important; border:1px solid var(--border-default) !important; border-radius:var(--r-md) !important; color:var(--text-secondary) !important; font-family:var(--font-ui) !important; font-size:12px !important; font-weight:500 !important; transition:all 0.15s !important; }
.stButton>button:hover { background:var(--bg-hover) !important; border-color:var(--border-strong) !important; color:var(--text-primary) !important; }
.stCheckbox label { font-size:12px !important; color:var(--text-secondary) !important; }
.stTabs [data-baseweb="tab-list"] { background:var(--bg-elevated) !important; border-radius:var(--r-md) !important; padding:3px !important; border:1px solid var(--border-subtle) !important; gap:2px !important; }
.stTabs [data-baseweb="tab"] { font-family:var(--font-ui) !important; font-size:11px !important; font-weight:500 !important; color:var(--text-tertiary) !important; border-radius:6px !important; padding:6px 14px !important; background:transparent !important; }
.stTabs [aria-selected="true"] { background:var(--bg-surface) !important; color:var(--text-primary) !important; border:1px solid var(--border-default) !important; }
div[data-testid="stSidebarNav"] { display:none !important; }
[data-testid="stSidebarUserContent"] { padding:0 !important; }
</style>""", unsafe_allow_html=True)


def metric_card(label, value, meta="", meta_cls=""):
    m = f"<div class='mc-meta {meta_cls}'>{meta}</div>" if meta else ""
    st.markdown(f"<div class='mc'><div class='mc-label'>{label}</div><div class='mc-value'>{value}</div>{m}</div>", unsafe_allow_html=True)

def metric_card_c(label, value, color="", meta="", meta_cls=""):
    vc = f"mc-value {color}" if color else "mc-value"
    m = f"<div class='mc-meta {meta_cls}'>{meta}</div>" if meta else ""
    st.markdown(f"<div class='mc'><div class='mc-label'>{label}</div><div class='{vc}'>{value}</div>{m}</div>", unsafe_allow_html=True)

def section_header(title):
    st.markdown(f"<div class='sec-hd'><span class='sec-title'>{title}</span><div class='sec-line'></div></div>", unsafe_allow_html=True)

def bdg(text, color="neutral"):
    return f'<span class="bdg bdg-{color}">{text}</span>'

def sig_type_badge(t):
    m = {"OI_BUILDUP":("green","OI Buildup"),"OI_UNWIND":("red","OI Unwind"),"VOLUME_SPIKE":("blue","Vol Spike"),"IV_SPIKE":("purple","IV Spike")}
    c, l = m.get(t, ("neutral", t))
    return bdg(l, c)

def bias_bdg(b):
    m = {"BULLISH":"amber","BEARISH":"red","NEUTRAL":"blue"}
    return bdg(b, m.get(b,"neutral"))

def conf_pips(conf):
    try: conf = int(conf) if conf else 0
    except: conf = 0
    return "".join(f'<span class="conf-pip {"f" if i<conf else "e"}"></span>' for i in range(5))

def empty_state(title, sub=""):
    st.markdown(f"<div class='empty'><div class='empty-t'>{title}</div>{'<div class=\"empty-s\">' + sub + '</div>' if sub else ''}</div>", unsafe_allow_html=True)

def live_dot(text="Live"):
    st.markdown(f"<div class='live'><div class='live-dot'></div>{text}</div>", unsafe_allow_html=True)