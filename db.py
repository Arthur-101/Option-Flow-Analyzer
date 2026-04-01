# db.py — Database setup and operations

import sqlite3
import logging
from config import (
    DB_PATH,
    RETENTION_OPTIONS_CHAIN_DAYS,
    RETENTION_NEWS_RAW_DAYS,
    RETENTION_NEWS_SUMMARIES_DAYS,
)

logger = logging.getLogger(__name__)


# ── Connection helper ──────────────────────────────────────────────────────────

def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


# ── Schema creation ────────────────────────────────────────────────────────────

def init_db() -> None:
    """Create all tables and indexes if they don't exist yet."""
    conn = get_connection()
    with conn:
        conn.executescript("""
            -- Table 1: raw options chain snapshot every 5 min
            CREATE TABLE IF NOT EXISTS options_chain (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   DATETIME NOT NULL,
                symbol      TEXT NOT NULL,
                expiry      DATE NOT NULL,
                strike      REAL NOT NULL,
                option_type TEXT NOT NULL,   -- 'CE' or 'PE'
                oi          INTEGER,
                oi_change   INTEGER,         -- vs previous snapshot (intraday only)
                volume      INTEGER,
                iv          REAL,            -- implied volatility %
                last_price  REAL,
                spot_price  REAL
            );

            CREATE INDEX IF NOT EXISTS idx_oc_timestamp
                ON options_chain(timestamp);
            CREATE INDEX IF NOT EXISTS idx_oc_symbol_strike
                ON options_chain(symbol, strike, option_type, expiry);
            CREATE INDEX IF NOT EXISTS idx_oc_date
                ON options_chain(DATE(timestamp), symbol);

            -- Table 2: raw news headlines
            CREATE TABLE IF NOT EXISTS news_raw (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                fetched_at   DATETIME NOT NULL,
                symbol       TEXT NOT NULL,
                headline     TEXT NOT NULL,
                source       TEXT,
                url          TEXT,
                published_at DATETIME
            );

            -- Table 3: LLM-generated news summaries
            CREATE TABLE IF NOT EXISTS news_summaries (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at         DATETIME NOT NULL,
                signal_id          INTEGER,
                symbol             TEXT NOT NULL,
                summary            TEXT NOT NULL,
                news_window_hours  INTEGER
            );

            -- Table 4: detected anomaly signals (never deleted)
            CREATE TABLE IF NOT EXISTS signals (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                fired_at         DATETIME NOT NULL,      -- UTC
                symbol           TEXT NOT NULL,
                expiry           DATE,
                strike           REAL,
                option_type      TEXT,                   -- 'CE' or 'PE'
                signal_type      TEXT NOT NULL,          -- see signal types below
                signal_strength  REAL,                   -- z-score or percentile rank
                oi_change        INTEGER,                -- raw value that triggered
                volume           INTEGER,                -- raw volume at trigger
                iv               REAL,                   -- IV at trigger time
                spot_price       REAL,                   -- NIFTY spot at trigger
                bias             TEXT,                   -- 'BULLISH', 'BEARISH', 'NEUTRAL'
                mode             TEXT,                   -- 'BOOTSTRAP' or 'FULL'
                llm_thesis       TEXT,                   -- NULL until Week 3
                llm_bias         TEXT,
                llm_confidence   INTEGER,                -- 1-5
                news_summary_id  INTEGER,
                outcome_7d       REAL,                   -- % price change 7 days later
                outcome_correct  BOOLEAN,
                outcome_filled_at DATETIME
            );

            -- Signal types reference:
            -- OI_BUILDUP   : oi_change > 0 + volume > 0 → new positions opening (directional)
            -- OI_UNWIND    : oi_change < 0 + volume > 0 → positions closing (potential reversal)
            -- VOLUME_SPIKE : high volume but oi_change ≈ 0 → intraday speculation
            -- IV_SPIKE     : IV significantly above session average for nearby strikes
        """)
    conn.close()
    logger.info("Database initialised at %s", DB_PATH)


# ── Insert helpers ─────────────────────────────────────────────────────────────

def insert_options_rows(rows: list[dict]) -> None:
    if not rows:
        return
    sql = """
        INSERT INTO options_chain
            (timestamp, symbol, expiry, strike, option_type,
             oi, oi_change, volume, iv, last_price, spot_price)
        VALUES
            (:timestamp, :symbol, :expiry, :strike, :option_type,
             :oi, :oi_change, :volume, :iv, :last_price, :spot_price)
    """
    conn = get_connection()
    with conn:
        conn.executemany(sql, rows)
    conn.close()
    logger.info("Inserted %d rows into options_chain", len(rows))


def insert_signal(signal: dict) -> int:
    """Insert a signal row and return the new id."""
    sql = """
        INSERT INTO signals
            (fired_at, symbol, expiry, strike, option_type,
             signal_type, signal_strength, oi_change, volume,
             iv, spot_price, bias, mode,
             llm_thesis, llm_bias, llm_confidence, news_summary_id)
        VALUES
            (:fired_at, :symbol, :expiry, :strike, :option_type,
             :signal_type, :signal_strength, :oi_change, :volume,
             :iv, :spot_price, :bias, :mode,
             :llm_thesis, :llm_bias, :llm_confidence, :news_summary_id)
    """
    conn = get_connection()
    with conn:
        cur = conn.execute(sql, signal)
        new_id = cur.lastrowid
    conn.close()
    logger.info(
        "Signal inserted: id=%d type=%s %s %s %.0f %s strength=%.2f bias=%s",
        new_id, signal["signal_type"], signal["symbol"],
        signal.get("expiry", ""), signal.get("strike", 0),
        signal.get("option_type", ""), signal.get("signal_strength", 0),
        signal.get("bias", "")
    )
    return new_id


