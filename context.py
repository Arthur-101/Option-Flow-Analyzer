# context.py — Market context builder for LLM reasoning
#
# Computes from data already in options_chain DB:
#   - RSI(14) on NIFTY spot price series (5-min closes)
#   - MACD(12, 26, 9) on same series
#   - PCR: intraday put/call OI ratio
#   - VWAP: session volume-weighted average price of spot
#   - Spot trend: where spot is relative to session open
#
# Output: a clean dict passed to llm_engine.py
# Nothing here modifies signals or triggers alerts.

import logging
import sqlite3
import numpy as np
from datetime import date, datetime, timezone
from config import DB_PATH

logger = logging.getLogger(__name__)


# ── DB helpers ─────────────────────────────────────────────────────────────────

def _get_spot_series(conn: sqlite3.Connection, symbol: str, date_str: str) -> list[float]:
    """
    Returns ordered list of spot_price values for today's session.
    One value per flush timestamp (5-min closes).
    """
    rows = conn.execute("""
        SELECT AVG(spot_price) as spot, timestamp
        FROM options_chain
        WHERE symbol = ?
          AND DATE(timestamp) = ?
          AND spot_price IS NOT NULL
          AND spot_price > 0
        GROUP BY timestamp
        ORDER BY timestamp ASC
    """, (symbol, date_str)).fetchall()
    return [r[0] for r in rows]


def _get_intraday_oi(conn: sqlite3.Connection, symbol: str, date_str: str) -> dict:
    """
    Returns total CE OI and PE OI for the latest flush today.
    Used for PCR computation.
    """
    result = conn.execute("""
        SELECT
            SUM(CASE WHEN option_type = 'CE' THEN oi ELSE 0 END) as total_ce_oi,
            SUM(CASE WHEN option_type = 'PE' THEN oi ELSE 0 END) as total_pe_oi
        FROM options_chain
        WHERE symbol = ?
          AND DATE(timestamp) = ?
          AND timestamp = (
              SELECT MAX(timestamp) FROM options_chain
              WHERE symbol = ? AND DATE(timestamp) = ?
          )
    """, (symbol, date_str, symbol, date_str)).fetchone()

    return {
        "ce_oi": result[0] or 0,
        "pe_oi": result[1] or 0,
    }


def _get_volume_series(conn: sqlite3.Connection, symbol: str, date_str: str) -> list[dict]:
    """
    Returns volume and spot per timestamp for VWAP computation.
    Uses total volume across all strikes per flush as proxy.
    """
    rows = conn.execute("""
        SELECT
            timestamp,
            AVG(spot_price) as spot,
            SUM(volume) as total_volume
        FROM options_chain
        WHERE symbol = ?
          AND DATE(timestamp) = ?
          AND spot_price IS NOT NULL
          AND volume IS NOT NULL
        GROUP BY timestamp
        ORDER BY timestamp ASC
    """, (symbol, date_str)).fetchall()
    return [{"spot": r[1], "volume": r[2]} for r in rows]


# ── Indicator computations ─────────────────────────────────────────────────────

def _compute_rsi(prices: list[float], period: int = 14) -> float | None:
    """
    RSI(14) using Wilder's smoothing method.
    Returns current RSI value or None if insufficient data.
    """
    if len(prices) < period + 1:
        return None

    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    # Initial averages
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    # Wilder smoothing for remaining values
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


def _compute_macd(prices: list[float],
                  fast: int = 12, slow: int = 26, signal: int = 9
                  ) -> dict | None:
    """
    MACD(12, 26, 9) using EMA.
    Returns dict with macd_line, signal_line, histogram or None if insufficient data.
    """
    if len(prices) < slow + signal:
        return None

    def ema(data, period):
        k = 2 / (period + 1)
        result = [data[0]]
        for price in data[1:]:
            result.append(price * k + result[-1] * (1 - k))
        return result

    ema_fast = ema(prices, fast)
    ema_slow = ema(prices, slow)

    macd_line = [f - s for f, s in zip(ema_fast, ema_slow)]
    # Signal line is EMA of macd_line
    macd_from_slow = macd_line[slow - 1:]
    if len(macd_from_slow) < signal:
        return None

    signal_line = ema(macd_from_slow, signal)
    current_macd = macd_from_slow[-1]
    current_signal = signal_line[-1]
    histogram = current_macd - current_signal

    return {
        "macd_line":   round(current_macd, 4),
        "signal_line": round(current_signal, 4),
        "histogram":   round(histogram, 4),
        # Interpretation helpers for LLM
        "crossover":   "bullish" if current_macd > current_signal else "bearish",
        "momentum":    "strengthening" if histogram > 0 else "weakening",
    }


