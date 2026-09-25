# sync_supabase.py — Smart Delta Sync from Supabase into local SQLite
#
# Downloads only rows newer than the latest local timestamp.
# Uses INSERT OR IGNORE to guarantee zero duplicates.
# Called manually or from the Streamlit sidebar button.

import os
import sqlite3
import logging
from supabase import create_client
from dotenv import load_dotenv
from config import DB_PATH

load_dotenv()
logger = logging.getLogger(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")


def get_max_local_timestamp() -> str | None:
    """Return the latest timestamp in the local options_chain table."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT MAX(timestamp) FROM options_chain")
    row = cur.fetchone()
    conn.close()
    return row[0] if row and row[0] else None


def sync_options_chain() -> int:
    """
    Delta-sync options_chain from Supabase → local SQLite.
    Returns the number of new rows imported.
    """
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set in .env")

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    latest_local = get_max_local_timestamp()

    print(f"🔄 Syncing options_chain from Supabase...")
    print(f"   Latest local timestamp: {latest_local or 'Empty DB — full sync'}")

    # Fetch only rows newer than what we already have
    query = sb.table("options_chain").select("*")
    if latest_local:
        query = query.gt("timestamp", latest_local)

    # Paginate in batches (Supabase default limit is 1000)
    all_rows = []
    offset = 0
    batch_size = 1000
    while True:
        res = (
            query
            .order("timestamp", desc=False)
            .range(offset, offset + batch_size - 1)
            .execute()
        )
        batch = res.data or []
        all_rows.extend(batch)
        if len(batch) < batch_size:
            break
        offset += batch_size

    if not all_rows:
        print("✅ Local database is already up to date. Zero new rows.")
        return 0

    # Insert into local SQLite — INSERT OR IGNORE respects the unique index
    conn = sqlite3.connect(DB_PATH)
    sql = """
        INSERT OR IGNORE INTO options_chain
        (timestamp, symbol, expiry, strike, option_type,
         oi, oi_change, volume, iv, last_price, spot_price)
        VALUES
        (:timestamp, :symbol, :expiry, :strike, :option_type,
         :oi, :oi_change, :volume, :iv, :last_price, :spot_price)
    """
    with conn:
        conn.executemany(sql, all_rows)
    conn.close()

    print(f"✅ Imported {len(all_rows)} new rows into local options_flow.db")
    return len(all_rows)


def sync_signals() -> int:
    """
    Sync signals table from Supabase → local SQLite.
    Signals are permanent — syncs everything we don't have locally.
    """
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set in .env")

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    # Get latest local signal timestamp
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT MAX(fired_at) FROM signals")
    row = cur.fetchone()
    latest_local = row[0] if row and row[0] else None
    conn.close()

    print(f"🔄 Syncing signals from Supabase...")
    print(f"   Latest local signal: {latest_local or 'Empty — full sync'}")

    query = sb.table("signals").select("*")
    if latest_local:
        query = query.gt("fired_at", latest_local)

    res = query.order("fired_at", desc=False).limit(10000).execute()
    new_signals = res.data or []

    if not new_signals:
        print("✅ Signals are already up to date.")
        return 0

    conn = sqlite3.connect(DB_PATH)
    sql = """
        INSERT OR IGNORE INTO signals
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
    with conn:
        conn.executemany(sql, new_signals)
    conn.close()

    print(f"✅ Imported {len(new_signals)} new signals")
    return len(new_signals)


def sync_data():
    """Run full delta sync — options chain + signals."""
    print("═" * 50)
    print("OFA Cloud Sync — Supabase → Local SQLite")
    print("═" * 50)
    chain_count = sync_options_chain()
    sig_count = sync_signals()
    print("═" * 50)
    print(f"Done. {chain_count} chain rows + {sig_count} signals imported.")
    print("═" * 50)
    return chain_count, sig_count


if __name__ == "__main__":
    sync_data()
