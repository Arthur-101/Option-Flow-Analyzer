# OFA Backend — Completed Work

> Newest first. Dates from git history where available; verification notes from 2026-11-07.

## 2026-11-07

- **Honest backtest (P0)** — `get_backtest_hub_data` excludes `stale_ltp` and `is_exploratory` trades, deduplicates one observation per `signal_id` (RULES wins), defaults to 30 days, and returns `sample_warning` / `data_status` / `excluded_trades` below 30 clean trades.
- **Real KPIs** — expectancy, profit factor, avg win/loss, max drawdown, equity curve, and a Wilson 95% CI computed from the deduplicated sample. Hardcoded `accuracy_by_confidence` / `sample_sizes_by_confidence` removed.
- **Fake horizon scaling removed** — `horizon_factors` deleted; `horizon` is accepted for API compatibility but never rescales returns.
- **Fabricated local fallback removed** — a missing Supabase table now returns an explicit `no_execution_data` payload instead of a simulated 54.2% win rate.
- **`backfill_signals.py` sanity guards** — ₹10 entry floor, strict expiry (no cross-expiry fallback), same-session ticks, 15-minute entry cap, 10x return guard; failures are written as `SKIPPED_*` with zero PnL.
- **Headline win rate fixed** — the KPI card showed the 30-minute *cluster* win rate (23.1%) next to a trade-level confidence interval (46–63%). `win_rate` is now the deduplicated trade win rate; the cluster number moved to `cluster_win_rate`.
- **Equity curve is a fixed-size sum** — one unit per trade, labeled in the UI, so drawdown reads in the same units as the per-trade returns.
- **Trade page cap raised** to 1,000 with a `shortcut:` note (was 500, which silently truncated a 30-day window of ~900 trades).
- **Trade history is measured-only** — `get_backtest_hub_data` now returns only the deduplicated, resolved trades (155 rows instead of 802). Stale/exploratory/skipped rows no longer appear as −0.50% "Missed" trades. Per-row stars, confidence and `signal_strength` were removed (they were literals 3/4, ★★★☆☆, 3.5); `expiry_label` and `entry_time_ist` are derived from the trade.
- **Best setup uses the trade sample** — the card previously used the 30-minute cluster win rate (`25%`) while `by_setup` showed `53%`. `best_setup_name` / `best_setup_sub` now come from the deduplicated trade counts.
- **Verified live (2026-11-07, 30-day window, 1,000-row trade page):** `win_rate` 52.9% · n=155 clean deduplicated trades · expectancy +7.36%/trade · profit factor 1.70 · max drawdown −465.5% (sum of 1-unit trades, not compounded) · 802 raw trades, 647 excluded as stale/exploratory.

## 2026-10-13

- **Supabase key precedence** — `api_service` checks `SUPABASE_SERVICE_ROLE_KEY` before the anon key. Commit `f5d021c`.
- **Institutional campaign clustering** — 30-minute clustering plus cluster win-rate engine for the backtest hub. Commit `d4175f6`.
- **Weekly expiry filtering** — options chain queries restricted to the nearest active weekly expiry. Commit `8d934fe`.
- **Backtest source of truth** — queries the `trades` table directly. Commit `b230c8a`.
- **Win-rate denominator** — excludes `SKIPPED_*` and `NON_DIRECTIONAL` trades. Commit `2d6a636`.
- **Real-time signal resolution engine** — targets, stops, MFE/MAE. Commit `d4fb4c7`.

## 2026-10-12

- **Backfill script** for historical signal execution metrics (`backfill_signals.py`). Commit `d07c0e1`.
- **Execution fields** added to signal detection plus backfill. Commit `a1f5fd2`.
- **Dynamic expiries** and wall filtering to nearest active weekly expiry. Commit `8739c9a`.

## 2026-10-11

- **Supabase wiring** for options ladder, charts, and slide-over drawer. Commit `e820cfc`.

## 2026-10-01

- **Holiday awareness** in the React backend service layer. Commit `eb35cfb`.
- **Cloud reads** — market context, signals, and news read directly from Supabase. Commit `b9117fd`.

## 2026-09-29

- **Ribbon enrichment** — India VIX, sparkline, expiry DTE, AI stance. Commit `f63ce16`.
- **FastAPI server + service layer** for the React terminal. Commit `61e9884`.
- **Ribbon resilience** — missing `rsi` key fixed; thesis access made resilient. Commit `95baccf`.

## Earlier

- Model cascade hardened against 403-gated models. Commit `ebdf6f8`.
- Local collector/analyzer modules (`detector.py`, `resolver.py`, `llm_engine.py`, `scheduler.py`, `ws_feed.py`).
- Streamlit terminal (`app.py`, `pages/`, `ui/`) — legacy but functional.

## Verified on 2026-11-07

- API smoke test passed: `get_ribbon_data`, `get_latest_thesis`, `get_signals_feed`, `get_options_chain_ladder`, `get_backtest_hub_data`, `get_chart_data('c1')`.
- Supabase serving live data; latest session 2026-11-06.
- `ofa_frontend` production build passes (6.5s).
