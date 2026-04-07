# ui/queries.py — Database read queries for the Streamlit dashboard
#
# All UI data access goes through here.
# Never writes to DB — read-only.

import sqlite3
import pandas as pd
from datetime import date, datetime, timezone
from config import DB_PATH


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ── Live metrics ───────────────────────────────────────────────────────────────

def get_latest_spot(symbol: str = "NIFTY") -> float | None:
    conn = _conn()
    result = conn.execute("""
        SELECT spot_price FROM options_chain
        WHERE symbol = ? AND spot_price IS NOT NULL
        ORDER BY timestamp DESC LIMIT 1
    """, (symbol,)).fetchone()
    conn.close()
    return result["spot_price"] if result else None


def get_latest_timestamp(symbol: str = "NIFTY") -> str | None:
    conn = _conn()
    result = conn.execute("""
        SELECT MAX(timestamp) as ts FROM options_chain WHERE symbol = ?
    """, (symbol,)).fetchone()
    conn.close()
    return result["ts"] if result else None


def get_pcr(symbol: str = "NIFTY") -> float | None:
    """Put/Call Ratio from latest flush."""
    conn = _conn()
    result = conn.execute("""
        SELECT
            SUM(CASE WHEN option_type = 'PE' THEN oi ELSE 0 END) as pe_oi,
            SUM(CASE WHEN option_type = 'CE' THEN oi ELSE 0 END) as ce_oi
        FROM options_chain
        WHERE symbol = ?
          AND DATE(timestamp) = DATE('now')
          AND timestamp = (
              SELECT MAX(timestamp) FROM options_chain
              WHERE symbol = ? AND DATE(timestamp) = DATE('now')
          )
    """, (symbol, symbol)).fetchone()
    conn.close()
    if result and result["ce_oi"] and result["ce_oi"] > 0:
        return round(result["pe_oi"] / result["ce_oi"], 3)
    return None


def get_spot_series(symbol: str = "NIFTY", date_str: str = None) -> pd.DataFrame:
    """Returns spot price series for the day — for RSI/MACD computation."""
    if not date_str:
        date_str = date.today().isoformat()
    conn = _conn()
    df = pd.read_sql("""
        SELECT AVG(spot_price) as spot, timestamp
        FROM options_chain
        WHERE symbol = ?
          AND DATE(timestamp) = ?
          AND spot_price IS NOT NULL
        GROUP BY timestamp
        ORDER BY timestamp ASC
    """, conn, params=(symbol, date_str))
    conn.close()
    return df


# ── Options chain ──────────────────────────────────────────────────────────────

def get_latest_chain(symbol: str = "NIFTY") -> pd.DataFrame:
    """Latest full options chain snapshot."""
    conn = _conn()
    df = pd.read_sql("""
        SELECT strike, option_type, expiry, oi, oi_change,
               volume, iv, last_price, spot_price, timestamp
        FROM options_chain
        WHERE symbol = ?
          AND DATE(timestamp) = DATE('now')
          AND timestamp = (
              SELECT MAX(timestamp) FROM options_chain
              WHERE symbol = ? AND DATE(timestamp) = DATE('now')
          )
        ORDER BY strike ASC
    """, conn, params=(symbol, symbol))
    conn.close()
    return df


def get_oi_by_strike(symbol: str = "NIFTY") -> pd.DataFrame:
    """CE and PE OI per strike for the OI distribution chart."""
    df = get_latest_chain(symbol)
    if df.empty:
        return df
    pivot = df.pivot_table(
        index="strike",
        columns="option_type",
        values="oi",
        aggfunc="sum"
    ).reset_index().fillna(0)
    return pivot


def get_iv_skew(symbol: str = "NIFTY", expiry: str = None) -> pd.DataFrame:
    """IV across strikes for a given expiry — for the IV skew chart."""
    conn = _conn()
    query = """
        SELECT strike, option_type, iv, expiry
        FROM options_chain
        WHERE symbol = ?
          AND DATE(timestamp) = DATE('now')
          AND timestamp = (
              SELECT MAX(timestamp) FROM options_chain
              WHERE symbol = ? AND DATE(timestamp) = DATE('now')
          )
          AND iv IS NOT NULL
    """
    params = [symbol, symbol]
    if expiry:
        query += " AND expiry = ?"
        params.append(expiry)
    query += " ORDER BY strike ASC"
    df = pd.read_sql(query, conn, params=params)
    conn.close()
    return df


