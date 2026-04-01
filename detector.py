# detector.py — Options Flow Anomaly Detection Engine
#
# Real-world signal logic:
#   OI_BUILDUP  : oi_change > 0 + volume confirms → new positions being built
#   OI_UNWIND   : oi_change < 0 + volume confirms → positions being closed
#   VOLUME_SPIKE: high volume but flat OI → intraday speculation / day traders
#   IV_SPIKE    : IV significantly above session average → someone paying premium
#
# Two modes (auto-selected based on days of data available):
#   BOOTSTRAP (<20 trading days): intraday percentile rank thresholds
#   FULL      (>=20 trading days): rolling 20-day average thresholds
#
# Pre-filter eliminates:
#   - First flush rows (oi_change IS NULL)
#   - Deep ITM options (>10% from spot) — likely synthetic/hedge noise
#   - Expiry within 2 days — expiry-day pinning noise
#   - Offsetting CE+PE surge on same strike — spread trade, not directional

import logging
import numpy as np
from datetime import datetime, timezone, date, timedelta
from db import (
    get_today_snapshot,
    get_intraday_oi_changes,
    get_historical_oi_changes,
    get_historical_volumes,
    count_trading_days_in_db,
    signal_already_fired_today,
    insert_signal,
)

logger = logging.getLogger(__name__)

# ── Thresholds ─────────────────────────────────────────────────────────────────

# Bootstrap mode (intraday percentile rank)
BOOTSTRAP_OI_PERCENTILE     = 90    # top 10% of today's oi_change values
BOOTSTRAP_VOLUME_PERCENTILE = 95    # top 5% of today's volume values
BOOTSTRAP_IV_PERCENTILE     = 90    # top 10% of today's IV values

# Full mode (rolling 20-day)
FULL_OI_MULTIPLIER     = 2.0   # oi_change > 2x 20-day average
FULL_VOLUME_ZSCORE     = 3.0   # volume > mean + 3σ
FULL_IV_MULTIPLIER     = 1.5   # iv > 1.5x session average

# Pre-filter
DEEP_ITM_PCT       = 0.10   # >10% away from spot = deep ITM
MIN_DTE            = 2      # skip expiries within 2 days
MIN_OI             = 1000   # skip strikes with negligible OI (noise)
MIN_VOLUME         = 500    # skip strikes with negligible volume

# Volume must be at least this fraction of OI to confirm real activity
VOLUME_OI_CONFIRM_RATIO = 0.01   # volume > 1% of OI = real flow

# Days of data needed before switching to full mode
FULL_MODE_MIN_DAYS = 20

# Signal strength scoring
BOOTSTRAP_STRENGTH_SCALE = 5.0   # max strength in bootstrap mode


# ── Main entry point ───────────────────────────────────────────────────────────

