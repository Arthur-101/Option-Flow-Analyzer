# api_service.py — Data query & calculation service for OFA React Terminal
import os
import sqlite3
import math
import numpy as np
import pandas as pd
from datetime import datetime, date, timezone, timedelta
from typing import Optional, List, Dict, Any
from config import DB_PATH

HISTORICAL_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "options_flow_historical_apr2026.db")

def get_conn() -> sqlite3.Connection:
    # Use DB_PATH if exists, else fallback to HISTORICAL_DB_PATH
    path = DB_PATH if os.path.exists(DB_PATH) else HISTORICAL_DB_PATH
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn

def ist_time_str(ts_str: str) -> str:
    """Converts a UTC or naive timestamp string into IST HH:MM string."""
    if not ts_str:
        return "--:--"
    try:
        dt = datetime.strptime(ts_str[:19], "%Y-%m-%d %H:%M:%S")
        # Assuming database timestamp is stored in UTC
        dt_ist = dt + timedelta(hours=5, minutes=30)
        return dt_ist.strftime("%H:%M")
    except Exception:
        return ts_str[11:16] if len(ts_str) >= 16 else ts_str

def get_latest_session_date(symbol: str = "NIFTY") -> str:
    conn = get_conn()
    r = conn.execute("SELECT MAX(DATE(timestamp)) as dt FROM options_chain WHERE symbol = ?", (symbol,)).fetchone()
    conn.close()
    return r["dt"] if r and r["dt"] else date.today().isoformat()

