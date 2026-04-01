# catchup.py — Import data from Railway into local options_flow.db
#
# Smart catch-up: finds the latest timestamp already in local DB
# and only fetches rows AFTER that time from Railway.
# This prevents gaps, overlaps, and interference with the detector.
#
# Usage:
#   python catchup.py                    → catches up from latest local timestamp
#   python catchup.py --date 2026-04-01  → specific date (full day)
#   python catchup.py --force            → ignore local timestamps, import all of today

import argparse
import sqlite3
import requests
import pandas as pd
from datetime import date, datetime, timezone

# ── Config ─────────────────────────────────────────────────────────────────────
RAILWAY_URL = "https://ofa-collector.up.railway.app"
LOCAL_DB    = "options_flow.db"

# ── Args ───────────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser(description="Catch up local DB from Railway")
parser.add_argument("--date",  default=str(date.today()), help="Date YYYY-MM-DD (default: today)")
parser.add_argument("--force", action="store_true", help="Import all rows regardless of local timestamps")
args = parser.parse_args()
target_date = args.date


def get_latest_local_timestamp(conn: sqlite3.Connection, date_str: str) -> str | None:
    """
    Returns the latest timestamp already in local DB for the given date.
    Used to determine where to start importing from.
    """
    result = conn.execute("""
        SELECT MAX(timestamp) as latest
        FROM options_chain
        WHERE DATE(timestamp) = ?
    """, (date_str,)).fetchone()

    latest = result[0] if result else None
    return latest


def main():
    print(f"\n{'='*55}")
    print(f"  OFA Catchup — {target_date}")
    print(f"{'='*55}")

    # 1. Check Railway is alive
    try:
        health = requests.get(f"{RAILWAY_URL}/health", timeout=10).json()
        print(f"  Railway : {health['status'].upper()} | "
              f"WS: {'✅' if health['ws_connected'] else '❌'} | "
              f"Ticks: {health['tick_count']}")
    except Exception as e:
        print(f"  ❌ Cannot reach Railway: {e}")
        return

    # 2. Find latest local timestamp for this date
    conn = sqlite3.connect(LOCAL_DB)
    conn.row_factory = sqlite3.Row

    latest_local_ts = None if args.force else get_latest_local_timestamp(conn, target_date)

    if latest_local_ts:
        print(f"  Local DB : latest row at {latest_local_ts} (UTC)")
        print(f"  Strategy : importing rows AFTER {latest_local_ts}")
    else:
        print(f"  Local DB : no rows for {target_date}")
        print(f"  Strategy : importing all rows for {target_date}")

    # 3. Fetch all rows for target date from Railway
    try:
        res = requests.get(
            f"{RAILWAY_URL}/data",
            params={"date": target_date},
            timeout=30
        )
        res.raise_for_status()
        data = res.json()
    except Exception as e:
        print(f"  ❌ Failed to fetch data: {e}")
        conn.close()
        return

    total_on_railway = data["count"]
    print(f"  Railway  : {total_on_railway} rows available for {target_date}")

    if total_on_railway == 0:
        print(f"  ⚠️  No data on Railway for {target_date} (holiday or market closed)")
        conn.close()
        return

    # 4. Filter to only rows newer than latest local timestamp
    df = pd.DataFrame(data["rows"])
    df = df.drop(columns=["id"], errors="ignore")   # drop Railway's auto-increment id

    if latest_local_ts and not args.force:
        before = len(df)
        df = df[df["timestamp"] > latest_local_ts]
        skipped = before - len(df)
        if skipped:
            print(f"  Skipped  : {skipped} rows already in local DB")

    if df.empty:
        print(f"  ✅ Local DB is already up to date for {target_date}")
        conn.close()
        return

    # 5. Insert new rows into local DB
    df.to_sql("options_chain", conn, if_exists="append", index=False)
    conn.close()

    time_range = f"{df['timestamp'].min()} → {df['timestamp'].max()}"
    print(f"  ✅ Imported : {len(df)} new rows")
    print(f"  Time range : {time_range}")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    main()