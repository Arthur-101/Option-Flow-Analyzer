# db.py — Database setup and operations

import sqlite3
import logging
from datetime import datetime
from config import (
    DB_PATH,
    RETENTION_OPTIONS_CHAIN_DAYS,
    RETENTION_NEWS_RAW_DAYS,
    RETENTION_NEWS_SUMMARIES_DAYS,
)

logger = logging.getLogger(__name__)


# ── Connection helper ──────────────────────────────────────────────────────────

def get_connection() -> sqlite3.Connection:
    """Return a SQLite connection with row_factory set for dict-like access."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # safe for concurrent reads
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ── Schema creation ───────────────────────────────────────────────────────────

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
                option_type TEXT NOT NULL,      -- 'CE' or 'PE'
                oi          INTEGER,
                oi_change   INTEGER,            -- vs previous pull
                volume      INTEGER,
                iv          REAL,               -- implied volatility %
                last_price  REAL,
                spot_price  REAL
            );

            CREATE INDEX IF NOT EXISTS idx_oc_timestamp
                ON options_chain(timestamp);

            CREATE INDEX IF NOT EXISTS idx_oc_symbol_strike
                ON options_chain(symbol, strike, option_type, expiry);

            -- Table 2: raw news headlines (fetched when a signal fires)
            CREATE TABLE IF NOT EXISTS news_raw (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                fetched_at   DATETIME NOT NULL,
                symbol       TEXT NOT NULL,
                headline     TEXT NOT NULL,
                source       TEXT,
                url          TEXT,
                published_at DATETIME
            );

            -- Table 3: LLM-generated 2-sentence news summaries
            CREATE TABLE IF NOT EXISTS news_summaries (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at         DATETIME NOT NULL,
                signal_id          INTEGER,        -- FK → signals
                symbol             TEXT NOT NULL,
                summary            TEXT NOT NULL,
                news_window_hours  INTEGER
            );

            -- Table 4: every anomaly flagged (never deleted)
            CREATE TABLE IF NOT EXISTS signals (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                fired_at          DATETIME NOT NULL,
                symbol            TEXT NOT NULL,
                expiry            DATE,
                strike            REAL,
                option_type       TEXT,            -- 'CE', 'PE', or 'INDEX'
                signal_type       TEXT NOT NULL,   -- 'OI_SURGE', 'VOLUME_SPIKE', etc.
                signal_strength   REAL,            -- z-score or multiplier vs avg
                llm_thesis        TEXT,
                llm_bias          TEXT,            -- 'BULLISH', 'BEARISH', 'NEUTRAL'
                llm_confidence    INTEGER,         -- 1–5
                news_summary_id   INTEGER,         -- FK → news_summaries
                outcome_7d        REAL,            -- % price change 7 days later
                outcome_correct   BOOLEAN,
                outcome_filled_at DATETIME
            );
        """)
    conn.close()
    logger.info("Database initialised at %s", DB_PATH)


# ── Insert helpers ─────────────────────────────────────────────────────────────

def insert_options_rows(rows: list[dict]) -> None:
    """
    Bulk-insert a list of options_chain dicts.

    Each dict must contain:
        timestamp, symbol, expiry, strike, option_type,
        oi, oi_change, volume, iv, last_price, spot_price
    """
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
             signal_type, signal_strength, llm_thesis,
             llm_bias, llm_confidence, news_summary_id)
        VALUES
            (:fired_at, :symbol, :expiry, :strike, :option_type,
             :signal_type, :signal_strength, :llm_thesis,
             :llm_bias, :llm_confidence, :news_summary_id)
    """
    conn = get_connection()
    with conn:
        cur = conn.execute(sql, signal)
        new_id = cur.lastrowid
    conn.close()
    logger.info("Signal inserted: id=%d  type=%s  symbol=%s",
                new_id, signal["signal_type"], signal["symbol"])
    return new_id


# ── Retention cleanup ──────────────────────────────────────────────────────────

def purge_old_data() -> None:
    """Delete rows older than the configured retention windows."""
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
    logger.info("Purge complete — old rows removed")


# ── Read helpers (used by anomaly detector later) ─────────────────────────────

def get_latest_oi_snapshot(symbol: str) -> dict[tuple, int]:
    """
    Return a dict of {(strike, option_type, expiry): oi}
    for the most recent pull of a given symbol.
    Used by ingestion.py to compute oi_change.
    """
    conn = get_connection()
    sql = """
        SELECT strike, option_type, expiry, oi
        FROM options_chain
        WHERE symbol = ?
          AND timestamp = (
              SELECT MAX(timestamp)
              FROM options_chain
              WHERE symbol = ?
          )
    """
    rows = conn.execute(sql, (symbol, symbol)).fetchall()
    conn.close()
    return {(r["strike"], r["option_type"], r["expiry"]): r["oi"] for r in rows}
