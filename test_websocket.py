# test_websocket.py — Test Angel One WebSocket feed for 30 seconds
# Run: python test_websocket.py

import time
import logging
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s")

from ws_feed import start_feed, is_connected, tick_count
from config import SYMBOLS

print("="*60)
print("WebSocket Feed Test — running for 30 seconds")
print("="*60)

# Start feed
start_feed(SYMBOLS)

# Wait for connection + ticks
print("\nWaiting for WebSocket to connect and receive ticks …")
for i in range(30):
    time.sleep(1)
    ticks = tick_count()
    connected = is_connected()
    print(f"  [{i+1:02d}s] connected={connected}  ticks_in_store={ticks}")
    if ticks > 10:
        break

print(f"\n{'='*60}")
print(f"Final state: connected={is_connected()}  ticks={tick_count()}")

import ws_feed as _wf

if _wf._tick_store:
    print("\nSample ticks (first 5):")
    for token, tick in list(_wf._tick_store.items())[:5]:
        scrip = _wf._token_map.get(token) or _wf._token_map.get(str(token)) or {}
        print(f"  {scrip.get('symbol','?'):<30} "
              f"ltp=₹{tick.get('ltp'):<10} "
              f"oi={tick.get('oi'):<10} "
              f"vol={tick.get('volume'):<10} "
              f"iv={tick.get('iv')}")
    # Debug: show first token key types
    first_tick_token = next(iter(_wf._tick_store))
    first_map_token  = next(iter(_wf._token_map))
    print(f"\nDEBUG: tick_store key type={type(first_tick_token).__name__!r}  val={first_tick_token!r}")
    print(f"DEBUG: token_map  key type={type(first_map_token).__name__!r}  val={first_map_token!r}")
else:
    print("\n❌ No ticks received — check WebSocket connection and token list")