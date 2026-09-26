# api.py — High-Performance FastAPI Backend for OFA Professional Terminal
import os
import math
import sqlite3
import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, Query, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import config
from config import DB_PATH

app = FastAPI(
    title="Options Flow Analyzer Terminal API",
    description="Institutional-grade options flow analytics & anomaly signals API",
    version="3.0.0"
)

# Enable CORS for local Vite dev server and web clients
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _clean_val(v):
    if v is None:
        return None
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


def get_latest_date(symbol: str = "NIFTY") -> str:
    conn = _conn()
    row = conn.execute("SELECT MAX(DATE(timestamp)) as d FROM options_chain WHERE symbol=?", (symbol,)).fetchone()
    conn.close()
    return row["d"] if row and row["d"] else datetime.now(timezone.utc).strftime("%Y-%m-%d")


def compute_rsi(prices: list, period: int = 14) -> Optional[float]:
    if len(prices) < period + 1:
        return None
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = float(np.mean(gains[:period]))
    avg_loss = float(np.mean(losses[:period]))
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(float(100 - (100 / (1 + rs))), 1)


def compute_max_pain(chain_df: pd.DataFrame) -> Optional[float]:
    """Compute Max Pain strike where option sellers face minimal payout."""
    if chain_df.empty:
        return None
    strikes = sorted(chain_df["strike"].unique())
    if not strikes:
        return None
    
    ce_df = chain_df[chain_df["option_type"] == "CE"][["strike", "oi"]].dropna()
    pe_df = chain_df[chain_df["option_type"] == "PE"][["strike", "oi"]].dropna()
    
    ce_dict = dict(zip(ce_df["strike"], ce_df["oi"]))
    pe_dict = dict(zip(pe_df["strike"], pe_df["oi"]))
    
    min_loss = float("inf")
    best_strike = None
    
    for s in strikes:
        call_loss = sum(max(0.0, s - k) * oi for k, oi in ce_dict.items())
        put_loss = sum(max(0.0, k - s) * oi for k, oi in pe_dict.items())
        total_loss = call_loss + put_loss
        if total_loss < min_loss:
            min_loss = total_loss
            best_strike = float(s)
            
    return best_strike


# ── Health & System Status ───────────────────────────────────────────────────

@app.get("/api/status")
def get_system_status():
    conn = _conn()
    db_stats = conn.execute("""
        SELECT COUNT(*) as total_rows,
               COUNT(DISTINCT DATE(timestamp)) as trading_days,
               MIN(timestamp) as earliest,
               MAX(timestamp) as latest
        FROM options_chain
    """).fetchone()
    
    sig_count = conn.execute("SELECT COUNT(*) as c FROM signals").fetchone()["c"]
    dates = [r[0] for r in conn.execute("SELECT DISTINCT DATE(timestamp) FROM options_chain ORDER BY timestamp DESC LIMIT 30").fetchall()]
    conn.close()
    
    # Check Indian market hours (IST: 9:15 to 15:30 weekdays)
    now_utc = datetime.now(timezone.utc)
    ist_time = now_utc + timedelta(hours=5, minutes=30)
    is_weekday = ist_time.weekday() < 5
    m_open = ist_time.replace(hour=9, minute=15, second=0, microsecond=0)
    m_close = ist_time.replace(hour=15, minute=30, second=0, microsecond=0)
    is_market_open = is_weekday and (m_open <= ist_time <= m_close)
    
    return {
        "status": "healthy",
        "market_open": is_market_open,
        "ist_time": ist_time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_chain_rows": db_stats["total_rows"] or 0,
        "total_signals": sig_count or 0,
        "trading_days": db_stats["trading_days"] or 0,
        "latest_timestamp": db_stats["latest"],
        "available_dates": dates,
        "active_date": dates[0] if dates else datetime.now(timezone.utc).strftime("%Y-%m-%d")
    }


# ── Market Summary / Header Strip ─────────────────────────────────────────────