def run_detection(symbol: str) -> list[dict]:
    """
    Run full anomaly detection pipeline for a symbol.
    Called by scheduler every 5 minutes after flush_to_db().
    Returns list of signal dicts that were inserted.
    """
    today = date.today().isoformat()
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    # Decide mode
    trading_days = count_trading_days_in_db(symbol)
    mode = "FULL" if trading_days >= FULL_MODE_MIN_DAYS else "BOOTSTRAP"
    logger.info("[%s] Detection run — mode=%s trading_days_in_db=%d",
                symbol, mode, trading_days)

    # Get latest flush rows
    rows = get_today_snapshot(symbol, today)
    if not rows:
        logger.warning("[%s] No rows for today — skipping detection", symbol)
        return []

    # Get spot price from latest row (all rows in a flush share spot)
    spot = next((r["spot_price"] for r in rows if r["spot_price"]), None)
    if not spot:
        logger.warning("[%s] No spot price available — skipping detection", symbol)
        return []

    # Pre-filter rows
    filtered = _pre_filter(rows, spot)
    logger.info("[%s] %d rows after pre-filter (from %d total)",
                symbol, len(filtered), len(rows))

    if not filtered:
        return []

    # Get intraday context for bootstrap mode
    intraday_rows = get_intraday_oi_changes(symbol, today) if mode == "BOOTSTRAP" else []

    # Run detectors
    signals = []
    signals += _detect_oi_flow(filtered, symbol, spot, today, now_utc, mode, intraday_rows)
    signals += _detect_volume_spike(filtered, symbol, spot, today, now_utc, mode, intraday_rows)
    signals += _detect_iv_spike(filtered, symbol, spot, today, now_utc, intraday_rows)

    # Post-filter: eliminate CE+PE offsetting surges on same strike
    signals = _remove_offsetting_signals(signals)

    # Insert into DB
    inserted = []
    for sig in signals:
        # Dedup: don't fire same signal type on same strike twice in one day
        if not signal_already_fired_today(
            symbol, sig["strike"], sig["option_type"], sig["signal_type"], today
        ):
            insert_signal(sig)
            inserted.append(sig)
        else:
            logger.debug("Skipping duplicate signal: %s %s %.0f %s",
                         sig["signal_type"], symbol, sig["strike"], sig["option_type"])

    logger.info("[%s] %d new signals fired", symbol, len(inserted))
    return inserted


# ── Pre-filter ─────────────────────────────────────────────────────────────────

def _pre_filter(rows: list[dict], spot: float) -> list[dict]:
    """
    Remove rows that shouldn't be analysed:
    1. oi_change IS NULL (first flush of day)
    2. Deep ITM (>10% from spot)
    3. Expiry within MIN_DTE days
    4. Negligible OI or volume (noise strikes)
    """
    today = date.today()
    filtered = []

    for r in rows:
        # 1. Skip first flush
        if r["oi_change"] is None:
            continue

        # 2. Skip deep ITM
        strike = r["strike"]
        if spot and abs(strike - spot) / spot > DEEP_ITM_PCT:
            continue

        # 3. Skip near-expiry
        try:
            exp = date.fromisoformat(r["expiry"])
            if (exp - today).days <= MIN_DTE:
                continue
        except (ValueError, TypeError):
            continue

        # 4. Skip negligible OI strikes
        if (r["oi"] or 0) < MIN_OI:
            continue

        filtered.append(r)

    return filtered


# ── OI Flow Detector ───────────────────────────────────────────────────────────

def _detect_oi_flow(rows, symbol, spot, today, now_utc, mode, intraday_rows):
    """
    Detects OI_BUILDUP and OI_UNWIND signals.

    Real-world logic:
    - OI_BUILDUP: oi_change > threshold AND volume confirms real activity
      → Institutions building new directional positions
      → Bias: CE buildup = BULLISH, PE buildup = BEARISH

    - OI_UNWIND: oi_change < -threshold AND volume confirms
      → Smart money exiting — watch for reversal
      → Bias: CE unwind = BEARISH (longs exiting), PE unwind = BULLISH
    """
    signals = []

    # Compute threshold
    if mode == "BOOTSTRAP":
        # Use intraday percentile of absolute oi_change values
        all_changes = [abs(r["oi_change"]) for r in intraday_rows
                       if r["oi_change"] is not None and r["oi_change"] != 0]
        if len(all_changes) < 5:
            return []   # not enough intraday data yet
        threshold = np.percentile(all_changes, BOOTSTRAP_OI_PERCENTILE)
    else:
        threshold = None  # computed per-strike in full mode

    for r in rows:
        oi_change = r["oi_change"]
        volume = r["volume"] or 0
        oi = r["oi"] or 0

        if oi_change == 0 or oi_change is None:
            continue

        # Volume confirmation: volume must be meaningful relative to OI
        volume_confirms = volume >= max(MIN_VOLUME, oi * VOLUME_OI_CONFIRM_RATIO)

        abs_change = abs(oi_change)

        if mode == "FULL":
            hist = get_historical_oi_changes(
                symbol, r["strike"], r["option_type"], r["expiry"]
            )
            if len(hist) < 5:
                # Fall back to bootstrap for this strike
                all_changes = [abs(x["oi_change"]) for x in intraday_rows
                               if x["oi_change"] is not None]
                if len(all_changes) < 5:
                    continue
                threshold = np.percentile(all_changes, BOOTSTRAP_OI_PERCENTILE)
                mode_used = "BOOTSTRAP"
                strength = _percentile_strength(abs_change, all_changes)
            else:
                avg = np.mean(hist)
                threshold = avg * FULL_OI_MULTIPLIER
                mode_used = "FULL"
                strength = round(abs_change / avg, 2) if avg > 0 else 1.0
        else:
            mode_used = "BOOTSTRAP"
            all_changes = [abs(r2["oi_change"]) for r2 in intraday_rows
                          if r2["oi_change"] is not None]
            strength = _percentile_strength(abs_change, all_changes)

        if abs_change < threshold:
            continue

        if not volume_confirms:
            continue

        # Determine signal type and bias
        if oi_change > 0:
            signal_type = "OI_BUILDUP"
            bias = "BULLISH" if r["option_type"] == "CE" else "BEARISH"
        else:
            signal_type = "OI_UNWIND"
            # Unwind means existing position holders are exiting
            bias = "BEARISH" if r["option_type"] == "CE" else "BULLISH"

        signals.append(_build_signal(
            now_utc, symbol, r, signal_type, strength, bias, mode_used
        ))

    return signals


