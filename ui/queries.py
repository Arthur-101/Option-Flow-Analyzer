# ui/queries.py — DB read queries for OFA dashboard
import sqlite3, pandas as pd
from datetime import date
from config import DB_PATH

def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c

def get_latest_spot(symbol="NIFTY"):
    c = _conn()
    r = c.execute("SELECT spot_price FROM options_chain WHERE symbol=? AND spot_price IS NOT NULL ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
    c.close()
    return r["spot_price"] if r else None

def get_latest_timestamp(symbol="NIFTY"):
    c = _conn()
    r = c.execute("SELECT MAX(timestamp) as ts FROM options_chain WHERE symbol=?", (symbol,)).fetchone()
    c.close()
    return r["ts"] if r else None

def get_pcr(symbol="NIFTY"):
    c = _conn()
    r = c.execute("""SELECT SUM(CASE WHEN option_type='PE' THEN oi ELSE 0 END) pe,
                            SUM(CASE WHEN option_type='CE' THEN oi ELSE 0 END) ce
                     FROM options_chain WHERE symbol=? AND DATE(timestamp)=DATE('now')
                     AND timestamp=(SELECT MAX(timestamp) FROM options_chain WHERE symbol=? AND DATE(timestamp)=DATE('now'))""",
                  (symbol, symbol)).fetchone()
    c.close()
    if r and r["ce"] and r["ce"] > 0: return round(r["pe"] / r["ce"], 3)
    return None

def get_spot_series(symbol="NIFTY", date_str=None):
    if not date_str: date_str = date.today().isoformat()
    c = _conn()
    df = pd.read_sql("SELECT AVG(spot_price) as spot, timestamp FROM options_chain WHERE symbol=? AND DATE(timestamp)=? AND spot_price IS NOT NULL GROUP BY timestamp ORDER BY timestamp ASC",
                     c, params=(symbol, date_str))
    c.close()
    return df

def get_latest_chain(symbol="NIFTY"):
    c = _conn()
    df = pd.read_sql("""SELECT strike,option_type,expiry,oi,oi_change,volume,iv,last_price,spot_price,timestamp
                        FROM options_chain WHERE symbol=? AND DATE(timestamp)=DATE('now')
                        AND timestamp=(SELECT MAX(timestamp) FROM options_chain WHERE symbol=? AND DATE(timestamp)=DATE('now'))
                        ORDER BY strike ASC""", c, params=(symbol, symbol))
    c.close()
    return df

def get_available_expiries(symbol="NIFTY"):
    c = _conn()
    rows = c.execute("SELECT DISTINCT expiry FROM options_chain WHERE symbol=? AND DATE(timestamp)=DATE('now') ORDER BY expiry ASC", (symbol,)).fetchall()
    c.close()
    return [r["expiry"] for r in rows]

def get_oi_by_strike(symbol="NIFTY"):
    df = get_latest_chain(symbol)
    if df.empty: return df
    return df.pivot_table(index="strike", columns="option_type", values="oi", aggfunc="sum").reset_index().fillna(0)

def get_iv_skew(symbol="NIFTY", expiry=None):
    c = _conn()
    q = """SELECT strike,option_type,iv,expiry FROM options_chain WHERE symbol=? AND DATE(timestamp)=DATE('now')
           AND timestamp=(SELECT MAX(timestamp) FROM options_chain WHERE symbol=? AND DATE(timestamp)=DATE('now'))
           AND iv IS NOT NULL"""
    p = [symbol, symbol]
    if expiry: q += " AND expiry=?"; p.append(expiry)
    q += " ORDER BY strike ASC"
    df = pd.read_sql(q, c, params=p)
    c.close()
    return df

def get_intraday_oi_timeline(symbol="NIFTY", top_n=5):
    c = _conn()
    top = pd.read_sql("SELECT strike,option_type,SUM(ABS(oi_change)) tot FROM options_chain WHERE symbol=? AND DATE(timestamp)=DATE('now') AND oi_change IS NOT NULL GROUP BY strike,option_type ORDER BY tot DESC LIMIT ?",
                      c, params=(symbol, top_n))
    if top.empty: c.close(); return pd.DataFrame()
    cond = " OR ".join(f"(strike={r.strike} AND option_type='{r.option_type}')" for r in top.itertuples())
    df = pd.read_sql(f"SELECT timestamp,strike,option_type,oi_change,oi FROM options_chain WHERE symbol=? AND DATE(timestamp)=DATE('now') AND ({cond}) ORDER BY timestamp ASC", c, params=(symbol,))
    c.close()
    return df

def get_today_signals(symbol="NIFTY"):
    c = _conn()
    df = pd.read_sql("SELECT * FROM signals WHERE symbol=? AND DATE(fired_at)=DATE('now') ORDER BY fired_at DESC", c, params=(symbol,))
    c.close()
    return df

def get_all_signals(symbol="NIFTY", days=7):
    c = _conn()
    df = pd.read_sql("SELECT * FROM signals WHERE symbol=? AND DATE(fired_at)>=DATE('now',?) ORDER BY fired_at DESC", c, params=(symbol, f"-{days} days"))
    c.close()
    return df

def get_signal_stats(symbol="NIFTY"):
    c = _conn()
    today = date.today().isoformat()
    r = c.execute("""SELECT COUNT(*) total,
                            SUM(CASE WHEN DATE(fired_at)=? THEN 1 ELSE 0 END) today,
                            SUM(CASE WHEN bias='BULLISH' AND DATE(fired_at)=? THEN 1 ELSE 0 END) bullish,
                            SUM(CASE WHEN bias='BEARISH' AND DATE(fired_at)=? THEN 1 ELSE 0 END) bearish,
                            SUM(CASE WHEN llm_thesis IS NOT NULL AND DATE(fired_at)=? THEN 1 ELSE 0 END) with_thesis
                     FROM signals WHERE symbol=?""", (today,today,today,today,symbol)).fetchone()
    c.close()
    return dict(r) if r else {}

def get_news_for_signal(signal_id):
    c = _conn()
    rows = c.execute("""SELECT headline,source,published_at FROM news_raw
                        WHERE fetched_at>=(SELECT datetime(fired_at,'-10 minutes') FROM signals WHERE id=?)
                        AND fetched_at<=(SELECT datetime(fired_at,'+10 minutes') FROM signals WHERE id=?)
                        ORDER BY published_at DESC LIMIT 8""", (signal_id, signal_id)).fetchall()
    c.close()
    return [dict(r) for r in rows]

def get_db_stats():
    c = _conn()
    r = c.execute("SELECT COUNT(*) total_rows,COUNT(DISTINCT DATE(timestamp)) trading_days,MIN(timestamp) earliest,MAX(timestamp) latest FROM options_chain").fetchone()
    c.close()
    return dict(r) if r else {}