@app.get("/api/market-summary")
def get_market_summary(date: Optional[str] = None, symbol: str = "NIFTY"):
    if not date:
        date = get_latest_date(symbol)
        
    conn = _conn()
    
    # 1. Spot timeline for date
    spot_rows = conn.execute("""
        SELECT timestamp, AVG(spot_price) as spot
        FROM options_chain
        WHERE symbol=? AND DATE(timestamp)=? AND spot_price IS NOT NULL
        GROUP BY timestamp
        ORDER BY timestamp ASC
    """, (symbol, date)).fetchall()
    
    if not spot_rows:
        conn.close()
        return {
            "symbol": symbol,
            "date": date,
            "has_data": False,
            "spot": None,
            "change": 0,
            "change_pct": 0,
            "high": None,
            "low": None,
            "pcr": None,
            "rsi": None,
            "vwap": None,
            "max_pain": None,
            "call_wall": None,
            "put_wall": None,
            "total_ce_oi": 0,
            "total_pe_oi": 0
        }
        
    spots = [float(r["spot"]) for r in spot_rows]
    curr_spot = spots[-1]
    first_spot = spots[0]
    change = round(curr_spot - first_spot, 2)
    change_pct = round((change / first_spot) * 100, 2)
    day_high = round(max(spots), 2)
    day_low = round(min(spots), 2)
    session_vwap = round(float(np.mean(spots)), 2)
    rsi = compute_rsi(spots)
    
    # 2. Latest chain snapshot for this date
    latest_ts_row = conn.execute("""
        SELECT MAX(timestamp) as ts FROM options_chain
        WHERE symbol=? AND DATE(timestamp)=?
    """, (symbol, date)).fetchone()
    latest_ts = latest_ts_row["ts"]
    
    chain_rows = conn.execute("""
        SELECT strike, option_type, oi, volume, iv, last_price
        FROM options_chain
        WHERE symbol=? AND timestamp=?
    """, (symbol, latest_ts)).fetchall()
    
    conn.close()
    
    chain_df = pd.DataFrame([dict(r) for r in chain_rows])
    
    # PCR and OI metrics
    ce_df = chain_df[chain_df["option_type"] == "CE"] if not chain_df.empty else pd.DataFrame()
    pe_df = chain_df[chain_df["option_type"] == "PE"] if not chain_df.empty else pd.DataFrame()
    
    tot_ce_oi = int(ce_df["oi"].sum()) if not ce_df.empty else 0
    tot_pe_oi = int(pe_df["oi"].sum()) if not pe_df.empty else 0
    pcr = round(tot_pe_oi / tot_ce_oi, 3) if tot_ce_oi > 0 else None
    
    # Call Wall (Max CE OI) & Put Wall (Max PE OI)
    call_wall = float(ce_df.loc[ce_df["oi"].idxmax()]["strike"]) if not ce_df.empty and not ce_df["oi"].isna().all() else None
    put_wall = float(pe_df.loc[pe_df["oi"].idxmax()]["strike"]) if not pe_df.empty and not pe_df["oi"].isna().all() else None
    
    # Max Pain calculation
    max_pain = compute_max_pain(chain_df)
    
    return {
        "symbol": symbol,
        "date": date,
        "has_data": True,
        "spot": curr_spot,
        "change": change,
        "change_pct": change_pct,
        "high": day_high,
        "low": day_low,
        "pcr": pcr,
        "rsi": rsi,
        "vwap": session_vwap,
        "max_pain": max_pain,
        "call_wall": call_wall,
        "put_wall": put_wall,
        "total_ce_oi": tot_ce_oi,
        "total_pe_oi": tot_pe_oi,
        "ticks_count": len(spots),
        "latest_timestamp": latest_ts
    }


# ── Expiries ──────────────────────────────────────────────────────────────────