def _compute_vwap(volume_series: list[dict]) -> float | None:
    """
    Session VWAP: sum(price * volume) / sum(volume)
    """
    if not volume_series:
        return None

    total_pv = sum(v["spot"] * v["volume"] for v in volume_series
                   if v["spot"] and v["volume"])
    total_v = sum(v["volume"] for v in volume_series if v["volume"])

    if total_v == 0:
        return None

    return round(total_pv / total_v, 2)


def _pcr_interpretation(pcr: float) -> str:
    """
    Real-world PCR interpretation thresholds.
    PCR > 1.3 → defensive/bearish market positioning
    PCR < 0.7 → aggressive/bullish market positioning
    0.7–1.3   → balanced, no strong directional bias
    """
    if pcr > 1.5:
        return "extreme_bearish_hedge"
    elif pcr > 1.3:
        return "defensive_bearish"
    elif pcr > 1.0:
        return "mild_put_bias"
    elif pcr > 0.7:
        return "balanced"
    elif pcr > 0.5:
        return "mild_call_bias"
    else:
        return "aggressive_bullish"


def _rsi_interpretation(rsi: float) -> str:
    if rsi >= 80:
        return "highly_overbought"
    elif rsi >= 70:
        return "overbought"
    elif rsi >= 60:
        return "upper_mid"
    elif rsi >= 40:
        return "neutral"
    elif rsi >= 30:
        return "lower_mid"
    elif rsi >= 20:
        return "oversold"
    else:
        return "highly_oversold"


# ── Main entry point ───────────────────────────────────────────────────────────

def build_context(symbol: str) -> dict:
    """
    Build full market context dict for LLM consumption.
    Called once per signal before LLM thesis generation.

    Returns a dict with all context fields.
    All values are None if insufficient data.
    """
    today = date.today().isoformat()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    try:
        spot_series = _get_spot_series(conn, symbol, today)
        oi_data = _get_intraday_oi(conn, symbol, today)
        vol_series = _get_volume_series(conn, symbol, today)
    finally:
        conn.close()

    # Current spot (latest value)
    current_spot = spot_series[-1] if spot_series else None
    session_open = spot_series[0] if spot_series else None

    # RSI
    rsi = _compute_rsi(spot_series)

    # MACD
    macd = _compute_macd(spot_series)

    # PCR
    ce_oi = oi_data["ce_oi"]
    pe_oi = oi_data["pe_oi"]
    pcr = round(pe_oi / ce_oi, 3) if ce_oi > 0 else None

    # VWAP
    vwap = _compute_vwap(vol_series)

    # Spot vs VWAP
    spot_vs_vwap = None
    if current_spot and vwap:
        spot_vs_vwap = "above_vwap" if current_spot > vwap else "below_vwap"

    # Session move
    session_move_pct = None
    if current_spot and session_open and session_open > 0:
        session_move_pct = round((current_spot - session_open) / session_open * 100, 2)

    context = {
        # Spot
        "symbol":              symbol,
        "current_spot":        round(current_spot, 2) if current_spot else None,
        "session_open":        round(session_open, 2) if session_open else None,
        "session_move_pct":    session_move_pct,
        "spot_series_length":  len(spot_series),

        # RSI
        "rsi":                 rsi,
        "rsi_state":           _rsi_interpretation(rsi) if rsi is not None else None,

        # MACD
        "macd":                macd,

        # PCR
        "pcr":                 pcr,
        "pcr_state":           _pcr_interpretation(pcr) if pcr is not None else None,
        "total_ce_oi":         ce_oi,
        "total_pe_oi":         pe_oi,

        # VWAP
        "vwap":                vwap,
        "spot_vs_vwap":        spot_vs_vwap,

        # Metadata
        "computed_at_utc":     datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "date":                today,
    }

    logger.info(
        "[%s] Context built — spot=%.2f RSI=%s PCR=%s VWAP=%s spot_vs_vwap=%s",
        symbol,
        current_spot or 0,
        rsi,
        pcr,
        vwap,
        spot_vs_vwap,
    )

    return context