# ── Supabase Cloud Client ──────────────────────────────────────────────────────
import logging
from pathlib import Path
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")
load_dotenv()
logger = logging.getLogger(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
_sb_client: Optional[Client] = None

def get_supabase_client() -> Optional[Client]:
    global _sb_client
    if _sb_client is None and SUPABASE_URL and SUPABASE_KEY:
        try:
            _sb_client = create_client(SUPABASE_URL, SUPABASE_KEY)
        except Exception as e:
            logger.warning("Supabase client init failed in api_service: %s", e)
    return _sb_client


def _get_active_expiry_supabase(sb: Client, symbol: str, timestamp: str) -> Optional[str]:
    """Find the nearest active weekly expiry for a given snapshot timestamp."""
    try:
        res = (
            sb.table("options_chain")
            .select("expiry")
            .eq("symbol", symbol)
            .eq("timestamp", timestamp)
            .limit(50)
            .execute()
        )
        if not res.data:
            return None
        expiries = sorted(list({r["expiry"] for r in res.data if r.get("expiry")}))
        snap_date = timestamp[:10]
        active = [e for e in expiries if e >= snap_date]
        return active[0] if active else (expiries[0] if expiries else None)
    except Exception:
        return None



def _get_ribbon_from_supabase(symbol: str = "NIFTY") -> Optional[Dict[str, Any]]:
    sb = get_supabase_client()
    if not sb:
        return None
    try:
        res = sb.table("market_context").select("*").eq("symbol", symbol).order("timestamp", desc=True).limit(1).execute()
        if not res.data:
            return None
        mc = res.data[0]

        # Recent spot entries for sparkline (last 20 entries)
        history_res = sb.table("market_context").select("spot_price,timestamp").eq("symbol", symbol).order("timestamp", desc=True).limit(20).execute()
        hist_rows = history_res.data or []
        hist_rows.reverse()
        spots = [float(r["spot_price"]) for r in hist_rows if r.get("spot_price")]

        current_spot = float(mc["spot_price"])
        open_spot = spots[0] if spots else current_spot
        day_high = max(spots) if spots else current_spot
        day_low = min(spots) if spots else current_spot
        change_pts = current_spot - open_spot
        change_pct = (change_pts / open_spot * 100) if open_spot else 0.0

        if len(spots) > 16:
            indices = np.linspace(0, len(spots) - 1, 16, dtype=int)
            sparkline = [round(spots[i], 2) for i in indices]
        else:
            sparkline = [round(s, 2) for s in spots] if spots else [current_spot] * 10

        latest_ts = mc["timestamp"]
        try:
            dt = datetime.fromisoformat(latest_ts.replace("Z", "+00:00"))
            dt_ist = dt + timedelta(hours=5, minutes=30)
            latest_exact = dt_ist.strftime("%H:%M:%S IST")
            latest_ist = dt_ist.strftime("%H:%M")
        except Exception:
            latest_exact = latest_ts[11:19] + " IST"
            latest_ist = latest_ts[11:16]

        session_date = latest_ts[:10]
        available_expiries = []
        try:
            # market_context and options_chain timestamps differ by seconds, so match the chain's own latest snapshot.
            chain_ts_res = (
                sb.table("options_chain").select("timestamp").eq("symbol", symbol)
                .order("timestamp", desc=True).limit(1).execute()
            )
            chain_ts = chain_ts_res.data[0]["timestamp"] if chain_ts_res.data else None
            exp_res = (
                sb.table("options_chain")
                .select("expiry")
                .eq("symbol", symbol)
                .eq("timestamp", chain_ts)
                .order("expiry", desc=False)
                .limit(400)
                .execute()
            )
            raw_exps = sorted(set(r["expiry"] for r in (exp_res.data or []) if r.get("expiry")))[:4]
            sess_d = datetime.strptime(session_date, "%Y-%m-%d").date()
            for exp_s in raw_exps:
                exp_d = datetime.strptime(exp_s, "%Y-%m-%d").date()
                dte = (exp_d - sess_d).days
                available_expiries.append({
                    "expiry": exp_s,
                    "label": f"{exp_d.strftime('%d %b')} · {'expired' if dte < 0 else f'{dte}d'}",
                    "dte": dte,
                })
        except Exception as e:
            logger.warning("Error fetching dynamic expiries from Supabase: %s", e)

        from holidays import is_market_holiday
        is_hol, _ = is_market_holiday()
        now_utc = datetime.now(timezone.utc)
        now_ist = now_utc + timedelta(hours=5, minutes=30)
        market_open = (not is_hol) and (now_ist.weekday() < 5) and (
            (now_ist.hour > 9 or (now_ist.hour == 9 and now_ist.minute >= 15)) and
            (now_ist.hour < 15 or (now_ist.hour == 15 and now_ist.minute <= 30))
        )

        try:
            dt_utc = datetime.fromisoformat(latest_ts.replace("Z", "+00:00"))
            is_live = (now_utc - dt_utc).total_seconds() < 900
        except Exception:
            is_live = False

        return {
            "spot": round(current_spot, 2),
            "change_pts": round(change_pts, 2),
            "change_pct": round(change_pct, 2),
            "day_high": round(day_high, 2),
            "day_low": round(day_low, 2),
            "vix": float(mc["vix"]) if mc.get("vix") is not None else None,
            "vix_change": float(mc["vix_change"]) if mc.get("vix_change") is not None else None,
            "sparkline": sparkline,
            "pcr": float(mc["pcr"]) if mc.get("pcr") is not None else None,
            "pcr_state": mc.get("pcr_state") or "Neutral",
            "vwap": float(mc["vwap"]) if mc.get("vwap") is not None else None,
            "rsi": float(mc["rsi"]) if mc.get("rsi") is not None else None,
            "max_pain": float(mc["max_pain"]) if mc.get("max_pain") is not None else None,
            "put_wall": float(mc["put_wall"]) if mc.get("put_wall") is not None else None,
            "call_wall": float(mc["call_wall"]) if mc.get("call_wall") is not None else None,
            "available_expiries": available_expiries,
            "selected_expiry": available_expiries[0]["label"] if available_expiries else "",
            "market_open": market_open,
            "is_live": is_live,
            "session_date": latest_ts[:10],
            "latest_timestamp": latest_ts,
            "latest_ist": latest_ist,
            "latest_exact_ist": latest_exact,
            "ai_stance": mc.get("ai_stance") or "",
            "source": "supabase_market_context",
        }
    except Exception as e:
        logger.warning("Error fetching market_context from Supabase: %s", e)
        return None


# ── 1. Top Ribbon Metrics ──────────────────────────────────────────────────────
def get_ribbon_data(symbol: str = "NIFTY", session_date: Optional[str] = None) -> Dict[str, Any]:
    # Check Supabase first for real-time cloud snapshot if in live mode
    if not session_date:
        cloud_ribbon = _get_ribbon_from_supabase(symbol)
        if cloud_ribbon:
            return cloud_ribbon
        session_date = get_latest_session_date(symbol)
    
    conn = get_conn()
    
    # 1. Spot stats
    spot_rows = conn.execute("""
        SELECT spot_price, timestamp
        FROM options_chain
        WHERE symbol = ? AND DATE(timestamp) = ? AND spot_price IS NOT NULL AND spot_price > 0
        ORDER BY timestamp ASC
    """, (symbol, session_date)).fetchall()
    
    if not spot_rows:
        # Fallback to absolute latest spot regardless of date
        spot_rows = conn.execute("""
            SELECT spot_price, timestamp
            FROM options_chain
            WHERE symbol = ? AND spot_price IS NOT NULL AND spot_price > 0
            ORDER BY timestamp DESC LIMIT 30
        """, (symbol,)).fetchall()
        spot_rows = spot_rows[::-1]

    spots = [r["spot_price"] for r in spot_rows]
    timestamps = [r["timestamp"] for r in spot_rows]
    
    current_spot = spots[-1] if spots else 0.0
    open_spot = spots[0] if spots else current_spot
    day_high = max(spots) if spots else current_spot
    day_low = min(spots) if spots else current_spot
    change_pts = current_spot - open_spot
    change_pct = (change_pts / open_spot * 100) if open_spot else 0.0

    # 2. Latest flush timestamp for chain aggregations
    latest_ts_row = conn.execute("""
        SELECT MAX(timestamp) as ts FROM options_chain WHERE symbol = ? AND DATE(timestamp) = ?
    """, (symbol, session_date)).fetchone()
    latest_ts = latest_ts_row["ts"] if latest_ts_row and latest_ts_row["ts"] else None

    # 3. PCR, Put Wall, Call Wall, Max Pain (filtered strictly to nearest weekly expiry)
    chain_rows = []
    if latest_ts:
        exp_row = conn.execute("""
            SELECT expiry FROM options_chain
            WHERE symbol = ? AND timestamp = ? AND expiry IS NOT NULL AND expiry != ''
            ORDER BY expiry ASC LIMIT 1
        """, (symbol, latest_ts)).fetchone()
        near_exp = exp_row["expiry"] if exp_row else None

        if near_exp:
            chain_rows = conn.execute("""
                SELECT strike, option_type, oi, volume, iv, last_price
                FROM options_chain
                WHERE symbol = ? AND timestamp = ? AND expiry = ?
            """, (symbol, latest_ts, near_exp)).fetchall()
        else:
            chain_rows = conn.execute("""
                SELECT strike, option_type, oi, volume, iv, last_price
                FROM options_chain
                WHERE symbol = ? AND timestamp = ?
            """, (symbol, latest_ts)).fetchall()
    
    total_ce_oi = 0
    total_pe_oi = 0
    ce_strikes: Dict[float, int] = {}
    pe_strikes: Dict[float, int] = {}
    all_strikes = set()

    for r in chain_rows:
        k = float(r["strike"])
        oi = int(r["oi"] or 0)
        all_strikes.add(k)
        if r["option_type"] == "CE":
            total_ce_oi += oi
            ce_strikes[k] = ce_strikes.get(k, 0) + oi
        else:
            total_pe_oi += oi
            pe_strikes[k] = pe_strikes.get(k, 0) + oi

    pcr = round(total_pe_oi / total_ce_oi, 2) if total_ce_oi > 0 else 1.0
    pcr_state = "Bullish" if pcr < 0.75 else ("Bearish" if pcr > 1.25 else "Neutral")

    # Walls
    call_wall = max(ce_strikes.items(), key=lambda x: x[1])[0] if ce_strikes else (round(current_spot / 100) * 100 + 200)
    put_wall = max(pe_strikes.items(), key=lambda x: x[1])[0] if pe_strikes else (round(current_spot / 100) * 100 - 200)

    # Max Pain calculation: strike that minimizes total intrinsic payoff to buyers
    sorted_strikes = sorted(list(all_strikes))
    max_pain = round(current_spot / 100) * 100
    if sorted_strikes:
        min_loss = float("inf")
        for s in sorted_strikes:
            loss = 0.0
            for k, ce_oi in ce_strikes.items():
                if s > k:
                    loss += (s - k) * ce_oi
            for k, pe_oi in pe_strikes.items():
                if s < k:
                    loss += (k - s) * pe_oi
            if loss < min_loss:
                min_loss = loss
                max_pain = s

    # Session VWAP
    vwap = round(float(np.mean(spots)), 2) if spots else current_spot

    # RSI (14)
    rsi = None
    if len(spots) >= 5:
        deltas = np.diff(spots)
        gains = np.maximum(deltas, 0)
        losses = np.maximum(-deltas, 0)
        avg_gain = np.mean(gains[-14:]) if len(gains) >= 14 else np.mean(gains)
        avg_loss = np.mean(losses[-14:]) if len(losses) >= 14 else np.mean(losses)
        if avg_loss == 0:
            rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = round(100.0 - (100.0 / (1.0 + rs)), 1)

    # India VIX (from ATM IV or fallback baseline)
    atm_k = round(current_spot / 100) * 100
    atm_ivs = [float(r["iv"]) for r in chain_rows if r["iv"] and abs(float(r["strike"]) - atm_k) <= 150]
    vix = round(float(np.mean(atm_ivs)), 2) if atm_ivs else None
    vix_change = None

    # Downsample spots to 16 points for mini intraday sparkline
    if len(spots) > 16:
        indices = np.linspace(0, len(spots) - 1, 16, dtype=int)
        sparkline = [round(spots[i], 2) for i in indices]
    else:
        sparkline = [round(s, 2) for s in spots]

    # Expiries with DTE
    exp_rows = conn.execute("""
        SELECT DISTINCT expiry FROM options_chain
        WHERE symbol = ? AND expiry IS NOT NULL AND expiry != ''
        ORDER BY expiry ASC LIMIT 4
    """, (symbol,)).fetchall()

    available_expiries = []
    for er in exp_rows:
        exp_str = er["expiry"]
        try:
            exp_dt = datetime.strptime(exp_str, "%Y-%m-%d").date()
            sess_dt = datetime.strptime(session_date, "%Y-%m-%d").date()
            dte = max(0, (exp_dt - sess_dt).days)
            label = f"{exp_dt.strftime('%d %b')} · {dte}d"
        except Exception:
            continue
        available_expiries.append({"expiry": exp_str, "label": label, "dte": dte})

    # Latest exact IST time with seconds
    latest_exact = ""
    if latest_ts:
        try:
            dt = datetime.strptime(latest_ts[:19], "%Y-%m-%d %H:%M:%S")
            dt_ist = dt + timedelta(hours=5, minutes=30)
            latest_exact = dt_ist.strftime("%H:%M:%S IST")
        except:
            latest_exact = latest_ts[11:19] + " IST"

    # AI Stance for sidebar mini chip (aligns with latest thesis)
    sig_row = conn.execute("""
        SELECT llm_bias, bias, llm_confidence, signal_strength
        FROM signals
        WHERE symbol = ? AND llm_thesis IS NOT NULL AND llm_thesis != ''
        ORDER BY fired_at DESC LIMIT 1
    """, (symbol,)).fetchone()
    if not sig_row:
        sig_row = conn.execute("SELECT bias, llm_confidence, signal_strength FROM signals WHERE symbol = ? ORDER BY fired_at DESC LIMIT 1", (symbol,)).fetchone()

    if sig_row:
        raw_b = (sig_row["llm_bias"] if "llm_bias" in sig_row.keys() and sig_row["llm_bias"] else sig_row["bias"]) or ""
        bias_label = raw_b.capitalize()
        conf_val = sig_row["llm_confidence"]
        str_val = sig_row["signal_strength"]
        score_val = int(min(95, max(35, round(conf_val * 12 + str_val * 4 + 7)))) if (conf_val and str_val) else None
        ai_stance = {
            "bias": bias_label,
            "score": score_val,
            "label": f"{bias_label} · {score_val}" if score_val is not None else bias_label,
        }
    else:
        ai_stance = {"bias": "", "score": None, "label": ""}

    # Check if market is open (9:15 - 15:30 IST Mon-Fri)
    now_utc = datetime.now(timezone.utc)
    now_ist = now_utc + timedelta(hours=5, minutes=30)
    is_weekday = now_ist.weekday() < 5
    market_open = is_weekday and (9 * 60 + 15 <= now_ist.hour * 60 + now_ist.minute <= 15 * 60 + 30)

    # Check if data is live (updated in last 15 min and today's date)
    is_live = False
    if latest_ts:
        try:
            ts_dt = datetime.strptime(latest_ts[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            is_live = (now_utc - ts_dt).total_seconds() < 900
        except:
            is_live = False

    conn.close()

    return {
        "spot": round(current_spot, 2),
        "change_pts": round(change_pts, 2),
        "change_pct": round(change_pct, 2),
        "day_high": round(day_high, 2),
        "day_low": round(day_low, 2),
        "vix": vix,
        "vix_change": vix_change,
        "sparkline": sparkline,
        "pcr": pcr,
        "pcr_state": pcr_state,
        "vwap": vwap,
        "rsi": rsi,
        "max_pain": max_pain,
        "put_wall": put_wall,
        "call_wall": call_wall,
        "available_expiries": available_expiries,
        "selected_expiry": available_expiries[0]["label"] if available_expiries else "",
        "market_open": market_open,
        "is_live": is_live,
        "session_date": session_date,
        "latest_timestamp": latest_ts or timestamps[-1] if timestamps else None,
        "latest_ist": ist_time_str(latest_ts or timestamps[-1] if timestamps else None),
        "latest_exact_ist": latest_exact,
        "ai_stance": ai_stance,
    }

# ── helpers: live-series accessors for the thesis page ───────────────────────
def _mc_session_series(sb: Client, symbol: str, session_date: str) -> List[Dict[str, Any]]:
    """market_context rows for one session, oldest first (one row per 5-min snapshot)."""
    try:
        return (
            sb.table("market_context")
            .select("timestamp,spot_price,vix,vix_change,pcr,pcr_state,vwap,rsi,macd_hist,max_pain,put_wall,call_wall")
            .eq("symbol", symbol)
            .gte("timestamp", f"{session_date}T00:00:00")
            .lte("timestamp", f"{session_date}T23:59:59")
            .order("timestamp")
            .limit(1000)
            .execute()
            .data or []
        )
    except Exception as e:
        logger.warning("market_context series failed: %s", e)
        return []


def _sample_rows(rows: List[Dict[str, Any]], n: int = 24) -> List[Dict[str, Any]]:
    if len(rows) <= n:
        return rows
    idx = np.linspace(0, len(rows) - 1, n).astype(int)
    return [rows[i] for i in idx]


def _num(row: Dict[str, Any], key: str, default: float = 0.0) -> float:
    v = row.get(key) if row else None
    return float(v) if v is not None else default


def _age_label(ts: Optional[str], market_open: bool) -> str:
    """Real age of the latest stored snapshot — never an invented cadence."""
    if not ts:
        return ""
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        secs = (datetime.now(timezone.utc) - dt).total_seconds()
    except Exception:
        return ""
    if secs < 120:
        age = "Updated just now"
    elif secs < 3600:
        age = f"Updated {int(secs // 60)}m ago"
    elif secs < 86400:
        age = f"Updated {int(secs // 3600)}h ago"
    else:
        age = f"Updated {int(secs // 86400)}d ago"
    return age + ("" if market_open else " · market closed")


def _lakh(v: float) -> str:
    return f"{v / 100000:+.2f}L"


# ── 2. AI Verdict Hero ────────────────────────────────────────────────────────
def get_latest_thesis(symbol: str = "NIFTY") -> Dict[str, Any]:
    sb = get_supabase_client()
    sig: Optional[Dict[str, Any]] = None
    news: List[Dict[str, Any]] = []

    if sb:
        try:
            res = (
                sb.table("signals").select("*").eq("symbol", symbol)
                .not_.is_("llm_thesis", "null").neq("llm_thesis", "")
                .order("fired_at", desc=True).limit(1).execute()
            )
            if res.data:
                sig = res.data[0]
            news_res = (
                sb.table("news_raw").select("headline,source,published_at")
                .order("fetched_at", desc=True).limit(3).execute()
            )
            news = [
                {
                    "headline": r["headline"],
                    "time": ist_time_str(r.get("published_at") or ""),
                    "source": r.get("source") or "",
                }
                for r in (news_res.data or [])
                if r.get("headline")
            ]
        except Exception as e:
            logger.warning("Supabase thesis fetch failed: %s", e)

    ribbon = get_ribbon_data(symbol)
    market_open = bool(ribbon.get("market_open"))
    session_date = ribbon.get("session_date") or date.today().isoformat()
    session = _mc_session_series(sb, symbol, session_date) if sb else []
    latest = session[-1] if session else {}

    spot_val = _num(latest, "spot_price", float(ribbon.get("spot") or 0))
    vwap = _num(latest, "vwap", float(ribbon.get("vwap") or 0))
    pcr = _num(latest, "pcr", float(ribbon.get("pcr") or 0))
    pcr_state = latest.get("pcr_state") or ribbon.get("pcr_state") or "Neutral"
    rsi = _num(latest, "rsi", float(ribbon.get("rsi") or 0))
    macd_raw = latest.get("macd_hist")
    macd = float(macd_raw) if macd_raw is not None else None
    vix = _num(latest, "vix", float(ribbon.get("vix") or 0))
    vix_change = _num(latest, "vix_change", float(ribbon.get("vix_change") or 0))
    put_wall = _num(latest, "put_wall", float(ribbon.get("put_wall") or 0))
    call_wall = _num(latest, "call_wall", float(ribbon.get("call_wall") or 0))
    max_pain = _num(latest, "max_pain", float(ribbon.get("max_pain") or 0))
    day_high = float(ribbon.get("day_high") or spot_val)
    day_low = float(ribbon.get("day_low") or spot_val)

    # ── latest chain snapshot: real OI per strike, and ΔOI vs the prior snapshot
    ce_oi_total = pe_oi_total = 0
    strike_ce: Dict[float, int] = {}
    strike_pe: Dict[float, int] = {}
    ce_delta: Optional[int] = None
    pe_delta: Optional[int] = None
    chain_ts: Optional[str] = None
    if sb:
        try:
            last = (
                sb.table("options_chain").select("timestamp").eq("symbol", symbol)
                .order("timestamp", desc=True).limit(1).execute()
            )
            if last.data:
                chain_ts = last.data[0]["timestamp"]
                exp = _get_active_expiry_supabase(sb, symbol, chain_ts)
                q = (
                    sb.table("options_chain").select("strike,option_type,oi")
                    .eq("symbol", symbol).eq("timestamp", chain_ts)
                )
                if exp:
                    q = q.eq("expiry", exp)
                for r in q.execute().data or []:
                    k = float(r["strike"])
                    oi = int(r["oi"] or 0)
                    if r["option_type"] == "CE":
                        strike_ce[k] = strike_ce.get(k, 0) + oi
                        ce_oi_total += oi
                    else:
                        strike_pe[k] = strike_pe.get(k, 0) + oi
                        pe_oi_total += oi
                prev = (
                    sb.table("options_chain").select("timestamp").eq("symbol", symbol)
                    .lt("timestamp", chain_ts).order("timestamp", desc=True).limit(1).execute()
                )
                if prev.data and exp:
                    prev_ts = prev.data[0]["timestamp"]
                    # ΔOI is only meaningful between adjacent flushes inside one session.
                    try:
                        gap = (datetime.fromisoformat(chain_ts) - datetime.fromisoformat(prev_ts)).total_seconds()
                    except Exception:
                        gap = 1e9
                    if prev_ts[:10] == chain_ts[:10] and 0 < gap <= 900:
                        prev_rows = (
                            sb.table("options_chain").select("option_type,oi")
                            .eq("symbol", symbol).eq("timestamp", prev_ts)
                            .eq("expiry", exp).execute().data or []
                        )
                        if prev_rows:
                            ce_prev = sum(int(r["oi"] or 0) for r in prev_rows if r["option_type"] == "CE")
                            pe_prev = sum(int(r["oi"] or 0) for r in prev_rows if r["option_type"] == "PE")
                            ce_delta = ce_oi_total - ce_prev
                            pe_delta = pe_oi_total - pe_prev
        except Exception as e:
            logger.warning("thesis chain snapshot failed: %s", e)

    strikes_near_spot = []
    if strike_ce or strike_pe:
        atm_k = round(spot_val / 50) * 50
        near = sorted(set(strike_ce) | set(strike_pe), key=lambda k: abs(k - atm_k))[:17]
        strikes_near_spot = [
            {
                "strike": int(k),
                "ce_oi": round(strike_ce.get(k, 0) / 100000, 2),
                "pe_oi": round(strike_pe.get(k, 0) / 100000, 2),
                "is_atm": k == atm_k,
            }
            for k in sorted(near)
        ]

    sampled = _sample_rows(session, 24)

    def series(key: str, field: str, nd: int = 2) -> List[Dict[str, Any]]:
        out = []
        for r in sampled:
            v = r.get(key)
            if v is None:
                continue
            out.append({"time": ist_time_str(r["timestamp"]), field: round(float(v), nd)})
        return out

    def spark(key: str, nd: int = 2) -> List[float]:
        vals = [float(r[key]) for r in session if r.get(key) is not None]
        return [round(v, nd) for v in vals[-8:]]

    def delta_30m(key: str, nd: int = 2) -> str:
        if len(session) < 7:
            return ""
        a, b = session[-7].get(key), session[-1].get(key)
        if a is None or b is None:
            return ""
        return f"{float(b) - float(a):+.{nd}f} vs 30m ago"

    flow_charts = {
        "price_series": series("spot_price", "spot"),
        "pcr_series": series("pcr", "pcr", 3),
        "macd_series": series("macd_hist", "macd", 3),
        "vix_series": series("vix", "vix"),
        "strikes_near_spot": strikes_near_spot,
        "vwap": round(vwap, 2),
    }

    # ── 4 pulse cards, each backed by a real series/column
    vix_vals = [float(r["vix"]) for r in session if r.get("vix") is not None]
    if vix_vals and max(vix_vals) > min(vix_vals):
        vix_pct = int(round((vix - min(vix_vals)) / (max(vix_vals) - min(vix_vals)) * 100))
    else:
        vix_pct = 0
    ce_share = int(round(ce_oi_total / (ce_oi_total + pe_oi_total) * 100)) if (ce_oi_total + pe_oi_total) else 0

    market_pulse = {
        "pcr": {
            "title": "Put / Call Ratio",
            "value": f"{pcr:.2f}" if pcr else "—",
            "sub": (
                f"{pcr_state} · PE {pe_oi_total / 100000:.1f}L vs CE {ce_oi_total / 100000:.1f}L"
                if (ce_oi_total or pe_oi_total) else pcr_state
            ),
            "delta_30m": delta_30m("pcr", 3),
            "sparkline": spark("pcr", 3),
            "bias": "bullish" if pcr and pcr < 0.75 else ("bearish" if pcr > 1.25 else "neutral"),
            "pct": int(min(100, max(0, pcr / 1.5 * 100))) if pcr else 0,
        },
        "net_oi_delta": {
            "title": "Net ΔOI (last snapshot)",
            "value": f"{_lakh(ce_delta)} CE" if ce_delta is not None else "—",
            "sub": (
                f"PE {_lakh(pe_delta)} · net {_lakh(ce_delta - pe_delta)}"
                if ce_delta is not None and pe_delta is not None else "No prior snapshot"
            ),
            "delta_30m": "",
            "sparkline": [],
            "bias": "bullish" if (ce_delta or 0) > (pe_delta or 0) else "bearish",
            "pct": ce_share,
            "counts": {"ce_oi": ce_oi_total, "pe_oi": pe_oi_total},
        },
        "rsi": {
            "title": "RSI (14)",
            "value": f"{rsi:.1f}" if rsi else "—",
            "sub": (
                ("Overbought" if rsi >= 70 else "Oversold" if rsi <= 30 else "Neutral")
                + (f" · MACD {macd:+.2f}" if macd is not None else "")
            ),
            "delta_30m": delta_30m("rsi", 1),
            "sparkline": spark("rsi", 1),
            "bias": "bearish" if rsi >= 70 else ("bullish" if rsi <= 30 else "neutral"),
            "pct": int(min(100, max(0, rsi))) if rsi else 0,
        },
        "vix": {
            "title": "India VIX",
            "value": f"{vix:.2f}" if vix else "—",
            "sub": f"{vix_change:+.2f} vs prev close" if vix else "",
            "delta_30m": delta_30m("vix", 2),
            "sparkline": spark("vix", 2),
            "bias": "bearish" if vix_change > 0 else "bullish",
            "pct": vix_pct,
            "percentile": vix_pct,
        },
    }

    chips = [
        {"label": "PCR", "value": f"{pcr:.2f}" if pcr else "—",
         "bias": "bullish" if pcr and pcr < 0.75 else ("bearish" if pcr > 1.25 else "neutral")},
        {"label": "RSI (14)", "value": f"{rsi:.1f}" if rsi else "—",
         "bias": "bearish" if rsi >= 70 else ("bullish" if rsi <= 30 else "neutral")},
        {"label": "MACD hist", "value": f"{macd:+.2f}" if macd is not None else "—",
         "bias": "bullish" if (macd or 0) > 0 else ("bearish" if (macd or 0) < 0 else "neutral")},
        {"label": "VWAP", "value": f"{vwap:,.0f}" if vwap else "—",
         "bias": "bullish" if vwap and spot_val >= vwap else "bearish"},
        {"label": "Put wall", "value": f"{put_wall:,.0f}" if put_wall else "—", "bias": "bullish"},
        {"label": "Call wall", "value": f"{call_wall:,.0f}" if call_wall else "—", "bias": "bearish"},
    ]

    meta_updated = _age_label(ribbon.get("latest_timestamp") or chain_ts, market_open)
    # The chain series can lag the tape; say so instead of implying a live chain.
    if exp and chain_ts and exp < chain_ts[:10]:
        meta_updated += " · chain series expired"

    if not sig:
        return {
            "verdict": "NEUTRAL",
            "stars": "",
            "confidence": None,
            "conviction_pct": 0,
            "signal_strength": None,
            "signals_today": 0,
            "spot": round(spot_val, 2),
            "target": round(max(call_wall, day_high, spot_val), 2),
            "invalidation": round(min([v for v in (put_wall, day_low) if v > 0] or [spot_val]), 2),
            "vwap": round(vwap, 2),
            "sparkline": ribbon.get("sparkline", []),
            "thesis_history": [],
            "flip_summary": "",
            "meta_updated": meta_updated,
            "thesis_date": None,
            "summary": "",
            "thesis": "",
            "supports": [],
            "contradicts": [],
            "change_mind": "",
            "chips": chips,
            "market_pulse": market_pulse,
            "flow_charts": flow_charts,
            "news": news,
            "updated_at": "",
            "data_status": "no_thesis",
        }

    sig_date = sig["fired_at"][:10]
    bias = (sig.get("llm_bias") or sig.get("bias") or "NEUTRAL").upper()

    # ── the thesis day's own signal cycle (real rows, not a scripted narrative)
    day_signals: List[Dict[str, Any]] = []
    if sb:
        try:
            day_signals = (
                sb.table("signals").select("fired_at,bias,llm_bias,signal_strength")
                .eq("symbol", symbol)
                .gte("fired_at", f"{sig_date}T00:00:00")
                .lte("fired_at", f"{sig_date}T23:59:59")
                .order("fired_at").limit(200).execute().data or []
            )
        except Exception as e:
            logger.warning("thesis day signals failed: %s", e)

    thesis_history = [
        {
            "time": ist_time_str(r["fired_at"]),
            "bias": (r.get("llm_bias") or r.get("bias") or "NEUTRAL").upper(),
            "conviction": int(round(float(r.get("signal_strength") or 0) * 10)),
        }
        for r in _sample_rows(day_signals, 12)
    ]
    flip_summary = ""
    if len(thesis_history) >= 2:
        flips = [i for i in range(1, len(thesis_history))
                 if thesis_history[i]["bias"] != thesis_history[i - 1]["bias"]]
        if flips:
            i = flips[-1]
            flip_summary = (
                f"Flipped {thesis_history[i - 1]['bias']} → {thesis_history[i]['bias']} "
                f"at {thesis_history[i]['time']} · {len(thesis_history) - i} signals since"
            )
        else:
            flip_summary = (
                f"Stable {thesis_history[-1]['bias']} across {len(thesis_history)} signals "
                f"since {thesis_history[0]['time']}"
            )

    # ── supports/contradicts are measured facts, sorted by which side of the call they sit on
    facts: List[tuple] = []
    if pcr:
        facts.append(("BULLISH" if pcr < 0.75 else "BEARISH" if pcr > 1.25 else "NEUTRAL",
                      f"PCR {pcr:.2f} ({pcr_state})"))
    if vwap:
        facts.append(("BULLISH" if spot_val >= vwap else "BEARISH",
                      f"Spot {spot_val:,.0f} {'above' if spot_val >= vwap else 'below'} session VWAP {vwap:,.0f}"))
    if macd is not None:
        facts.append(("BULLISH" if macd > 0 else "BEARISH", f"MACD histogram {macd:+.2f}"))
    if rsi:
        facts.append(("BEARISH" if rsi >= 70 else "BULLISH" if rsi <= 30 else "NEUTRAL",
                      f"RSI (14) {rsi:.1f}"))
    if call_wall and spot_val:
        facts.append(("BEARISH",
                      f"Call OI wall {call_wall:,.0f} ({(call_wall - spot_val) / spot_val * 100:+.2f}% from spot)"))
    if put_wall and spot_val:
        facts.append(("BULLISH",
                      f"Put OI wall {put_wall:,.0f} ({(put_wall - spot_val) / spot_val * 100:+.2f}% from spot)"))
    # A NEUTRAL verdict has nothing to contradict, so every reading lands on the support side.
    supports = [t for a, t in facts if bias == "NEUTRAL" or a == bias][:4]
    contradicts = [] if bias == "NEUTRAL" else [t for a, t in facts if a != bias and a != "NEUTRAL"][:4]

    resistance = call_wall if call_wall > spot_val else max(day_high, spot_val)
    support = put_wall if 0 < put_wall < spot_val else min(day_low, spot_val)
    if bias == "BEARISH":
        target, invalidation = support, resistance
    else:
        target, invalidation = resistance, support

    if bias == "BULLISH":
        change_mind = f"Sustained close below the put wall at {put_wall:,.0f}." if put_wall else \
            f"Sustained close below the session low at {day_low:,.0f}."
    elif bias == "BEARISH":
        change_mind = f"Sustained reclaim above the call wall at {call_wall:,.0f}." if call_wall else \
            f"Sustained reclaim above the session high at {day_high:,.0f}."
    else:
        change_mind = f"Close outside {invalidation:,.0f} – {target:,.0f}."

    confidence = int(sig["llm_confidence"]) if sig.get("llm_confidence") is not None else None
    strength = float(sig["signal_strength"]) if sig.get("signal_strength") is not None else None
    stars_str = ("★" * confidence + "☆" * (5 - confidence)) if confidence is not None else ""
    if confidence is not None:
        conviction_pct = min(100, max(0, confidence * 20))
    elif strength is not None:
        conviction_pct = min(100, max(0, int(round(strength * 10))))
    else:
        conviction_pct = 0

    raw_thesis = sig.get("llm_thesis") or ""
    sentences = [s.strip() for s in raw_thesis.split(". ") if s.strip()]
    summary = ". ".join(sentences[:2])
    if summary and not summary.endswith("."):
        summary += "."

    return {
        "verdict": bias,
        "stars": stars_str,
        "confidence": confidence,
        "conviction_pct": conviction_pct,
        "signal_strength": strength,
        "signals_today": len(day_signals),
        "spot": round(spot_val, 2),
        "target": round(target, 2),
        "invalidation": round(invalidation, 2),
        "vwap": round(vwap, 2),
        "sparkline": ribbon.get("sparkline", []),
        "thesis_history": thesis_history,
        "flip_summary": flip_summary,
        "meta_updated": meta_updated,
        "thesis_date": sig_date,
        "summary": summary,
        "thesis": raw_thesis,
        "supports": supports,
        "contradicts": contradicts,
        "change_mind": change_mind,
        "chips": chips,
        "market_pulse": market_pulse,
        "flow_charts": flow_charts,
        "news": news,
        "updated_at": ist_time_str(sig["fired_at"]) + " IST",
        "data_status": "ok" if (session and sig) else "partial",
    }

# ── 3. Signals Feed ────────────────────────────────────────────────────────────
def get_signals_feed(symbol: str = "NIFTY", limit: int = 50, bias_filter: Optional[str] = None, type_filter: Optional[str] = None, ranked: bool = False) -> List[Dict[str, Any]]:
    rows = []
    sb = get_supabase_client()
    if sb:
        try:
            q = sb.table("signals").select("*").eq("symbol", symbol)
            if bias_filter and bias_filter != "ALL":
                q = q.eq("bias", bias_filter)
            if type_filter and type_filter != "ALL":
                q = q.eq("signal_type", type_filter)
            if ranked:
                q = q.order("signal_strength", desc=True)
            else:
                q = q.order("fired_at", desc=True)
            res = q.limit(limit).execute()
            if res.data and len(res.data) > 0:
                rows = res.data
        except Exception as e:
            logger.warning("Supabase signals feed error: %s", e)

    if not rows:
        rows = []

    results = []
    for idx, r in enumerate(rows):
        # Strength: normalise a real score, leave it blank when the feed has none.
        raw_conf = r["llm_confidence"]
        raw_str = r["signal_strength"]
        str_val = None
        if raw_str is not None:
            s = float(raw_str)
            if 10.0 < s <= 100.0:
                s = 1.0 + (s / 100.0) * 4.0
            elif 5.0 < s <= 10.0:
                s = s / 2.0
            elif s > 100.0:
                s = 5.0
            str_val = min(5.0, max(1.0, round(s, 1)))

        conf = min(5, max(1, int(raw_conf))) if (raw_conf is not None and int(raw_conf) > 0) else None

        strike_val = f"{int(r['strike']):,}" if r["strike"] else "—"
        strike_label = f"{strike_val} {r['option_type'] or ''}".strip()

        # OI delta and volume: the feed's own numbers, or a dash.
        oi_change = r["oi_change"]
        oi_str = f"{oi_change/100000:+.1f}L" if oi_change is not None else "—"
        vol = r["volume"]
        vol_str = f"{vol/100000:.1f}L" if vol is not None else "—"

        # Distance from spot
        spot_p = float(r["spot_price"]) if r["spot_price"] else None
        strike_num = float(r["strike"]) if r["strike"] else None
        if spot_p and strike_num:
            dist_pts = round(strike_num - spot_p, 1)
            dist_pct = round((dist_pts / spot_p) * 100, 1)
            dist_str = f"{dist_pts:+.0f} pts ({dist_pct:+.1f}%)"
        else:
            dist_str = "—"

        # Premium delta is the measured entry→exit move, never an estimate.
        entry_prem = r["entry_premium"] if "entry_premium" in r.keys() else None
        exit_prem = r["exit_premium"] if "exit_premium" in r.keys() else None
        if entry_prem is not None and exit_prem is not None:
            prem_pts = round(float(exit_prem) - float(entry_prem), 1)
            prem_str = f"{prem_pts:+.1f} pts"
        else:
            prem_str = "—"

        # Human-readable institutional setup label
        st_type = (r["signal_type"] or "").upper()
        op_type = (r["option_type"] or "CE").upper()
        raw_bias = (r["bias"] or "NEUTRAL").upper()
        if "UNWIND" in st_type:
            setup_label = "Long unwinding" if op_type == "CE" else "Short covering"
        elif "BUILDUP" in st_type:
            setup_label = "Long buildup" if raw_bias == "BULLISH" else "Short buildup"
        elif "PCR" in st_type:
            setup_label = "PCR divergence"
        elif "IV" in st_type and "SPIKE" in st_type:
            setup_label = "IV spike"
        elif "VOLUME" in st_type or "SPIKE" in st_type:
            setup_label = "Volume breakout"
        else:
            setup_label = (r["signal_type"] or "").replace("_", " ").title()

        results.append({
            "id": r["id"],
            "rank": idx + 1 if ranked else None,
            "strike_label": strike_label,
            "strike": r["strike"],
            "option_type": r["option_type"],
            "time_ist": ist_time_str(r["fired_at"]),
            "timestamp": r["fired_at"],
            "bias": (r["bias"] or "NEUTRAL").capitalize(),
            "setup": r["signal_type"],
            "setup_label": setup_label,
            "strength": str_val,
            "confidence": conf,
            "stars": ("★" * conf + "☆" * (5 - conf)) if conf is not None else "",
            "expiry": r["expiry"] or "",
            "iv": round(float(r["iv"]), 1) if r["iv"] is not None else None,
            "oi_delta": oi_str,
            "premium_delta": prem_str,
            "distance_from_spot": dist_str,
            "volume": vol_str,
            "spot_price": r["spot_price"],
            "thesis": r["llm_thesis"] or "",
            "news": [],
        })
    return results

# ── 4. Signal Detail (for 440px Slide-Over) ───────────────────────────────────
def get_signal_detail(signal_id: int) -> Optional[Dict[str, Any]]:
    sb = get_supabase_client()
    r = None
    news: List[str] = []
    if sb:
        try:
            res = sb.table("signals").select("*").eq("id", signal_id).execute()
            if res.data:
                r = res.data[0]
                news_res = sb.table("news_raw").select("headline").order("fetched_at", desc=True).limit(5).execute()
                news = [nr["headline"] for nr in (news_res.data or []) if nr.get("headline")]
        except Exception as e:
            logger.warning("Supabase get_signal_detail failed: %s", e)

    if not r:
        return None

    # Market context at the signal's own timestamp (real columns, no defaults)
    pcr = rsi = macd = vwap = None
    if sb:
        try:
            fired = str(r.get("fired_at") or "")
            mc = (
                sb.table("market_context").select("pcr,rsi,macd_hist,vwap")
                .eq("symbol", r.get("symbol") or "NIFTY")
                .lte("timestamp", fired).order("timestamp", desc=True).limit(1).execute()
            )
            if mc.data:
                m = mc.data[0]
                pcr, rsi = m.get("pcr"), m.get("rsi")
                macd, vwap = m.get("macd_hist"), m.get("vwap")
        except Exception as e:
            logger.warning("signal context lookup failed: %s", e)

    conf = int(r["llm_confidence"]) if r.get("llm_confidence") is not None else None
    strike_val = f"{int(r['strike']):,}" if r.get("strike") else "—"
    strike_label = f"{strike_val} {r.get('option_type') or ''}".strip()
    oi_change = r.get("oi_change")
    oi_str = f"{oi_change/100000:+.1f}L" if oi_change is not None else "—"
    vol = r.get("volume")
    vol_str = f"{vol/100000:.1f}L" if vol is not None else "—"

    strength = None
    if r.get("signal_strength") is not None:
        s = float(r["signal_strength"])
        if 10.0 < s <= 100.0:
            s = 1.0 + (s / 100.0) * 4.0
        elif 5.0 < s <= 10.0:
            s = s / 2.0
        elif s > 100.0:
            s = 5.0
        strength = min(5.0, max(1.0, round(s, 1)))

    outcome_7d = r.get("outcome_7d")
    return {
        "id": r["id"],
        "strike_label": strike_label,
        "strike": r.get("strike"),
        "option_type": r.get("option_type"),
        "expiry": r.get("expiry") or "",
        "time_ist": ist_time_str(str(r.get("fired_at") or "")),
        "timestamp": str(r.get("fired_at") or ""),
        "bias": (r.get("bias") or "NEUTRAL").capitalize(),
        "setup": r.get("signal_type"),
        "strength": strength,
        "confidence": conf,
        "stars": ("★" * conf + "☆" * (5 - conf)) if conf is not None else "",
        "thesis": r.get("llm_thesis") or "",
        "iv": round(float(r["iv"]), 1) if r.get("iv") is not None else None,
        "oi_delta": oi_str,
        "volume": vol_str,
        "pcr_rsi": f"{float(pcr):.2f} / {float(rsi):.1f}" if pcr is not None and rsi is not None else "",
        "macd_vwap": f"{float(macd):+.2f} / {float(vwap):,.0f}" if macd is not None and vwap is not None else "",
        "spot_price": r.get("spot_price"),
        "news": news,
        "outcome": {
            "evaluated": r.get("outcome_correct") is not None,
            "correct": bool(r.get("outcome_correct")),
            "outcome_7d": outcome_7d,
            "move_pct": f"{float(outcome_7d):+.2f}%" if outcome_7d is not None else "",
        },
    }

# ── 5. Options Chain (Center-Anchored Strike Ladder) ───────────────────────────
def get_options_chain_ladder(symbol: str = "NIFTY") -> Dict[str, Any]:
    ribbon = get_ribbon_data(symbol)
    spot = ribbon.get("spot") or 0.0

    rows = []
    sb = get_supabase_client()
    if sb:
        try:
            latest_oc_res = sb.table("options_chain").select("timestamp").eq("symbol", symbol).order("timestamp", desc=True).limit(1).execute()
            if latest_oc_res.data:
                latest_oc_ts = latest_oc_res.data[0]["timestamp"]
                active_exp = _get_active_expiry_supabase(sb, symbol, latest_oc_ts)
                q = sb.table("options_chain").select("strike,option_type,oi,oi_change,volume,iv,last_price").eq("symbol", symbol).eq("timestamp", latest_oc_ts)
                if active_exp:
                    q = q.eq("expiry", active_exp)
                res = q.order("strike", desc=False).execute()
                if res.data:
                    rows = res.data
        except Exception as e:
            logger.warning("Supabase options_chain ladder query error: %s", e)

    if not rows:
        return {"spot": spot, "rows": [], "total_ce_oi": "0L", "total_pe_oi": "0L", "net_pcr": None}

    by_strike: Dict[float, Dict[str, Any]] = {}
    total_ce = 0
    total_pe = 0

    for r in rows:
        k = float(r["strike"])
        if k not in by_strike:
            by_strike[k] = {"strike": k, "ce": {}, "pe": {}}
        
        opt = r["option_type"]
        oi = int(r["oi"] or 0)
        oi_chg = int(r["oi_change"] or 0)
        vol = int(r["volume"] or 0)
        iv = round(float(r["iv"] or 0), 1)
        ltp = round(float(r["last_price"] or 0), 2)

        if opt == "CE":
            total_ce += oi
            by_strike[k]["ce"] = {
                "oi": f"{oi/100000:.1f}L",
                "oi_raw": oi,
                "oi_change": f"{oi_chg/100000:+.1f}L",
                "volume": f"{vol/100000:.1f}L",
                "iv": iv,
                "ltp": ltp
            }
        else:
            total_pe += oi
            by_strike[k]["pe"] = {
                "oi": f"{oi/100000:.1f}L",
                "oi_raw": oi,
                "oi_change": f"{oi_chg/100000:+.1f}L",
                "volume": f"{vol/100000:.1f}L",
                "iv": iv,
                "ltp": ltp
            }

    spot = ribbon["spot"]
    atm_strike = min(by_strike.keys(), key=lambda k: abs(k - spot)) if by_strike else spot

    # Filter to strikes around ATM (e.g. +/- 10 strikes)
    sorted_k = sorted(list(by_strike.keys()))
    if atm_strike in sorted_k:
        idx = sorted_k.index(atm_strike)
        start_idx = max(0, idx - 8)
        end_idx = min(len(sorted_k), idx + 9)
        selected_strikes = sorted_k[start_idx:end_idx]
    else:
        selected_strikes = sorted_k[:16]

    ladder = []
    for k in selected_strikes:
        entry = by_strike[k]
        badges = []
        if k == atm_strike:
            badges.append("ATM")
        if k == ribbon["call_wall"]:
            badges.append("CALL WALL")
        if k == ribbon["put_wall"]:
            badges.append("PUT WALL")
        if k == ribbon["max_pain"]:
            badges.append("MAX PAIN")

        ladder.append({
            "strike": f"{int(k):,}",
            "strike_num": k,
            "is_atm": k == atm_strike,
            "badges": badges,
            "ce": entry.get("ce", {"oi": "—", "oi_change": "—", "volume": "—", "iv": 0, "ltp": 0}),
            "pe": entry.get("pe", {"oi": "—", "oi_change": "—", "volume": "—", "iv": 0, "ltp": 0}),
        })

    return {
        "spot": spot,
        "total_ce_oi": f"{total_ce/100000:.1f}L",
        "total_pe_oi": f"{total_pe/100000:.1f}L",
        "net_pcr": round(total_pe / total_ce, 2) if total_ce > 0 else 1.0,
        "atm_strike": atm_strike,
        "rows": ladder
    }

# Helper to format ISO dates like "2026-10-01" or "10-01" to unambiguous "01 Oct"
def format_display_date(date_str: str) -> str:
    if not date_str:
        return ""
    try:
        if len(date_str) >= 10 and date_str[4] == "-":
            dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
            return dt.strftime("%d %b")
        elif len(date_str) == 5 and date_str[2] == "-":
            m, d = int(date_str[:2]), int(date_str[3:])
            dt = datetime(2026, m, d)
            return dt.strftime("%d %b")
    except Exception:
        pass
    return date_str


def _to_ist_time(iso_ts: Optional[str]) -> str:
    """UTC ISO timestamp -> 'HH:MM' IST, or '' when unparseable."""
    if not iso_ts:
        return ""
    try:
        dt = datetime.fromisoformat(str(iso_ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (dt + timedelta(hours=5, minutes=30)).strftime("%H:%M")
    except Exception:
        return ""

# ── 6. Backtesting Hub ────────────────────────────────────────────────────────
def get_backtest_hub_data(range_days: int = 30, horizon: str = "+7d") -> Dict[str, Any]:
    # NOTE: horizon is accepted for API compatibility but does not rescale
    # returns. Trades resolve same-day at target / stop / 15:20 IST.

    # 1. Primary Source of Truth: Supabase `trades` execution table
    sb = get_supabase_client()
    sb_trades_raw = []
    if sb:
        try:
            tr_q = sb.table("trades").select("*").order("entry_at", desc=True)
            if range_days > 0:
                cutoff = (datetime.now(timezone.utc) - timedelta(days=range_days)).isoformat()
                tr_q = tr_q.gte("entry_at", cutoff)
            res = tr_q.limit(1000).execute()
            # shortcut: single 1000-row page (Supabase max-rows). Paginate if trades exceed 1000.
            sb_trades_raw = res.data or []
        except Exception as e:
            logger.debug("Failed to query Supabase trades table: %s", e)

    if sb_trades_raw:
        trades = []
        setup_counts = {"RULES": [0, 0], "LLM": [0, 0], "OI_BUILDUP": [0, 0], "OI_UNWIND": [0, 0]}
        dir_counts = {"BULLISH": [0, 0], "BEARISH": [0, 0]}
        daily_groups: Dict[str, List[bool]] = {}

        total_correct = 0
        total_evaluated = 0
        returns = []

        # Temporal & Spatial Clustering (30-minute institutional campaign window)
        clusters = []
        trade_cluster_map = {}
        eval_trades = [
            t for t in sb_trades_raw
            if not (t.get("exit_reason") and (str(t.get("exit_reason")).startswith("SKIPPED_") or t.get("exit_reason") == "NON_DIRECTIONAL"))
            and t.get("resolved_at")
            and not t.get("stale_ltp")
            and not t.get("is_exploratory")
        ]
        eval_trades.sort(key=lambda x: (x.get("entry_at") or "", 0 if x.get("source") == "RULES" else 1))

        # One observation per signal: RULES wins over LLM when both exist.
        dedup_trade_ids = set()
        seen_signal_ids = set()

        for t in eval_trades:
            t_id = t["id"]
            sid = t.get("signal_id")
            if sid in seen_signal_ids:
                continue
            seen_signal_ids.add(sid)
            dedup_trade_ids.add(t_id)
            src = t.get("source", "RULES")
            b = (t.get("bias_used") or "BULLISH").upper()
            e_at = t.get("entry_at") or ""
            pnl = float(t.get("net_pnl_pct") or 0.0)
            try:
                dt = datetime.fromisoformat(e_at.replace("Z", "+00:00"))
            except Exception:
                dt = datetime.now(timezone.utc)

            assigned = False
            for cl in reversed(clusters):
                if cl["source"] == src and cl["bias"] == b:
                    delta_m = (dt - cl["last_time"]).total_seconds() / 60.0
                    if delta_m <= 30.0:
                        cl["trade_ids"].append(t_id)
                        cl["pnl_list"].append(pnl)
                        cl["last_time"] = dt
                        trade_cluster_map[t_id] = cl["label"]
                        assigned = True
                        break
            if not assigned:
                cl_idx = len(clusters) + 1
                cl_label = f"C-{dt.strftime('%m%d')}-{cl_idx:02d}"
                clusters.append({
                    "id": cl_idx,
                    "label": cl_label,
                    "source": src,
                    "bias": b,
                    "date": e_at[:10],
                    "start_time": dt,
                    "last_time": dt,
                    "trade_ids": [t_id],
                    "pnl_list": [pnl],
                })
                trade_cluster_map[t_id] = cl_label

        cluster_correct = 0
        cluster_rules = [0, 0]
        cluster_llm = [0, 0]
        for cl in clusters:
            avg_cl_pnl = float(np.mean(cl["pnl_list"])) if cl["pnl_list"] else 0.0
            cl_win = (avg_cl_pnl > 0)
            if cl_win:
                cluster_correct += 1
            if cl["source"] == "RULES":
                cluster_rules[1] += 1
                if cl_win:
                    cluster_rules[0] += 1
            elif cl["source"] == "LLM":
                cluster_llm[1] += 1
                if cl_win:
                    cluster_llm[0] += 1

        clusters_evaluated = len(clusters)
        cluster_win_rate = round(cluster_correct / clusters_evaluated * 100, 1) if clusters_evaluated > 0 else 0.0

        for t in sb_trades_raw:
            exit_r = t.get("exit_reason")
            is_skipped = bool(
                exit_r and (
                    str(exit_r).startswith("SKIPPED_")
                    or exit_r == "NON_DIRECTIONAL"
                    or t.get("stale_ltp")
                    or t.get("is_exploratory")
                )
            )
            net_pnl = float(t.get("net_pnl_pct") or 0.0)
            is_correct = (net_pnl > 0)
            bias = (t.get("bias_used") or "BULLISH").upper()
            source = t.get("source", "RULES")
            entry_at = t.get("entry_at") or ""
            sig_date = entry_at[:10]
            cl_id = trade_cluster_map.get(t.get("id"))

            if not is_skipped and t.get("resolved_at"):
                if source in setup_counts:
                    setup_counts[source][1] += 1
                    if is_correct:
                        setup_counts[source][0] += 1

                b_key = "BULLISH" if bias == "BULLISH" else "BEARISH"
                dir_counts[b_key][1] += 1
                if is_correct:
                    dir_counts[b_key][0] += 1

                # Overall stats: one observation per signal.
                if t.get("id") in dedup_trade_ids:
                    total_evaluated += 1
                    if is_correct:
                        total_correct += 1
                    returns.append(net_pnl)
                    if sig_date:
                        daily_groups.setdefault(sig_date, []).append(is_correct)

            trades.append({
                "id": t.get("id"),
                "date": format_display_date(sig_date),
                "strike_label": f"{int(t.get('strike') or 0):,} {t.get('option_type') or ''}",
                "setup": f"{source} · {t.get('exit_reason') or 'Open'}" + (f" · {cl_id}" if cl_id else ""),
                "cluster_id": cl_id or "Unclustered",
                "predicted_bias": bias.capitalize(),
                "expiry_label": format_display_date(str(t.get("expiry"))) if t.get("expiry") else "",
                "entry_time_ist": _to_ist_time(t.get("entry_at")),
                "entry_premium": f"₹{t.get('entry_premium', 0):.2f}",
                "exit_premium": f"₹{t.get('exit_premium', 0):.2f}" if t.get('exit_premium') else "Open",
                "move_pct": f"{net_pnl:+.1f}%",
                "outcome": exit_r if is_skipped else ("Correct" if is_correct else "Missed"),
                "is_correct": False if is_skipped else is_correct,
                "edge": f"{net_pnl:+.1f}%",
                "edge_val": net_pnl,
                "horizon": horizon,
                "thesis": f"Trade execution for {source} bias {bias} on {t.get('expiry')}."
            })

        # Only measured trades belong in the history table: stale, exploratory and
        # skipped rows were never resolved and would read as fake losses.
        trades = [tr for tr in trades if tr.get("id") in dedup_trade_ids]

        # Why rows were dropped matters: "no trades since 15 Oct" is really
        # "185 rows resolved but none was measurable". Count them by reason.
        excluded_by_reason = {
            "stale_ltp": 0, "exploratory": 0, "skipped": 0,
            "non_directional": 0, "unresolved": 0, "duplicate_signal": 0,
        }
        for t in sb_trades_raw:
            exit_r = str(t.get("exit_reason") or "")
            if t.get("stale_ltp"):
                excluded_by_reason["stale_ltp"] += 1
            elif t.get("is_exploratory"):
                excluded_by_reason["exploratory"] += 1
            elif exit_r.startswith("SKIPPED_"):
                excluded_by_reason["skipped"] += 1
            elif exit_r == "NON_DIRECTIONAL":
                excluded_by_reason["non_directional"] += 1
            elif not t.get("resolved_at"):
                excluded_by_reason["unresolved"] += 1
            elif t.get("id") not in dedup_trade_ids:
                excluded_by_reason["duplicate_signal"] += 1

        raw_win_rate = round((total_correct / total_evaluated * 100), 1) if total_evaluated > 0 else 0.0
        avg_return = round(float(np.mean(returns)), 2) if returns else 0.0

        daily_win_rates = []
        for s_date, bools in sorted(daily_groups.items()):
            c_cnt = sum(bools)
            daily_win_rates.append({
                "day": format_display_date(s_date),
                "win_rate": round(c_cnt / len(bools) * 100, 1) if bools else 0.0,
                "count": len(bools)
            })

        sample_days = sorted(daily_groups.keys())
        sample_first = format_display_date(sample_days[0]) if sample_days else ""
        sample_last = format_display_date(sample_days[-1]) if sample_days else ""
        days_since_last_trade = None
        if sample_days:
            try:
                days_since_last_trade = (
                    datetime.now(timezone.utc).date()
                    - datetime.fromisoformat(sample_days[-1]).date()
                ).days
            except Exception:
                days_since_last_trade = None

        sample_warning = None
        if total_evaluated < 30:
            sample_warning = (
                f"Only {total_evaluated} clean trades in this window — "
                "not statistically meaningful. Use All Time or wait for more sessions."
            )
        elif days_since_last_trade is not None and days_since_last_trade > 4:
            sample_warning = (
                f"No clean trades since {sample_last} ({days_since_last_trade} days ago) — "
                "the feed stopped resolving, so this is a historical sample, not the last 30 days."
            )

        # Honest KPIs from the deduplicated clean sample.
        expectancy = round(float(np.mean(returns)), 2) if returns else 0.0
        wins = [r for r in returns if r > 0]
        losses = [abs(r) for r in returns if r < 0]
        sum_w, sum_l = sum(wins), sum(losses)
        profit_factor = round(sum_w / sum_l, 2) if sum_l > 0 else (round(sum_w, 2) if sum_w > 0 else 0.0)
        avg_win = round(float(np.mean(wins)), 2) if wins else 0.0
        avg_loss = round(float(np.mean(losses)), 2) if losses else 0.0

        def _wilson(k: int, n: int, z: float = 1.96):
            if n <= 0:
                return 0, 0
            p = k / n
            denom = 1 + (z * z) / n
            center = (p + (z * z) / (2 * n)) / denom
            spread = (z * math.sqrt(max(0, (p * (1 - p) / n) + ((z * z) / (4 * n * n))))) / denom
            return max(0, int(round((center - spread) * 100))), min(100, int(round((center + spread) * 100)))

        ci_lower, ci_upper = _wilson(total_correct, total_evaluated)
        ci_str = f"95% CI {ci_lower}–{ci_upper} · n={total_evaluated} (assumes independent trades)"

        chron = [t for t in eval_trades if t.get("id") in dedup_trade_ids]
        chron.sort(key=lambda x: x.get("entry_at") or "")
        equity = peak = max_dd = 0.0
        equity_curve = []
        # One stake unit per trade: the curve is the sum of per-trade % (uncompounded), and
        # drawdown is its peak-to-trough in stake units — not a % of account capital.
        for idx, t in enumerate(chron):
            equity = round(equity + float(t.get("net_pnl_pct") or 0), 2)
            peak = max(peak, equity)
            max_dd = min(max_dd, (equity - peak) / 100)
            equity_curve.append({
                "trade": f"Trade {idx + 1}",
                "trade_num": idx + 1,
                "signals": equity,
                "benchmark": 0.0,
            })

        by_setup = [
            {"label": "RULES", "win_rate": round(setup_counts["RULES"][0] / max(1, setup_counts["RULES"][1]) * 100), "n": setup_counts["RULES"][1]},
            {"label": "LLM", "win_rate": round(setup_counts["LLM"][0] / max(1, setup_counts["LLM"][1]) * 100), "n": setup_counts["LLM"][1]},
        ]
        by_dir = [
            {"label": "Bullish", "win_rate": round(dir_counts["BULLISH"][0] / max(1, dir_counts["BULLISH"][1]) * 100), "n": dir_counts["BULLISH"][1]},
            {"label": "Bearish", "win_rate": round(dir_counts["BEARISH"][0] / max(1, dir_counts["BEARISH"][1]) * 100), "n": dir_counts["BEARISH"][1]},
        ]

        # Best setup uses the same trade-level sample as by_setup, never the cluster rate.
        ranked = [s for s in by_setup if s["n"] >= 5] or [s for s in by_setup if s["n"] > 0]
        top = max(ranked, key=lambda s: (s["win_rate"], s["n"])) if ranked else None
        best_setup_name = f"{top['label']} · {top['win_rate']}%" if top else "No trades"
        best_setup_sub = f"n={top['n']} · min n 5" if top and top["n"] >= 5 else (f"n={top['n']} · below 5, not meaningful" if top else "n=0")

        return {
            "win_rate": raw_win_rate,
            "raw_win_rate": raw_win_rate,
            "cluster_win_rate": cluster_win_rate,
            "clusters_evaluated": clusters_evaluated,
            "signals_evaluated": total_evaluated,
            "avg_forward_return": f"{avg_return:+.2f}%",
            "ci_lower": ci_lower,
            "ci_upper": ci_upper,
            "ci_str": ci_str,
            "expectancy": expectancy,
            "expectancy_str": f"{expectancy:+.2f}%",
            "profit_factor": profit_factor,
            "profit_factor_str": f"{profit_factor:.2f}",
            "profit_factor_sub": f"Win +{avg_win:.2f} · loss -{avg_loss:.2f} (% per trade, equal notional)",
            "max_drawdown": round(max_dd, 2),
            "max_drawdown_str": f"{max_dd:.2f} units",
            "equity_curve": equity_curve,
            "breakdowns": {
                "by_setup": by_setup,
                "by_score": [],
                "by_direction_moneyness": by_dir,
            },
            "best_setup": best_setup_name,
            "best_setup_name": best_setup_name,
            "best_setup_sub": best_setup_sub,
            "daily_win_rates": daily_win_rates,
            "sample_first": sample_first,
            "sample_last": sample_last,
            "sample_days": len(sample_days),
            "days_since_last_trade": days_since_last_trade,
            # Same trade-level sample as `by_setup`/`best_setup`; the cluster
            # counts (n=12) contradict the hub and are not what users read.
            "accuracy_by_setup": {
                "RULES": round(setup_counts["RULES"][0]/max(1, setup_counts["RULES"][1])*100),
                "LLM": round(setup_counts["LLM"][0]/max(1, setup_counts["LLM"][1])*100),
            },
            "sample_sizes_by_setup": {
                "RULES": setup_counts["RULES"][1],
                "LLM": setup_counts["LLM"][1],
            },
            "raw_accuracy_by_setup": {
                "RULES": round(setup_counts["RULES"][0]/max(1, setup_counts["RULES"][1])*100) if setup_counts["RULES"][1] > 0 else 0,
                "LLM": round(setup_counts["LLM"][0]/max(1, setup_counts["LLM"][1])*100) if setup_counts["LLM"][1] > 0 else 0,
            },
            "calibration": [],
            "data_status": "ok" if total_evaluated >= 30 else "insufficient_sample",
            "sample_warning": sample_warning,
            "excluded_by_reason": excluded_by_reason,
            "excluded_trades": len(sb_trades_raw) - total_evaluated,
            "horizon": horizon,
            "trades": trades
        }

    # 2. No execution data: never fabricate a backtest.
    return {
        "win_rate": 0.0,
        "raw_win_rate": 0.0,
        "clusters_evaluated": 0,
        "signals_evaluated": 0,
        "avg_forward_return": "0.00%",
        "ci_lower": 0,
        "ci_upper": 0,
        "ci_str": "n=0 · no execution data",
        "expectancy": 0.0,
        "expectancy_str": "0.00%",
        "profit_factor": 0.0,
        "profit_factor_str": "\u2014",
        "profit_factor_sub": "No resolved trades",
        "max_drawdown": 0.0,
        "max_drawdown_str": "0.0%",
        "best_setup": "No trades",
        "best_setup_name": "No trades",
        "best_setup_sub": "n=0",
        "equity_curve": [],
        "calibration": [],
        "breakdowns": {
            "by_setup": [
                {"label": "RULES", "win_rate": 0, "n": 0},
                {"label": "LLM", "win_rate": 0, "n": 0},
            ],
            "by_score": [],
            "by_direction_moneyness": [
                {"label": "Bullish", "win_rate": 0, "n": 0},
                {"label": "Bearish", "win_rate": 0, "n": 0},
            ],
        },
        "daily_win_rates": [],
        "sample_first": "",
        "sample_last": "",
        "sample_days": 0,
        "days_since_last_trade": None,
        "accuracy_by_setup": {"RULES": 0, "LLM": 0},
        "sample_sizes_by_setup": {"RULES": 0, "LLM": 0},
        "raw_accuracy_by_setup": {"RULES": 0, "LLM": 0},
        "accuracy_by_confidence": {},
        "sample_sizes_by_confidence": {},
        "data_status": "no_execution_data",
        "sample_warning": "No resolved execution trades in Supabase. Nothing to measure yet.",
        "excluded_by_reason": {},
        "excluded_trades": 0,
        "horizon": horizon,
        "trades": [],
    }


# ── 7. Charts Data ─────────────────────────────────────────────────────────────
def get_chart_data(chart_id: str, symbol: str = "NIFTY") -> Dict[str, Any]:
    sb = get_supabase_client()
    ribbon = get_ribbon_data(symbol)

    if chart_id == "c1":  # 5-min candles + flow markers
        candles = []
        markers = []
        if sb:
            try:
                latest_mc = sb.table("market_context").select("timestamp").eq("symbol", symbol).order("timestamp", desc=True).limit(1).execute()
                if latest_mc.data:
                    latest_date = latest_mc.data[0]["timestamp"][:10]
                    mc_rows = sb.table("market_context").select("timestamp,spot_price").eq("symbol", symbol).gte("timestamp", f"{latest_date}T00:00:00").order("timestamp", desc=False).execute()

                    prev_close = None
                    for r in mc_rows.data:
                        p = float(r["spot_price"] or 0)
                        if p <= 0:
                            continue
                        o = prev_close if prev_close else p
                        h = max(o, p)
                        l = min(o, p)
                        c = round(p, 2)
                        prev_close = c
                        candles.append({
                            "time": ist_time_str(r["timestamp"]),
                            "open": o,
                            "high": h,
                            "low": l,
                            "close": c,
                        })

                    sig_res = sb.table("signals").select("id,strike,option_type,bias,signal_type,fired_at").eq("symbol", symbol).gte("fired_at", f"{latest_date}T00:00:00").order("fired_at", desc=False).execute()
                    if sig_res.data and candles:
                        for s in sig_res.data:
                            sig_time = ist_time_str(s["fired_at"])
                            idx = len(candles) - 1
                            for c_i, cand in enumerate(candles):
                                if cand["time"] >= sig_time:
                                    idx = c_i
                                    break
                            b_type = "bull" if (s.get("bias") or "").upper() == "BULLISH" else "bear"
                            lbl = f"{int(s['strike']):,} {s['option_type']}" if s.get("strike") else s.get("signal_type", "SIGNAL")
                            markers.append({
                                "index": idx,
                                "type": b_type,
                                "label": lbl,
                                "signal_id": s["id"],
                            })
            except Exception as e:
                logger.warning("Supabase chart c1 error: %s", e)

        return {"candles": candles, "markers": markers}

    elif chart_id == "c2":  # Call vs Put OI by strike
        strikes_data = []
        if sb:
            try:
                latest_oc_res = sb.table("options_chain").select("timestamp").eq("symbol", symbol).order("timestamp", desc=True).limit(1).execute()
                if latest_oc_res.data:
                    latest_ts = latest_oc_res.data[0]["timestamp"]
                    active_exp = _get_active_expiry_supabase(sb, symbol, latest_ts)
                    q = sb.table("options_chain").select("strike,option_type,oi").eq("symbol", symbol).eq("timestamp", latest_ts)
                    if active_exp:
                        q = q.eq("expiry", active_exp)
                    res = q.execute()

                    ce_map: Dict[float, int] = {}
                    pe_map: Dict[float, int] = {}
                    for r in res.data:
                        k = float(r["strike"])
                        oi = int(r["oi"] or 0)
                        if r["option_type"] == "CE":
                            ce_map[k] = ce_map.get(k, 0) + oi
                        else:
                            pe_map[k] = pe_map.get(k, 0) + oi

                    spot = ribbon.get("spot") or 0.0
                    all_strikes = sorted(list(set(ce_map.keys()).union(set(pe_map.keys()))))
                    near = sorted(all_strikes, key=lambda x: abs(x - spot))[:16]
                    near.sort()
                    for k in near:
                        strikes_data.append({
                            "strike": int(k),
                            "ce_oi": round(ce_map.get(k, 0) / 100000, 2),
                            "pe_oi": round(pe_map.get(k, 0) / 100000, 2),
                        })
            except Exception as e:
                logger.warning("Supabase chart c2 error: %s", e)

        return {"data": strikes_data}

    elif chart_id == "c3":  # IV Skew
        skew_data = []
        if sb:
            try:
                latest_oc_res = sb.table("options_chain").select("timestamp").eq("symbol", symbol).order("timestamp", desc=True).limit(1).execute()
                if latest_oc_res.data:
                    latest_ts = latest_oc_res.data[0]["timestamp"]
                    active_exp = _get_active_expiry_supabase(sb, symbol, latest_ts)
                    q = sb.table("options_chain").select("strike,option_type,iv").eq("symbol", symbol).eq("timestamp", latest_ts)
                    if active_exp:
                        q = q.eq("expiry", active_exp)
                    res = q.execute()

                    ce_iv: Dict[float, float] = {}
                    pe_iv: Dict[float, float] = {}
                    for r in res.data:
                        k = float(r["strike"])
                        iv = float(r["iv"] or 0)
                        if r["option_type"] == "CE" and iv > 0:
                            ce_iv[k] = iv
                        elif r["option_type"] == "PE" and iv > 0:
                            pe_iv[k] = iv

                    spot = ribbon.get("spot") or 0.0
                    all_strikes = sorted(list(set(ce_iv.keys()).union(set(pe_iv.keys()))))
                    near = sorted(all_strikes, key=lambda x: abs(x - spot))[:16]
                    near.sort()
                    for k in near:
                        skew_data.append({
                            "strike": int(k),
                            "ce_iv": round(ce_iv.get(k, 0), 1),
                            "pe_iv": round(pe_iv.get(k, 0), 1),
                        })
            except Exception as e:
                logger.warning("Supabase chart c3 error: %s", e)

        return {"skew": skew_data}

    elif chart_id == "c4":  # Settlement payout curve from the live chain's own OI
        curve: List[Dict[str, Any]] = []
        if sb:
            try:
                latest = (
                    sb.table("options_chain").select("timestamp").eq("symbol", symbol)
                    .order("timestamp", desc=True).limit(1).execute()
                )
                if latest.data:
                    ts = latest.data[0]["timestamp"]
                    exp = _get_active_expiry_supabase(sb, symbol, ts)
                    q = sb.table("options_chain").select("strike,option_type,oi").eq("symbol", symbol).eq("timestamp", ts)
                    if exp:
                        q = q.eq("expiry", exp)
                    rows = q.execute().data or []
                    ce = {float(r["strike"]): int(r["oi"] or 0) for r in rows if r["option_type"] == "CE"}
                    pe = {float(r["strike"]): int(r["oi"] or 0) for r in rows if r["option_type"] == "PE"}
                    for s in sorted(set(ce) | set(pe)):
                        payout = (
                            sum(oi * max(0.0, s - k) for k, oi in ce.items())
                            + sum(oi * max(0.0, k - s) for k, oi in pe.items())
                        )
                        curve.append({"strike": int(s), "payout": round(payout / 100000, 1)})
            except Exception as e:
                logger.warning("Supabase chart c4 error: %s", e)

        max_pain = min(curve, key=lambda c: c["payout"])["strike"] if curve else None
        return {"curve": curve, "max_pain": max_pain}

    elif chart_id in ("c5", "c6"):  # PCR / spot / VWAP and RSI / MACD from market_context
        session_date = ribbon.get("session_date") or date.today().isoformat()
        rows = _sample_rows(_mc_session_series(sb, symbol, session_date), 48) if sb else []

        def pick(field: str, nd: int) -> List[Dict[str, Any]]:
            return [
                {"time": ist_time_str(r["timestamp"]), "value": round(float(r[field]), nd)}
                for r in rows if r.get(field) is not None
            ]

        if chart_id == "c5":
            return {"pcr": pick("pcr", 3), "spot": pick("spot_price", 2), "vwap": pick("vwap", 2)}
        return {"rsi": pick("rsi", 2), "macd": pick("macd_hist", 3)}

    return {}