# ── Retention cleanup ──────────────────────────────────────────────────────────

def purge_old_data() -> None:
    conn = get_connection()
    with conn:
        conn.execute(
            "DELETE FROM options_chain WHERE timestamp < datetime('now', ?)",
            (f"-{RETENTION_OPTIONS_CHAIN_DAYS} days",)
        )
        conn.execute(
            "DELETE FROM news_raw WHERE fetched_at < datetime('now', ?)",
            (f"-{RETENTION_NEWS_RAW_DAYS} days",)
        )
        conn.execute(
            "DELETE FROM news_summaries WHERE created_at < datetime('now', ?)",
            (f"-{RETENTION_NEWS_SUMMARIES_DAYS} days",)
        )
    conn.close()
    logger.info("Purge complete")


# ── Read helpers (used by ws_feed.py) ─────────────────────────────────────────

def get_latest_oi_snapshot(symbol: str) -> dict[tuple, int]:
    """
    Return {(strike, option_type, expiry): oi} for the most recent
    timestamp in the DB. Used by flush_to_db() to compute oi_change.
    """
    conn = get_connection()
    rows = conn.execute("""
        SELECT strike, option_type, expiry, oi
        FROM options_chain
        WHERE symbol = ?
          AND timestamp = (
              SELECT MAX(timestamp) FROM options_chain WHERE symbol = ?
          )
    """, (symbol, symbol)).fetchall()
    conn.close()
    return {(r["strike"], r["option_type"], r["expiry"]): r["oi"] for r in rows}


# ── Read helpers (used by detector.py) ────────────────────────────────────────

def get_today_snapshot(symbol: str, date_str: str) -> list[dict]:
    """
    Returns the latest flush rows for today — one row per strike/expiry/type.
    This is what the detector analyses each run.
    """
    conn = get_connection()
    rows = conn.execute("""
        SELECT *
        FROM options_chain
        WHERE symbol = ?
          AND DATE(timestamp) = ?
          AND timestamp = (
              SELECT MAX(timestamp)
              FROM options_chain
              WHERE symbol = ? AND DATE(timestamp) = ?
          )
    """, (symbol, date_str, symbol, date_str)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_intraday_oi_changes(symbol: str, date_str: str) -> list[dict]:
    """
    Returns all non-NULL oi_change rows for today.
    Used to compute intraday percentile rank in bootstrap mode.
    """
    conn = get_connection()
    rows = conn.execute("""
        SELECT strike, option_type, expiry, oi_change, volume, iv, spot_price, timestamp
        FROM options_chain
        WHERE symbol = ?
          AND DATE(timestamp) = ?
          AND oi_change IS NOT NULL
        ORDER BY timestamp ASC
    """, (symbol, date_str)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_historical_oi_changes(symbol: str, strike: float,
                               option_type: str, expiry: str,
                               days: int = 20) -> list[int]:
    """
    Returns daily max oi_change values for a specific strike over
    the last N trading days. Used for rolling average in full mode.
    """
    conn = get_connection()
    rows = conn.execute("""
        SELECT DATE(timestamp) as day, MAX(ABS(oi_change)) as max_oi_change
        FROM options_chain
        WHERE symbol = ?
          AND strike = ?
          AND option_type = ?
          AND expiry = ?
          AND oi_change IS NOT NULL
          AND DATE(timestamp) < DATE('now')
        GROUP BY DATE(timestamp)
        ORDER BY day DESC
        LIMIT ?
    """, (symbol, strike, option_type, expiry, days)).fetchall()
    conn.close()
    return [r["max_oi_change"] for r in rows if r["max_oi_change"] is not None]


def get_historical_volumes(symbol: str, strike: float,
                            option_type: str, expiry: str,
                            days: int = 20) -> list[int]:
    """
    Returns daily max volume for a strike over last N trading days.
    Used for rolling average volume baseline.
    """
    conn = get_connection()
    rows = conn.execute("""
        SELECT DATE(timestamp) as day, MAX(volume) as max_volume
        FROM options_chain
        WHERE symbol = ?
          AND strike = ?
          AND option_type = ?
          AND expiry = ?
          AND DATE(timestamp) < DATE('now')
        GROUP BY DATE(timestamp)
        ORDER BY day DESC
        LIMIT ?
    """, (symbol, strike, option_type, expiry, days)).fetchall()
    conn.close()
    return [r["max_volume"] for r in rows if r["max_volume"] is not None]


def count_trading_days_in_db(symbol: str) -> int:
    """
    Returns how many distinct trading days exist in the DB for this symbol.
    Used to decide bootstrap vs full mode.
    """
    conn = get_connection()
    result = conn.execute("""
        SELECT COUNT(DISTINCT DATE(timestamp)) as days
        FROM options_chain
        WHERE symbol = ?
          AND DATE(timestamp) < DATE('now')
    """, (symbol,)).fetchone()
    conn.close()
    return result["days"] if result else 0


def signal_already_fired_today(symbol: str, strike: float,
                                option_type: str, signal_type: str,
                                date_str: str) -> bool:
    """
    Prevents duplicate signals for the same strike/type within one trading day.
    """
    conn = get_connection()
    result = conn.execute("""
        SELECT COUNT(*) as cnt
        FROM signals
        WHERE symbol = ?
          AND strike = ?
          AND option_type = ?
          AND signal_type = ?
          AND DATE(fired_at) = ?
    """, (symbol, strike, option_type, signal_type, date_str)).fetchone()
    conn.close()
    return result["cnt"] > 0