# ── Volume Spike Detector ──────────────────────────────────────────────────────

def _detect_volume_spike(rows, symbol, spot, today, now_utc, mode, intraday_rows):
    """
    Detects VOLUME_SPIKE: high volume with negligible OI change.

    Real-world meaning:
    - Positions opening and closing within the same candle
    - Pure intraday speculation / day traders
    - Lower conviction than OI_BUILDUP but still notable at extremes
    - Bias is NEUTRAL — no directional information
    """
    signals = []

    all_volumes = [r["volume"] for r in intraday_rows
                   if r["volume"] is not None and r["volume"] > 0]
    if len(all_volumes) < 5:
        return []

    if mode == "BOOTSTRAP":
        threshold = np.percentile(all_volumes, BOOTSTRAP_VOLUME_PERCENTILE)
    else:
        # Will compute per-strike; use intraday as fallback
        threshold = None

    for r in rows:
        volume = r["volume"] or 0
        oi_change = r["oi_change"] or 0

        if volume < MIN_VOLUME:
            continue

        # Only flag if OI change is small relative to volume
        # If oi_change is large, it's an OI_BUILDUP, not a volume spike
        if abs(oi_change) > volume * 0.3:
            continue

        if mode == "FULL":
            hist_vol = get_historical_volumes(
                symbol, r["strike"], r["option_type"], r["expiry"]
            )
            if len(hist_vol) < 5:
                vol_threshold = np.percentile(all_volumes, BOOTSTRAP_VOLUME_PERCENTILE)
                mode_used = "BOOTSTRAP"
            else:
                mean_v = np.mean(hist_vol)
                std_v = np.std(hist_vol)
                vol_threshold = mean_v + FULL_VOLUME_ZSCORE * std_v
                mode_used = "FULL"
        else:
            vol_threshold = threshold
            mode_used = "BOOTSTRAP"

        if volume < vol_threshold:
            continue

        strength = _percentile_strength(volume, all_volumes)

        signals.append(_build_signal(
            now_utc, symbol, r, "VOLUME_SPIKE", strength, "NEUTRAL", mode_used
        ))

    return signals


# ── IV Spike Detector ──────────────────────────────────────────────────────────

