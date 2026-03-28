# fetch_instruments.py — Download Angel One instrument master CSV
# Angel One publishes a daily JSON with ALL correct symbol tokens
# Run: python fetch_instruments.py
#
# This replaces searchScrip for token lookup.

import re
import json
import requests
from datetime import date, timedelta

MONTH_MAP = {
    "JAN":"01","FEB":"02","MAR":"03","APR":"04","MAY":"05","JUN":"06",
    "JUL":"07","AUG":"08","SEP":"09","OCT":"10","NOV":"11","DEC":"12"
}

SYMBOL_RE = re.compile(
    r"^(?P<n>NIFTY|BANKNIFTY)"
    r"(?P<dd>\d{2})(?P<mon>[A-Z]{3})(?P<yy>\d{2})"
    r"(?P<strike>\d+)"
    r"(?P<otype>CE|PE)$"
)

INSTRUMENT_URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"

def download_instruments() -> list[dict]:
    print(f"Downloading instrument master from Angel One …")
    r = requests.get(INSTRUMENT_URL, timeout=30)
    r.raise_for_status()
    data = r.json()
    print(f"Total instruments: {len(data)}")
    return data

def filter_nifty_options(instruments: list[dict], spot: float = 22600.0) -> list[dict]:
    today   = date.today()
    min_dte = today + timedelta(days=2)
    lo, hi  = spot * 0.90, spot * 1.10

    results = []
    for item in instruments:
        # Angel One instrument master fields:
        # token, symbol, name, expiry, strike, lotsize, instrumenttype,
        # exch_seg, tick_size
        if item.get("exch_seg") != "NFO":
            continue
        if item.get("instrumenttype") not in ("OPTIDX",):
            continue

        name = item.get("name", "")
        if name not in ("NIFTY", "BANKNIFTY"):
            continue

        symbol = item.get("symbol", "")
        m = SYMBOL_RE.match(symbol)
        if not m:
            continue

        expiry_date = date(
            2000 + int(m.group("yy")),
            int(MONTH_MAP[m.group("mon")]),
            int(m.group("dd"))
        )
        if expiry_date <= min_dte:
            continue

        strike = float(item.get("strike", 0)) / 100  # Angel One stores strike * 100
        if not (lo <= strike <= hi):
            continue

        results.append({
            "token":       item["token"],
            "symbol":      symbol,
            "name":        name,
            "expiry":      expiry_date.isoformat(),
            "strike":      strike,
            "option_type": m.group("otype"),
            "lotsize":     item.get("lotsize"),
        })

    return results

if __name__ == "__main__":
    instruments = download_instruments()

    # Show sample raw instrument to understand field names
    nfo_sample = [i for i in instruments if i.get("exch_seg") == "NFO"][:3]
    print(f"\nSample NFO instrument fields:")
    for s in nfo_sample:
        print(f"  {s}")

    # Filter
    nifty = filter_nifty_options(instruments, spot=22600.0)
    expiries = sorted(set(n["expiry"] for n in nifty))
    print(f"\nNIFTY options found: {len(nifty)}")
    print(f"Active expiries: {expiries[:6]}")

    if nifty:
        print(f"\nSample tokens:")
        for n in nifty[:5]:
            print(f"  {n['symbol']:<30}  token={n['token']:<8}  strike={n['strike']:.0f}  expiry={n['expiry']}")

        # Save to file for use by angel_fetcher
        with open("nifty_instruments.json", "w") as f:
            json.dump(nifty, f, indent=2)
        print(f"\n✅ Saved {len(nifty)} instruments to nifty_instruments.json")