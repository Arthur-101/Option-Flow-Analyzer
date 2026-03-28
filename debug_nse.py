# debug_nse.py — Run this standalone to diagnose NSE fetch issues
# Usage: python debug_nse.py

import json
import sys

def test_nsepython():
    print("=" * 60)
    print("TEST 1: nsepython")
    print("=" * 60)
    try:
        from nsepython import nse_optionchain_scrapper
        data = nse_optionchain_scrapper("NIFTY")
        print(f"Type returned: {type(data)}")

        if data is None:
            print("❌ Got None — nsepython returned nothing")
            return None

        if isinstance(data, dict):
            print(f"Top-level keys: {list(data.keys())}")

            # Check the path our parser uses
            records = data.get("records", {})
            print(f"  records keys: {list(records.keys()) if isinstance(records, dict) else type(records)}")

            chain_data = records.get("data", []) if isinstance(records, dict) else []
            print(f"  records.data length: {len(chain_data)}")

            spot = records.get("underlyingValue") if isinstance(records, dict) else None
            print(f"  spot price: {spot}")

            if chain_data:
                print("\n  First record sample:")
                print(json.dumps(chain_data[0], indent=4, default=str))
                print("\n✅ nsepython working — data looks good")
            else:
                print("\n❌ records.data is empty — structure may have changed")
                print("Full response (first 2000 chars):")
                print(json.dumps(data, default=str)[:2000])

        else:
            print(f"❌ Unexpected type: {type(data)}")
            print(str(data)[:1000])

        return data

    except ImportError:
        print("❌ nsepython not installed — run: pip install nsepython")
        return None
    except Exception as e:
        print(f"❌ Exception: {type(e).__name__}: {e}")
        return None


def test_direct_nse_api():
    """Fallback: hit NSE directly with proper headers (bypasses nsepython)."""
    print("\n" + "=" * 60)
    print("TEST 2: Direct NSE API call (fallback)")
    print("=" * 60)
    import urllib.request

    # NSE requires these headers or it returns 401/403
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/option-chain",
    }

    # Step 1: Get cookies by hitting the main page first
    print("Step 1: Fetching NSE homepage to get session cookies...")
    try:
        req = urllib.request.Request("https://www.nseindia.com", headers=headers)
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
        resp = opener.open(req, timeout=10)
        print(f"  Homepage status: {resp.status}")
    except Exception as e:
        print(f"  ❌ Homepage fetch failed: {e}")
        opener = urllib.request.build_opener()

    # Step 2: Fetch option chain
    print("Step 2: Fetching option chain...")
    url = "https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY"
    try:
        req = urllib.request.Request(url, headers=headers)
        resp = opener.open(req, timeout=10)
        raw = resp.read().decode("utf-8")
        data = json.loads(raw)

        records = data.get("records", {})
        chain = records.get("data", [])
        spot  = records.get("underlyingValue")

        print(f"  ✅ Direct API works!")
        print(f"  Spot price: {spot}")
        print(f"  Chain rows: {len(chain)}")
        if chain:
            print(f"  First strike: {chain[0].get('strikePrice')}")

        return data

    except Exception as e:
        print(f"  ❌ Direct API failed: {type(e).__name__}: {e}")
        return None


if __name__ == "__main__":
    result1 = test_nsepython()
    result2 = test_direct_nse_api()

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    if result1 and result1.get("records", {}).get("data"):
        print("✅ nsepython works  → no change needed")
    elif result2 and result2.get("records", {}).get("data"):
        print("⚠️  nsepython broken, direct API works → we'll replace the fetcher")
    else:
        print("❌ Both methods failed → likely a network/IP block issue")
        print("   Try running during market hours (9:15–15:30 IST weekdays)")
        print("   NSE sometimes blocks non-Indian IPs or rate-limits scrapers")
