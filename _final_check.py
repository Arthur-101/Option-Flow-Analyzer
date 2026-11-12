"""End-of-session truth check for 2026-11-12. Run: python _final_check.py"""

from collections import Counter

import api_service as a

sb = a.get_supabase_client()
D = "2026-11-12"


def q(table, tcol, cols="*", limit=3000):
    return (sb.table(table).select(cols)
            .gte(tcol, D + "T00:00:00+00:00").lt(tcol, D + "T23:59:59+00:00")
            .order(tcol, desc=True).limit(limit).execute().data or [])


mc = q("market_context", "timestamp", "timestamp,spot_price")
print("market_context:", len(mc))
if mc:
    print("  span:", str(mc[-1]["timestamp"])[11:19], "->", str(mc[0]["timestamp"])[11:19],
          "| null spot:", sum(1 for r in mc if not r.get("spot_price")))
    times = sorted(str(r["timestamp"])[11:16] for r in mc)
    gaps = [(times[i], times[i + 1]) for i in range(len(times) - 1)
            if int(times[i + 1][:2]) * 60 + int(times[i + 1][3:]) -
               (int(times[i][:2]) * 60 + int(times[i][3:])) > 6]
    print("  gaps >6min:", gaps)

oc = q("options_chain", "timestamp", "timestamp,spot_price")
stamps = sorted({str(r["timestamp"])[:19] for r in oc})
print("\noptions_chain rows (capped 1000):", len(oc), "| flushes:", len(stamps))
print("  first/last flush:", stamps[0][11:19] if stamps else "-", "/", stamps[-1][11:19] if stamps else "-")
print("  null spot:", sum(1 for r in oc if r.get("spot_price") in (None, 0)))

sig = q("signals", "fired_at", "fired_at,bias,signal_type")
print("\nsignals:", len(sig), "|", Counter(r.get("signal_type") for r in sig).most_common(6))
print("  latest:", str(sig[0]["fired_at"])[11:19] if sig else "-")

tr = q("trades", "entry_at", "entry_at,exit_reason,net_pnl_pct,stale_ltp,resolved_at,bias_used,option_type")
print("\ntrades:", len(tr))
print("  exits:", Counter(str(r.get("exit_reason")) for r in tr).most_common())
print("  unresolved:", sum(1 for r in tr if not r.get("resolved_at")))
print("  stale_ltp:", sum(1 for r in tr if r.get("stale_ltp")))

done = [r for r in tr if r.get("exit_reason") in ("TARGET_HIT", "STOP_HIT", "TIME_EXIT")]
w = sum(1 for r in done if float(r.get("net_pnl_pct") or 0) > 0)
if done:
    print(f"  resolved directional: {len(done)} | wins {w} = {w / len(done) * 100:.1f}%")
    print("  by bias:", Counter((r.get("bias_used"), r.get("exit_reason")) for r in done).most_common())
    print("  pnl sum: %.2f%%" % sum(float(r.get("net_pnl_pct") or 0) for r in done))