def get_intraday_oi_timeline(symbol: str = "NIFTY", top_n: int = 5) -> pd.DataFrame:
    """
    OI change timeline for top N strikes by total absolute OI change today.
    Used for the intraday OI timeline chart.
    """
    conn = _conn()
    # Find top N most active strikes by absolute OI change
    top_strikes = pd.read_sql("""
        SELECT strike, option_type,
               SUM(ABS(oi_change)) as total_oi_change
        FROM options_chain
        WHERE symbol = ?
          AND DATE(timestamp) = DATE('now')
          AND oi_change IS NOT NULL
        GROUP BY strike, option_type
        ORDER BY total_oi_change DESC
        LIMIT ?
    """, conn, params=(symbol, top_n))

    if top_strikes.empty:
        conn.close()
        return pd.DataFrame()

    # Build filter
    conditions = " OR ".join(
        f"(strike={row.strike} AND option_type='{row.option_type}')"
        for row in top_strikes.itertuples()
    )

    df = pd.read_sql(f"""
        SELECT timestamp, strike, option_type, oi_change, oi
        FROM options_chain
        WHERE symbol = ?
          AND DATE(timestamp) = DATE('now')
          AND ({conditions})
        ORDER BY timestamp ASC
    """, conn, params=(symbol,))
    conn.close()
    return df


def get_available_expiries(symbol: str = "NIFTY") -> list[str]:
    """Returns list of available expiries in current chain."""
    conn = _conn()
    rows = conn.execute("""
        SELECT DISTINCT expiry FROM options_chain
        WHERE symbol = ?
          AND DATE(timestamp) = DATE('now')
        ORDER BY expiry ASC
    """, (symbol,)).fetchall()
    conn.close()
    return [r["expiry"] for r in rows]


# ── Signals ────────────────────────────────────────────────────────────────────

def get_today_signals(symbol: str = "NIFTY") -> pd.DataFrame:
    """All signals fired today, newest first."""
    conn = _conn()
    df = pd.read_sql("""
        SELECT id, fired_at, signal_type, strike, option_type, expiry,
               signal_strength, bias, mode, oi_change, volume, iv,
               spot_price, llm_thesis, llm_bias, llm_confidence
        FROM signals
        WHERE symbol = ?
          AND DATE(fired_at) = DATE('now')
        ORDER BY fired_at DESC
    """, conn, params=(symbol,))
    conn.close()
    return df


def get_all_signals(symbol: str = "NIFTY", days: int = 7) -> pd.DataFrame:
    """All signals for the last N days."""
    conn = _conn()
    df = pd.read_sql("""
        SELECT id, fired_at, signal_type, strike, option_type, expiry,
               signal_strength, bias, mode, oi_change, volume, iv,
               spot_price, llm_thesis, llm_bias, llm_confidence
        FROM signals
        WHERE symbol = ?
          AND DATE(fired_at) >= DATE('now', ?)
        ORDER BY fired_at DESC
    """, conn, params=(symbol, f"-{days} days"))
    conn.close()
    return df


def get_signal_stats(symbol: str = "NIFTY") -> dict:
    """Summary stats for signals table."""
    conn = _conn()
    today = date.today().isoformat()
    result = conn.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN DATE(fired_at) = ? THEN 1 ELSE 0 END) as today,
            SUM(CASE WHEN bias = 'BULLISH' AND DATE(fired_at) = ? THEN 1 ELSE 0 END) as bullish_today,
            SUM(CASE WHEN bias = 'BEARISH' AND DATE(fired_at) = ? THEN 1 ELSE 0 END) as bearish_today,
            SUM(CASE WHEN llm_thesis IS NOT NULL AND DATE(fired_at) = ? THEN 1 ELSE 0 END) as with_thesis
        FROM signals WHERE symbol = ?
    """, (today, today, today, today, symbol)).fetchone()
    conn.close()
    return dict(result) if result else {}


def get_news_for_signal(signal_id: int) -> list[dict]:
    """Fetch news headlines stored around a signal's time."""
    conn = _conn()
    rows = conn.execute("""
        SELECT headline, source, published_at FROM news_raw
        WHERE fetched_at >= (
            SELECT datetime(fired_at, '-10 minutes') FROM signals WHERE id = ?
        )
        AND fetched_at <= (
            SELECT datetime(fired_at, '+10 minutes') FROM signals WHERE id = ?
        )
        ORDER BY published_at DESC
        LIMIT 8
    """, (signal_id, signal_id)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── DB health ──────────────────────────────────────────────────────────────────

def get_db_stats() -> dict:
    conn = _conn()
    result = conn.execute("""
        SELECT
            COUNT(*) as total_rows,
            COUNT(DISTINCT DATE(timestamp)) as trading_days,
            MIN(timestamp) as earliest,
            MAX(timestamp) as latest
        FROM options_chain
    """).fetchone()
    conn.close()
    return dict(result) if result else {}