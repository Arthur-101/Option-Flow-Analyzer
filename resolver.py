# resolver.py — Live Signal Execution Resolver
# Evaluates open signals against incoming 5-minute options chain ticks in real-time.

import logging
from datetime import datetime, timezone, timedelta
from api_service import get_supabase_client

logger = logging.getLogger(__name__)

TARGET_PCT = 0.30   # +30% profit target
STOP_PCT   = -0.20  # -20% stop loss
COST_PCT   = 0.005  # 0.5% transaction cost & slippage
TIME_EXIT_HOUR_UTC = 9
TIME_EXIT_MINUTE_UTC = 50  # 15:20 IST = 09:50 UTC


def _find_matching_option(current_rows: list[dict], target_strike: float,
                          target_type: str, expiry: str | None = None) -> dict | None:
    candidates = [
        r for r in current_rows
        if abs(float(r.get("strike") or 0) - target_strike) < 0.1
        and r.get("option_type") == target_type
    ]
    if expiry and candidates:
        exp_match = [r for r in candidates if r.get("expiry") == expiry]
        if exp_match:
            return exp_match[0]
    return candidates[0] if candidates else None


def _find_atm_option(current_rows: list[dict], spot: float,
                     target_type: str, expiry: str | None = None) -> dict | None:
    type_rows = [r for r in current_rows if r.get("option_type") == target_type and r.get("strike")]
    if expiry:
        type_rows = [r for r in type_rows if r.get("expiry") == expiry] or type_rows
    if not type_rows:
        return None
    return min(type_rows, key=lambda r: abs(float(r["strike"]) - spot))


def fill_pending_entries(symbol: str, current_rows: list[dict], now_utc: str) -> None:
    if not current_rows:
        return

    client = get_supabase_client()
    if not client:
        return

    spot = next((float(r["spot_price"]) for r in current_rows if r.get("spot_price")), 22500.0)

    try:
        res = (
            client.table("signals")
            .select("*")
            .eq("symbol", symbol)
            .is_("entry_premium", "null")
            .lt("fired_at", now_utc)
            .execute()
        )
        pending = res.data or []
    except Exception as e:
        logger.warning("Failed to fetch pending entry signals: %s", e)
        return

    for sig in pending:
        sig_id = sig["id"]
        bias = (sig.get("bias") or "NEUTRAL").upper()

        if bias == "NEUTRAL":
            try:
                client.table("signals").update({
                    "entry_premium": 0.0,
                    "exit_premium": 0.0,
                    "exit_reason": "NON_DIRECTIONAL",
                    "net_pnl_pct": 0.0,
                    "resolved_at": now_utc,
                }).eq("id", sig_id).execute()
                logger.info("Signal %s: Neutral bias marked NON_DIRECTIONAL", sig_id)
            except Exception as e:
                logger.error("Failed to update neutral signal %s: %s", sig_id, e)
            continue

        sig_strike = float(sig.get("strike") or spot)
        sig_type = sig.get("option_type") or "CE"
        sig_exp = sig.get("expiry")

        if bias == "BULLISH":
            row_opt = _find_matching_option(current_rows, sig_strike, "CE", sig_exp) if sig_type == "CE" else _find_atm_option(current_rows, spot, "CE", sig_exp)
        else:
            row_opt = _find_matching_option(current_rows, sig_strike, "PE", sig_exp) if sig_type == "PE" else _find_atm_option(current_rows, spot, "PE", sig_exp)

        if not row_opt:
            continue

        entry_ltp = float(row_opt.get("last_price") or 0)
        if entry_ltp <= 0:
            continue

        try:
            client.table("signals").update({
                "entry_premium": round(entry_ltp, 2),
                "target_pct": TARGET_PCT,
                "stop_pct": STOP_PCT,
            }).eq("id", sig_id).execute()
            logger.info("🎯 Signal %s: t+1 entry_premium filled at ₹%.2f (%s %s)",
                        sig_id, entry_ltp, row_opt.get("strike"), row_opt.get("option_type"))
        except Exception as e:
            logger.error("Failed to fill entry_premium for signal %s: %s", sig_id, e)