def _detect_iv_spike(rows, symbol, spot, today, now_utc, intraday_rows):
    """
    Detects IV_SPIKE: IV significantly above session average for nearby strikes.

    Real-world meaning:
    - Someone paying elevated premium on a specific strike
    - Often precedes big moves — market makers pricing in event risk
    - Most meaningful on ATM ± 2 strikes
    - Bias: CE IV spike = BULLISH (expecting upside), PE IV spike = BEARISH
    """
    signals = []

    # Compute session IV baseline per option_type per expiry
    iv_rows = [r for r in rows if r["iv"] is not None and r["iv"] > 0]
    if len(iv_rows) < 10:
        return []

    # Group IV by expiry + option_type for fair comparison
    from collections import defaultdict
    iv_by_group = defaultdict(list)
    for r in iv_rows:
        key = (r["expiry"], r["option_type"])
        iv_by_group[key].append(r["iv"])

    # Get intraday IV values for percentile ranking
    intra_iv = [r["iv"] for r in intraday_rows if r.get("iv") and r["iv"] > 0]

    for r in rows:
        if not r["iv"] or r["iv"] <= 0:
            continue

        key = (r["expiry"], r["option_type"])
        group_ivs = iv_by_group.get(key, [])
        if len(group_ivs) < 5:
            continue

        group_mean = np.mean(group_ivs)
        if group_mean <= 0:
            continue

        iv_ratio = r["iv"] / group_mean

        if iv_ratio < FULL_IV_MULTIPLIER:
            continue

        # Additional check: must be near ATM (within 5% of spot) for IV spikes to be meaningful
        if spot and abs(r["strike"] - spot) / spot > 0.05:
            continue

        strength = round(iv_ratio, 2)
        if intra_iv:
            strength = _percentile_strength(r["iv"], intra_iv)

        bias = "BULLISH" if r["option_type"] == "CE" else "BEARISH"

        signals.append(_build_signal(
            now_utc, symbol, r, "IV_SPIKE", strength, bias, "BOOTSTRAP"
        ))

    return signals


# ── Post-filter: remove offsetting signals ─────────────────────────────────────

def _remove_offsetting_signals(signals: list[dict]) -> list[dict]:
    """
    If both CE and PE OI_BUILDUP fire on the same strike same expiry,
    it's a spread trade (buying both sides) — not a directional signal.
    Remove both and log.
    """
    buildup_strikes = {}
    for sig in signals:
        if sig["signal_type"] == "OI_BUILDUP":
            key = (sig["strike"], sig["expiry"])
            buildup_strikes.setdefault(key, []).append(sig)

    offsetting_keys = {k for k, v in buildup_strikes.items() if len(v) == 2}

    if offsetting_keys:
        for key in offsetting_keys:
            logger.info(
                "Removing offsetting CE+PE buildup at strike=%.0f expiry=%s (spread trade)",
                key[0], key[1]
            )

    return [s for s in signals if
            not (s["signal_type"] == "OI_BUILDUP" and
                 (s["strike"], s["expiry"]) in offsetting_keys)]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _percentile_strength(value: float, population: list[float]) -> float:
    """
    Compute percentile rank of value within population,
    scaled to 1.0–5.0 for signal_strength.
    """
    if not population:
        return 1.0
    pct = float(np.mean([v <= value for v in population])) * 100
    # Map 0–100 percentile to 1.0–5.0 strength score
    strength = 1.0 + (pct / 100) * (BOOTSTRAP_STRENGTH_SCALE - 1.0)
    return round(strength, 2)


def _build_signal(fired_at, symbol, row, signal_type,
                  strength, bias, mode) -> dict:
    return {
        "fired_at":       fired_at,
        "symbol":         symbol,
        "expiry":         row["expiry"],
        "strike":         row["strike"],
        "option_type":    row["option_type"],
        "signal_type":    signal_type,
        "signal_strength": strength,
        "oi_change":      row.get("oi_change"),
        "volume":         row.get("volume"),
        "iv":             row.get("iv"),
        "spot_price":     row.get("spot_price"),
        "bias":           bias,
        "mode":           mode,
        "llm_thesis":     None,
        "llm_bias":       None,
        "llm_confidence": None,
        "news_summary_id": None,
    }