@app.get("/api/expiries")
def get_expiries(date: Optional[str] = None, symbol: str = "NIFTY"):
    if not date:
        date = get_latest_date(symbol)
    conn = _conn()
    rows = conn.execute("""
        SELECT DISTINCT expiry FROM options_chain
        WHERE symbol=? AND DATE(timestamp)=?
        ORDER BY expiry ASC
    """, (symbol, date)).fetchall()
    conn.close()
    return {"date": date, "expiries": [r["expiry"] for r in rows]}


# ── Options Chain Matrix ──────────────────────────────────────────────────────

@app.get("/api/chain")
def get_options_chain(
    date: Optional[str] = None,
    expiry: Optional[str] = None,
    range_filter: str = "all", # 'all', 'atm5', 'atm10', 'atm20'
    symbol: str = "NIFTY"
):
    if not date:
        date = get_latest_date(symbol)
        
    conn = _conn()
    
    # Latest timestamp for that date
    ts_row = conn.execute("""
        SELECT MAX(timestamp) as ts FROM options_chain
        WHERE symbol=? AND DATE(timestamp)=?
    """, (symbol, date)).fetchone()
    
    if not ts_row or not ts_row["ts"]:
        conn.close()
        return {"date": date, "rows": [], "totals": {}}
        
    latest_ts = ts_row["ts"]
    
    # Determine default expiry if not supplied
    if not expiry:
        exp_row = conn.execute("""
            SELECT expiry FROM options_chain
            WHERE symbol=? AND timestamp=?
            ORDER BY expiry ASC LIMIT 1
        """, (symbol, latest_ts)).fetchone()
        expiry = exp_row["expiry"] if exp_row else None
        
    # Fetch chain
    query = """
        SELECT strike, option_type, expiry, oi, oi_change, volume, iv, last_price, spot_price
        FROM options_chain
        WHERE symbol=? AND timestamp=?
    """
    params = [symbol, latest_ts]
    if expiry:
        query += " AND expiry=?"
        params.append(expiry)
        
    df = pd.read_sql(query, conn, params=params)
    conn.close()
    
    if df.empty:
        return {"date": date, "expiry": expiry, "spot": None, "rows": [], "totals": {}}
        
    spot = float(df["spot_price"].dropna().iloc[0]) if not df["spot_price"].dropna().empty else None
    
    # Pivot CE and PE
    ce = df[df["option_type"] == "CE"].set_index("strike")
    pe = df[df["option_type"] == "PE"].set_index("strike")
    all_strikes = sorted(set(ce.index) | set(pe.index))
    
    # Strike range filter
    step = 50
    atm = round(spot / step) * step if spot else None
    
    if spot and range_filter in ("atm5", "atm10", "atm20"):
        n = 5 if range_filter == "atm5" else (10 if range_filter == "atm10" else 20)
        all_strikes = [s for s in all_strikes if abs(s - atm) <= n * step]
        
    # Find Call Wall & Put Wall
    call_wall = float(ce["oi"].idxmax()) if not ce.empty and not ce["oi"].isna().all() else None
    put_wall = float(pe["oi"].idxmax()) if not pe.empty and not pe["oi"].isna().all() else None
    max_pain = compute_max_pain(df)
    
    # Find max values for percentage bars
    max_ce_oi = float(ce["oi"].max()) if not ce.empty and ce["oi"].max() > 0 else 1.0
    max_pe_oi = float(pe["oi"].max()) if not pe.empty and pe["oi"].max() > 0 else 1.0
    max_ce_vol = float(ce["volume"].max()) if not ce.empty and ce["volume"].max() > 0 else 1.0
    max_pe_vol = float(pe["volume"].max()) if not pe.empty and pe["volume"].max() > 0 else 1.0
    
    rows = []
    for s in all_strikes:
        c_row = ce.loc[s] if s in ce.index else None
        p_row = pe.loc[s] if s in pe.index else None
        
        is_atm = bool(spot and abs(s - spot) <= 25)
        
        def extract(r):
            if r is None:
                return {"oi": 0, "oi_change": 0, "volume": 0, "iv": None, "last_price": None}
            return {
                "oi": int(r["oi"]) if pd.notna(r["oi"]) else 0,
                "oi_change": int(r["oi_change"]) if pd.notna(r["oi_change"]) else 0,
                "volume": int(r["volume"]) if pd.notna(r["volume"]) else 0,
                "iv": round(float(r["iv"]), 2) if pd.notna(r["iv"]) else None,
                "last_price": round(float(r["last_price"]), 2) if pd.notna(r["last_price"]) else None,
            }
            
        c_data = extract(c_row)
        p_data = extract(p_row)
        
        # Add visual bar ratios
        c_data["oi_ratio"] = round(c_data["oi"] / max_ce_oi, 3)
        c_data["vol_ratio"] = round(c_data["volume"] / max_ce_vol, 3)
        p_data["oi_ratio"] = round(p_data["oi"] / max_pe_oi, 3)
        p_data["vol_ratio"] = round(p_data["volume"] / max_pe_vol, 3)
        
        rows.append({
            "strike": float(s),
            "is_atm": is_atm,
            "is_call_wall": bool(call_wall and s == call_wall),
            "is_put_wall": bool(put_wall and s == put_wall),
            "is_max_pain": bool(max_pain and s == max_pain),
            "ce": c_data,
            "pe": p_data
        })
        
    tot_ce = int(ce["oi"].sum()) if not ce.empty else 0
    tot_pe = int(pe["oi"].sum()) if not pe.empty else 0
    
    return {
        "date": date,
        "expiry": expiry,
        "spot": spot,
        "timestamp": latest_ts,
        "rows": rows,
        "totals": {
            "total_ce_oi": tot_ce,
            "total_pe_oi": tot_pe,
            "pcr": round(tot_pe / tot_ce, 3) if tot_ce > 0 else 0,
            "call_wall": call_wall,
            "put_wall": put_wall,
            "max_pain": max_pain,
            "strikes_count": len(rows)
        }
    }