def resolve_active_signals(symbol: str, current_rows: list[dict], now_utc: str) -> None:
    if not current_rows:
        return

    fill_pending_entries(symbol, current_rows, now_utc)

    client = get_supabase_client()
    if not client:
        return

    spot = next((float(r["spot_price"]) for r in current_rows if r.get("spot_price")), 22500.0)

    try:
        res = (
            client.table("signals")
            .select("*")
            .eq("symbol", symbol)
            .is_("resolved_at", "null")
            .not_.is_("entry_premium", "null")
            .gt("entry_premium", 0)
            .execute()
        )
        active_signals = res.data or []
    except Exception as e:
        logger.warning("Failed to fetch active signals for resolution: %s", e)
        return

    if not active_signals:
        return

    now_dt = datetime.now(timezone.utc)
    is_time_exit = (now_dt.hour > TIME_EXIT_HOUR_UTC or
                    (now_dt.hour == TIME_EXIT_HOUR_UTC and now_dt.minute >= TIME_EXIT_MINUTE_UTC))

    for sig in active_signals:
        sig_id = sig["id"]
        entry_price = float(sig["entry_premium"])
        bias = (sig.get("bias") or "BULLISH").upper()
        sig_strike = float(sig.get("strike") or spot)
        sig_type = sig.get("option_type") or "CE"
        sig_exp = sig.get("expiry")

        if bias == "BULLISH":
            row_opt = _find_matching_option(current_rows, sig_strike, "CE", sig_exp) if sig_type == "CE" else _find_atm_option(current_rows, spot, "CE", sig_exp)
        else:
            row_opt = _find_matching_option(current_rows, sig_strike, "PE", sig_exp) if sig_type == "PE" else _find_atm_option(current_rows, spot, "PE", sig_exp)

        if not row_opt:
            continue

        current_ltp = float(row_opt.get("last_price") or 0)
        if current_ltp <= 0:
            continue

        pct_change = (current_ltp - entry_price) / entry_price

        curr_mfe = float(sig.get("mfe") or 0.0) / 100.0
        curr_mae = float(sig.get("mae") or 0.0) / 100.0
        new_mfe = max(curr_mfe, pct_change)
        new_mae = min(curr_mae, pct_change)

        exit_reason = None
        exit_price = current_ltp

        target_pct = float(sig.get("target_pct") or TARGET_PCT)
        stop_pct = float(sig.get("stop_pct") or STOP_PCT)

        if pct_change <= stop_pct:
            exit_reason = "STOP_HIT"
            exit_price = current_ltp
        elif pct_change >= target_pct:
            exit_reason = "TARGET_HIT"
            exit_price = current_ltp
        elif is_time_exit:
            exit_reason = "TIME_EXIT"
            exit_price = current_ltp

        if exit_reason:
            gross_pnl = (exit_price - entry_price) / entry_price
            net_pnl = round((gross_pnl - COST_PCT) * 100, 2)
            outcome_correct = (net_pnl > 0)

            try:
                client.table("signals").update({
                    "exit_premium": round(exit_price, 2),
                    "exit_reason": exit_reason,
                    "net_pnl_pct": net_pnl,
                    "outcome_correct": outcome_correct,
                    "mfe": round(new_mfe * 100, 2),
                    "mae": round(new_mae * 100, 2),
                    "resolved_at": now_utc,
                }).eq("id", sig_id).execute()
                logger.info("🏁 Signal %s RESOLVED: %s at ₹%.2f (Entry: ₹%.2f | Net PnL: %+.2f%% | MFE: +%.1f%% | MAE: %.1f%%)",
                            sig_id, exit_reason, exit_price, entry_price, net_pnl, new_mfe * 100, new_mae * 100)
            except Exception as e:
                logger.error("Failed to resolve signal %s: %s", sig_id, e)
        else:
            try:
                client.table("signals").update({
                    "mfe": round(new_mfe * 100, 2),
                    "mae": round(new_mae * 100, 2),
                }).eq("id", sig_id).execute()
            except Exception as e:
                pass
