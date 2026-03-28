# test_full_pipeline.py — Full end-to-end pipeline test
# Run: python test_full_pipeline.py

import sqlite3
import logging
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s")

from db import init_db
from angel_fetcher import fetch_and_store

print("="*60)
print("Full Pipeline Test — fetch → parse → SQLite")
print("="*60)

# Init DB
init_db()
print("✅ DB initialised\n")

# Fetch and store
print("Fetching NIFTY options chain …")
rows = fetch_and_store("NIFTY")
print(f"\n✅ fetch_and_store returned {len(rows)} rows")

if rows:
    # Show sample
    print("\nSample row:")
    r = rows[0]
    for k, v in r.items():
        print(f"  {k:15s}: {v}")

    # Verify in DB
    conn = sqlite3.connect("options_flow.db")
    count = conn.execute("SELECT COUNT(*) FROM options_chain").fetchone()[0]
    sample = conn.execute("""
        SELECT timestamp, symbol, expiry, strike, option_type,
               volume, last_price, spot_price
        FROM options_chain
        ORDER BY id DESC LIMIT 5
    """).fetchall()
    conn.close()

    print(f"\n✅ Rows in DB: {count}")
    print("\nLatest 5 rows from DB:")
    print(f"  {'timestamp':<22} {'sym':<8} {'expiry':<12} {'strike':>8} {'type':<4} {'vol':>8} {'ltp':>8} {'spot':>10}")
    for row in sample:
        print(f"  {str(row[0]):<22} {row[1]:<8} {row[2]:<12} {row[3]:>8.0f} {row[4]:<4} {str(row[5]):>8} {str(row[6]):>8} {str(row[7]):>10}")
else:
    print("\n❌ No rows returned — check logs above for errors")