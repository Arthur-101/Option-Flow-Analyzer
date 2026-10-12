# backfill_signals.py — Backfill option execution metrics for historical signals
import logging
from datetime import datetime, timezone, timedelta
from api_service import get_supabase_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("backfill")

TARGET_PCT = 0.30   # +30% profit target
STOP_PCT   = -0.20  # -20% stop loss
COST_PCT   = 0.005  # 0.5% estimated slippage and transaction costs

def run_backfill():
    sb = get_supabase_client()
    if not sb:
        logger.error("Supabase client unavailable")
        return

    # Fetch all signals
    signals_res = sb.table("signals").select("*").order("fired_at", desc=False).execute()
    signals = signals_res.data or []
    logger.info("Found %d signals to evaluate and backfill", len(signals))

    updated_count = 0

    for sig in signals:
        sig_id = sig["id"]
        strike = sig.get("strike")
        opt_type = sig.get("option_type")
        fired_at_str = sig.get("fired_at")
        expiry_str = sig.get("expiry")

        if not strike or not opt_type or not fired_at_str:
            logger.warning("Skipping signal %s due to missing strike/type/fired_at", sig_id)
            continue

        fired_dt = datetime.fromisoformat(fired_at_str.replace("Z", "+00:00"))
        
        # Calculate DTE
        dte = 0
        if expiry_str:
            try:
                exp_date = datetime.strptime(expiry_str[:10], "%Y-%m-%d").date()
                dte = max(0, (exp_date - fired_dt.date()).days)
            except Exception:
                dte = 0
        is_expiry_day = (dte == 0)

        # Query options_chain ticks for this strike, option_type, expiry from fired_at onwards
        q = (
            sb.table("options_chain")
            .select("timestamp,last_price")
            .eq("symbol", "NIFTY")
            .eq("strike", strike)
            .eq("option_type", opt_type)
            .gte("timestamp", fired_at_str)
            .order("timestamp", desc=False)
        )
        if expiry_str:
            q = q.eq("expiry", expiry_str[:10])

        ticks_res = q.limit(100).execute()
        ticks = ticks_res.data or []

        if not ticks and expiry_str:
            fallback_q = (
                sb.table("options_chain")
                .select("timestamp,last_price")
                .eq("symbol", "NIFTY")
                .eq("strike", strike)
                .eq("option_type", opt_type)
                .gte("timestamp", fired_at_str)
                .order("timestamp", desc=False)
                .limit(100)
            )
            ticks = fallback_q.execute().data or []

        if not ticks:
            logger.info("Signal %s (%s %s %s): No chain ticks found in window", sig_id, strike, opt_type, fired_at_str)
            # Still tag as exploratory
            try:
                sb.table("signals").update({
                    "dte": dte,
                    "is_expiry_day": is_expiry_day,
                    "is_exploratory": True,
                    "target_pct": TARGET_PCT,
                    "stop_pct": STOP_PCT,
                }).eq("id", sig_id).execute()
            except Exception as e:
                logger.error("Update failed for signal %s: %s", sig_id, e)
            continue

        # 1. Entry price = LTP at the next available snapshot
        entry_price = float(ticks[0]["last_price"] or 0)
        if entry_price <= 0 and len(ticks) > 1:
            entry_price = float(ticks[1]["last_price"] or 0)

        if entry_price <= 0:
            logger.warning("Signal %s: invalid entry price <= 0", sig_id)
            continue

        # 2. Simulate fixed-rule execution across subsequent ticks
        mfe = 0.0
        mae = 0.0
        exit_price = entry_price
        exit_reason = "TIME_EXIT"
        resolved_at = ticks[-1]["timestamp"]

        subsequent_ticks = ticks[1:] if len(ticks) > 1 else ticks

        for t in subsequent_ticks:
            p = float(t.get("last_price") or 0)
            if p <= 0:
                continue

            pct_change = (p - entry_price) / entry_price
            if pct_change > mfe:
                mfe = pct_change
            if pct_change < mae:
                mae = pct_change

            # Check target hit
            if pct_change >= TARGET_PCT:
                exit_price = p
                exit_reason = "TARGET_HIT"
                resolved_at = t["timestamp"]
                break

            # Check stop hit
            if pct_change <= STOP_PCT:
                exit_price = p
                exit_reason = "STOP_HIT"
                resolved_at = t["timestamp"]
                break

            exit_price = p
            resolved_at = t["timestamp"]

        # 3. Calculate realized net PnL (after costs)
        gross_pnl_pct = (exit_price - entry_price) / entry_price
        net_pnl_pct = round((gross_pnl_pct - COST_PCT) * 100, 2)

        update_payload = {
            "entry_premium": round(entry_price, 2),
            "exit_premium": round(exit_price, 2),
            "exit_reason": exit_reason,
            "net_pnl_pct": net_pnl_pct,
            "mfe": round(mfe * 100, 2),
            "mae": round(mae * 100, 2),
            "resolved_at": resolved_at,
            "dte": dte,
            "is_expiry_day": is_expiry_day,
            "target_pct": TARGET_PCT,
            "stop_pct": STOP_PCT,
            "is_exploratory": True,
        }

        try:
            sb.table("signals").update(update_payload).eq("id", sig_id).execute()
            updated_count += 1
            logger.info("Signal %s backfilled: entry=%.2f exit=%.2f reason=%s PnL=%.2f%% MFE=%.2f%% MAE=%.2f%%",
                        sig_id, entry_price, exit_price, exit_reason, net_pnl_pct, mfe * 100, mae * 100)
        except Exception as e:
            logger.error("Failed to update signal %s in Supabase: %s", sig_id, e)

    logger.info("Backfill complete! Updated %d of %d signals.", updated_count, len(signals))

if __name__ == "__main__":
    run_backfill()