# ── Signals Feed & Inspector ──────────────────────────────────────────────────

@app.get("/api/signals")
def get_signals(
    date: Optional[str] = None,
    bias: Optional[str] = None,
    signal_type: Optional[str] = None,
    min_confidence: Optional[int] = None,
    min_strength: Optional[float] = None,
    limit: int = 100,
    offset: int = 0,
    symbol: str = "NIFTY"
):
    conn = _conn()
    
    where = ["symbol = ?"]
    params = [symbol]
    
    if date:
        where.append("DATE(fired_at) = ?")
        params.append(date)
    if bias and bias != "ALL":
        where.append("bias = ?")
        params.append(bias.upper())
    if signal_type and signal_type != "ALL":
        where.append("signal_type = ?")
        params.append(signal_type.upper())
    if min_confidence:
        where.append("llm_confidence >= ?")
        params.append(min_confidence)
    if min_strength:
        where.append("signal_strength >= ?")
        params.append(min_strength)
        
    where_sql = " AND ".join(where)
    
    # Query signals
    sql = f"""
        SELECT id, fired_at, symbol, expiry, strike, option_type,
               signal_type, signal_strength, oi_change, volume,
               iv, spot_price, bias, mode, llm_thesis, llm_bias,
               llm_confidence, outcome_7d, outcome_correct
        FROM signals
        WHERE {where_sql}
        ORDER BY fired_at DESC
        LIMIT ? OFFSET ?
    """
    params_paged = params + [limit, offset]
    rows = conn.execute(sql, params_paged).fetchall()
    
    # Summary stats for this filter
    count_sql = f"""
        SELECT COUNT(*) as total,
               SUM(CASE WHEN bias='BULLISH' THEN 1 ELSE 0 END) as bullish,
               SUM(CASE WHEN bias='BEARISH' THEN 1 ELSE 0 END) as bearish,
               SUM(CASE WHEN bias='NEUTRAL' THEN 1 ELSE 0 END) as neutral,
               SUM(CASE WHEN llm_thesis IS NOT NULL THEN 1 ELSE 0 END) as with_thesis
        FROM signals
        WHERE {where_sql}
    """
    stats_row = conn.execute(count_sql, params).fetchone()
    conn.close()
    
    signals = []
    for r in rows:
        d = dict(r)
        # Format IST time
        raw_ts = d["fired_at"]
        try:
            dt = datetime.strptime(raw_ts[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            d["fired_at_ist"] = (dt + timedelta(hours=5, minutes=30)).strftime("%d %b %H:%M IST")
        except Exception:
            d["fired_at_ist"] = raw_ts
        signals.append(d)
        
    return {
        "signals": signals,
        "stats": dict(stats_row) if stats_row else {
            "total": 0, "bullish": 0, "bearish": 0, "neutral": 0, "with_thesis": 0
        }
    }


@app.get("/api/signals/{signal_id}/context")
def get_signal_context(signal_id: int):
    conn = _conn()
    sig = conn.execute("SELECT * FROM signals WHERE id=?", (signal_id,)).fetchone()
    if not sig:
        conn.close()
        raise HTTPException(status_code=404, detail="Signal not found")
        
    sig_dict = dict(sig)
    fired_at = sig_dict["fired_at"]
    
    # Correlated news headlines (+- 15 mins)
    news_rows = conn.execute("""
        SELECT headline, source, published_at, url
        FROM news_raw
        WHERE fetched_at >= datetime(?, '-15 minutes')
          AND fetched_at <= datetime(?, '+15 minutes')
        ORDER BY published_at DESC LIMIT 10
    """, (fired_at, fired_at)).fetchall()
    
    # Surrounding spot movements (+- 30 mins)
    spot_rows = conn.execute("""
        SELECT timestamp, AVG(spot_price) as spot
        FROM options_chain
        WHERE timestamp >= datetime(?, '-30 minutes')
          AND timestamp <= datetime(?, '+30 minutes')
        GROUP BY timestamp
        ORDER BY timestamp ASC
    """, (fired_at, fired_at)).fetchall()
    
    conn.close()
    
    return {
        "signal": sig_dict,
        "news": [dict(r) for r in news_rows],
        "spot_context": [dict(r) for r in spot_rows]
    }


# ── Candlestick & Marker Charting (TradingView Format) ─────────────────────────

@app.get("/api/charts/candlesticks")
def get_candlestick_chart(date: Optional[str] = None, symbol: str = "NIFTY"):
    if not date:
        date = get_latest_date(symbol)
        
    conn = _conn()
    
    # 5-min snapshots from options_chain
    rows = conn.execute("""
        SELECT timestamp, AVG(spot_price) as spot, SUM(volume) as vol
        FROM options_chain
        WHERE symbol=? AND DATE(timestamp)=? AND spot_price IS NOT NULL
        GROUP BY timestamp
        ORDER BY timestamp ASC
    """, (symbol, date)).fetchall()
    
    if not rows:
        conn.close()
        return {"date": date, "candles": [], "markers": []}
        
    candles = []
    for i, r in enumerate(rows):
        ts_str = r["timestamp"]
        try:
            dt = datetime.strptime(ts_str[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            unix_sec = int(dt.timestamp())
        except Exception:
            continue
            
        spot = round(float(r["spot"]), 2)
        prev_spot = round(float(rows[i-1]["spot"]), 2) if i > 0 else spot
        
        # Build 5-min candle representation
        c_open = prev_spot
        c_close = spot
        c_high = max(c_open, c_close) + round(abs(c_close - c_open) * 0.15, 2)
        c_low = min(c_open, c_close) - round(abs(c_close - c_open) * 0.15, 2)
        
        candles.append({
            "time": unix_sec,
            "open": c_open,
            "high": c_high,
            "low": c_low,
            "close": c_close,
            "volume": int(r["vol"]) if r["vol"] else 0
        })
        
    # Flow markers from signals
    sig_rows = conn.execute("""
        SELECT id, fired_at, strike, option_type, signal_type, bias, signal_strength, llm_confidence
        FROM signals
        WHERE symbol=? AND DATE(fired_at)=?
        ORDER BY fired_at ASC
    """, (symbol, date)).fetchall()
    
    conn.close()
    
    markers = []
    for s in sig_rows:
        try:
            dt = datetime.strptime(s["fired_at"][:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            unix_sec = int(dt.timestamp())
        except Exception:
            continue
            
        bias = s["bias"]
        is_bull = bias == "BULLISH"
        
        markers.append({
            "time": unix_sec,
            "position": "belowBar" if is_bull else "aboveBar",
            "color": "#10B981" if is_bull else ("#F43F5E" if bias == "BEARISH" else "#F59E0B"),
            "shape": "arrowUp" if is_bull else ("arrowDown" if bias == "BEARISH" else "circle"),
            "text": f"{int(s['strike'])} {s['option_type']} {bias[:4]}",
            "id": s["id"],
            "strength": s["signal_strength"],
            "confidence": s["llm_confidence"]
        })
        
    return {
        "date": date,
        "candles": candles,
        "markers": markers
    }


# ── Analytics: OI Distribution, Skew, Intraday Timeline ───────────────────────

@app.get("/api/analytics/oi-distribution")
def get_oi_distribution(date: Optional[str] = None, symbol: str = "NIFTY"):
    if not date:
        date = get_latest_date(symbol)
        
    conn = _conn()
    ts_row = conn.execute("SELECT MAX(timestamp) as ts FROM options_chain WHERE symbol=? AND DATE(timestamp)=?", (symbol, date)).fetchone()
    if not ts_row or not ts_row["ts"]:
        conn.close()
        return {"data": []}
        
    latest_ts = ts_row["ts"]
    
    rows = conn.execute("""
        SELECT strike,
               SUM(CASE WHEN option_type='CE' THEN oi ELSE 0 END) as ce_oi,
               SUM(CASE WHEN option_type='PE' THEN oi ELSE 0 END) as pe_oi
        FROM options_chain
        WHERE symbol=? AND timestamp=?
        GROUP BY strike
        ORDER BY strike ASC
    """, (symbol, latest_ts)).fetchall()
    
    spot_row = conn.execute("SELECT AVG(spot_price) as spot FROM options_chain WHERE symbol=? AND timestamp=?", (symbol, latest_ts)).fetchone()
    conn.close()
    
    spot = spot_row["spot"] if spot_row else None
    
    data = []
    for r in rows:
        s = float(r["strike"])
        # Limit to ATM +- 25 strikes for clarity
        if spot and abs(s - spot) > 1500:
            continue
        data.append({
            "strike": int(s),
            "ce_oi": int(r["ce_oi"] or 0),
            "pe_oi": int(r["pe_oi"] or 0),
            "net_oi": int((r["ce_oi"] or 0) - (r["pe_oi"] or 0))
        })
        
    return {"date": date, "spot": spot, "data": data}


@app.get("/api/analytics/iv-skew")
def get_iv_skew(date: Optional[str] = None, expiry: Optional[str] = None, symbol: str = "NIFTY"):
    if not date:
        date = get_latest_date(symbol)
        
    conn = _conn()
    ts_row = conn.execute("SELECT MAX(timestamp) as ts FROM options_chain WHERE symbol=? AND DATE(timestamp)=?", (symbol, date)).fetchone()
    if not ts_row or not ts_row["ts"]:
        conn.close()
        return {"data": []}
    latest_ts = ts_row["ts"]
    
    if not expiry:
        exp_row = conn.execute("SELECT expiry FROM options_chain WHERE symbol=? AND timestamp=? ORDER BY expiry ASC LIMIT 1", (symbol, latest_ts)).fetchone()
        expiry = exp_row["expiry"] if exp_row else None
        
    df = pd.read_sql("""
        SELECT strike, option_type, iv
        FROM options_chain
        WHERE symbol=? AND timestamp=? AND expiry=? AND iv IS NOT NULL
        ORDER BY strike ASC
    """, conn, params=(symbol, latest_ts, expiry))
    
    spot_row = conn.execute("SELECT AVG(spot_price) as spot FROM options_chain WHERE symbol=? AND timestamp=?", (symbol, latest_ts)).fetchone()
    conn.close()
    
    if df.empty:
        return {"date": date, "expiry": expiry, "data": []}
        
    ce = df[df["option_type"] == "CE"].set_index("strike")["iv"]
    pe = df[df["option_type"] == "PE"].set_index("strike")["iv"]
    strikes = sorted(set(ce.index) | set(pe.index))
    
    spot = spot_row["spot"] if spot_row else None
    
    data = []
    for s in strikes:
        if spot and abs(s - spot) > 1500:
            continue
        data.append({
            "strike": int(s),
            "ce_iv": round(float(ce.get(s, 0)), 2) if s in ce and pd.notna(ce.get(s)) else None,
            "pe_iv": round(float(pe.get(s, 0)), 2) if s in pe and pd.notna(pe.get(s)) else None
        })
        
    return {"date": date, "expiry": expiry, "spot": spot, "data": data}


@app.get("/api/analytics/timeline")
def get_intraday_timeline(date: Optional[str] = None, top_n: int = 5, symbol: str = "NIFTY"):
    if not date:
        date = get_latest_date(symbol)
        
    conn = _conn()
    top_strikes = pd.read_sql("""
        SELECT strike, option_type, SUM(ABS(oi_change)) as tot
        FROM options_chain
        WHERE symbol=? AND DATE(timestamp)=? AND oi_change IS NOT NULL
        GROUP BY strike, option_type
        ORDER BY tot DESC LIMIT ?
    """, conn, params=(symbol, date, top_n))
    
    if top_strikes.empty:
        conn.close()
        return {"series": []}
        
    cond = " OR ".join(f"(strike={r.strike} AND option_type='{r.option_type}')" for r in top_strikes.itertuples())
    df = pd.read_sql(f"""
        SELECT timestamp, strike, option_type, oi_change, oi
        FROM options_chain
        WHERE symbol=? AND DATE(timestamp)=? AND ({cond})
        ORDER BY timestamp ASC
    """, conn, params=(symbol, date))
    conn.close()
    
    series_map = {}
    for r in df.itertuples():
        label = f"{int(r.strike)} {r.option_type}"
        if label not in series_map:
            series_map[label] = []
        try:
            dt = datetime.strptime(r.timestamp[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            time_ist = (dt + timedelta(hours=5, minutes=30)).strftime("%H:%M")
        except Exception:
            time_ist = r.timestamp[11:16]
            
        series_map[label].append({
            "time": time_ist,
            "oi_change": int(r.oi_change or 0),
            "oi": int(r.oi or 0)
        })
        
    return {"date": date, "series": series_map}


# ── Quantitative Backtesting Hub ──────────────────────────────────────────────

@app.get("/api/backtest/stats")
def get_backtest_stats(symbol: str = "NIFTY"):
    """
    Evaluates signal directional accuracy.
    Checks price movement 3-7 days after the signal was fired.
    Uses in-memory lookup of session spots for ultra-fast performance.
    """
    conn = _conn()
    
    # 1. Fetch daily spots map in a single fast query
    daily_spots = pd.read_sql("""
        SELECT DATE(timestamp) as dt, AVG(spot_price) as spot
        FROM options_chain
        WHERE symbol=? AND spot_price IS NOT NULL
        GROUP BY DATE(timestamp)
        ORDER BY dt ASC
    """, conn, params=(symbol,))
    
    spot_by_date = dict(zip(daily_spots["dt"], daily_spots["spot"]))
    sorted_dates = sorted(spot_by_date.keys())
    
    signals = conn.execute("""
        SELECT id, fired_at, strike, option_type, signal_type, signal_strength,
               spot_price, bias, llm_confidence, outcome_7d, outcome_correct
        FROM signals
        WHERE symbol=? AND spot_price IS NOT NULL
        ORDER BY fired_at ASC
    """, (symbol,)).fetchall()
    
    conn.close()
    
    if not signals:
        return {"total_evaluated": 0, "overall_win_rate": 0, "by_type": [], "by_confidence": [], "recent_trades": []}
        
    evaluated = []
    correct_count = 0
    type_stats = {}
    conf_stats = {}
    
    for s in signals:
        bias = s["bias"]
        sig_type = s["signal_type"]
        conf = s["llm_confidence"] or 3
        spot_at_fire = s["spot_price"]
        fired_at = s["fired_at"]
        sig_date = fired_at[:10]
        
        outcome_corr = s["outcome_correct"]
        outcome_7d = s["outcome_7d"]
        
        if outcome_corr is None and sig_date in sorted_dates:
            # Find trading date 3 to 7 trading days later
            idx = sorted_dates.index(sig_date)
            target_idx = min(idx + 5, len(sorted_dates) - 1)
            if target_idx > idx:
                future_date = sorted_dates[target_idx]
                f_spot = spot_by_date[future_date]
                ret_pct = ((f_spot - spot_at_fire) / spot_at_fire) * 100
                outcome_7d = round(ret_pct, 2)
                if bias == "BULLISH" and ret_pct > 0.2:
                    outcome_corr = 1
                elif bias == "BEARISH" and ret_pct < -0.2:
                    outcome_corr = 1
                elif bias == "NEUTRAL" and abs(ret_pct) <= 0.8:
                    outcome_corr = 1
                else:
                    outcome_corr = 0
                    
        if outcome_corr is not None:
            is_win = bool(outcome_corr)
            if is_win:
                correct_count += 1
                
            # By Type
            if sig_type not in type_stats:
                type_stats[sig_type] = {"total": 0, "wins": 0}
            type_stats[sig_type]["total"] += 1
            if is_win:
                type_stats[sig_type]["wins"] += 1
                
            # By Confidence
            c_key = f"{conf} Star"
            if c_key not in conf_stats:
                conf_stats[c_key] = {"total": 0, "wins": 0}
            conf_stats[c_key]["total"] += 1
            if is_win:
                conf_stats[c_key]["wins"] += 1
                
            evaluated.append({
                "id": s["id"],
                "fired_at": s["fired_at"],
                "strike": s["strike"],
                "option_type": s["option_type"],
                "type": sig_type,
                "bias": bias,
                "confidence": conf,
                "spot": spot_at_fire,
                "return_7d": outcome_7d,
                "correct": is_win
            })
            
    total_eval = len(evaluated)
    win_rate = round((correct_count / total_eval) * 100, 1) if total_eval > 0 else 0.0
    
    # Format type stats
    formatted_types = []
    for k, v in type_stats.items():
        rate = round((v["wins"] / v["total"]) * 100, 1) if v["total"] > 0 else 0
        formatted_types.append({"type": k, "total": v["total"], "wins": v["wins"], "win_rate": rate})
        
    formatted_conf = []
    for k, v in sorted(conf_stats.items()):
        rate = round((v["wins"] / v["total"]) * 100, 1) if v["total"] > 0 else 0
        formatted_conf.append({"confidence": k, "total": v["total"], "wins": v["wins"], "win_rate": rate})
        
    return {
        "total_evaluated": total_eval,
        "overall_win_rate": win_rate,
        "wins": correct_count,
        "losses": total_eval - correct_count,
        "by_type": formatted_types,
        "by_confidence": formatted_conf,
        "recent_trades": evaluated[-20:]
    }


# ── Cloud Sync Trigger ────────────────────────────────────────────────────────

@app.post("/api/sync")
def trigger_sync(background_tasks: BackgroundTasks):
    from sync_supabase import sync_data
    try:
        chain_c, sig_c = sync_data()
        return {"status": "success", "chain_imported": chain_c, "signals_imported": sig_c}
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)
