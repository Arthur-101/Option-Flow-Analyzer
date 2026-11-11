# OFA Backend — Issues & Solutions

> One entry per problem: symptom → cause → fix/status.

## Open

### 1. Backtest counted stale and double-counted trades (P0)
- **Symptom:** 0% win rate on the 7-day default; overall trade stats (44.5% win, +6.81% avg) still include frozen and deep-ITM quotes.
- **Cause:** `get_backtest_hub_data` excluded only `SKIPPED_*` / `NON_DIRECTIONAL`. It did not exclude `stale_ltp` or `is_exploratory`, counted a RULES and an LLM trade for the same signal as two independent observations, and defaulted to 7 days.
- **Fix (in code):** exclude stale/exploratory trades, deduplicate per `signal_id` (RULES wins), default to 30 days, return `sample_warning` below 30 clean trades, and remove the fake confidence stats.

### 2. Fake horizon scaling and local fallback (P0)
- **Symptom:** The horizon selector changed reported returns without changing any trade data; a missing Supabase table produced a plausible 54.2% win rate / 1,531 signals.
- **Cause:** `horizon_factors` multiplied returns by 0.35–1.0, and the local SQLite fallback simulated outcomes with `seed = (id * 17 + …) % 100`.
- **Fix (in code):** horizon no longer rescales returns; the fabricated fallback is replaced by an explicit `no_execution_data` response. The UI labels same-day resolution and shows the sample warning.

### 3. Headline win rate came from a different sample than the CI (P0, fixed)
- **Symptom:** The Win rate card read 23.1% while the line under it read `95% CI 46–63` — two contradictory numbers on the same card.
- **Cause:** `win_rate` was the 30-minute cluster win rate (cluster average PnL > 0), while `ci_str` was computed from deduplicated trades.
- **Fix (in code):** `win_rate` is now the deduplicated trade win rate; the cluster metric is returned separately as `cluster_win_rate`. Zero-sample defaults changed from a fabricated 50% to 0%.

### 4. `backfill_signals.py` bypassed the ₹10 minimum (P0)
- **Symptom:** 64 signals have |PnL| > 100%, entries ₹0.75–₹2.00, exits ₹123–₹186, max +16,352%. `OI_UNWIND` shows a fake 66.7% win rate.
- **Cause:** The backfill script had no premium floor, no same-day/entry-delay check, and fell back across expiries.
- **Fix (in code):** enforce ₹10 entry, strict expiry (no cross-expiry fallback), same-session ticks, and a 15-minute entry-delay cap; mark failures `SKIPPED_*` with zero PnL.

### 5. The whole clean sample comes from two sessions (P0)
- **Symptom:** A 30-day backtest reports `n=155` and 52.9%, but every clean trade is on **14–15 Oct**; the last three weeks contribute nothing. The UI therefore reads as a fresh 30-day result when it is a 2-day sample.
- **Cause:** After 15 Oct the feed froze (Render was still on the pre-fix build `9d668c3`, deployed 2026-10-13), so trade rows past that date are either `NON_DIRECTIONAL` or `stale_ltp`/`SKIPPED_*` and are excluded. Verified against Supabase: 14 Oct 75 clean / 15 Oct 80 clean / every later day 0 clean.
- **Fix:** collector guards shipped in `4d0d266` (deployed 2026-11-07) stop new occurrences. The API now returns `sample_first`, `sample_last` and `days_since_last_trade`; when the newest clean trade is older than 4 days `sample_warning` says so and the preview header carries a `Stale · 14 Oct–15 Oct` badge, so a 30-day window cannot pass for a fresh result. Historical rows still need re-resolution: re-run `backfill_signals.py`, then re-export to `ofa-data`.

### 6. `accuracy_by_setup` reported the cluster sample, not the trade sample (P0)
- **Symptom:** The collapsed preview showed `RULES 25% · n=12` while the hub showed `RULES 53% · n=154`.
- **Cause:** the field was built from `cluster_rules`/`cluster_llm` (30-minute clusters), unlike `by_setup`/`best_setup`.
- **Fix (in code):** both `accuracy_by_setup` and `sample_sizes_by_setup` now use `setup_counts`.

### 7. Local DB is stale
- **Symptom:** Local `options_flow.db` ends 2026-10-01; Supabase has 2026-11-06.
- **Cause:** Cloud collector became primary; local catch-up not run.
- **Fix:** Run `catchup.py` / `sync_supabase.py`, or treat local DB as historical-only and document it.

### 8. Outcome fields never populated
- **Symptom:** `outcome_correct` and `outcome_7d` are 0/1,594 in local DB.
- **Cause:** Resolver runs against cloud trades; local signals predate execution-field backfill.
- **Fix:** Run `backfill_signals.py`; verify resolver writes both fields.

### 9. Incomplete requirements
- **Symptom:** Fresh venv cannot run `api_server.py` or Streamlit.
- **Cause:** `requirements.txt` omitted the API runtime: `fastapi`, `uvicorn`, `pandas` (and `streamlit`/`plotly` for the old dashboard).
- **Fix (in code):** added `fastapi`, `uvicorn[standard]` and `pandas`; the API no longer imports streamlit or plotly.

### 10. Thesis is low-conviction
- **Symptom:** Latest thesis NEUTRAL, 2★, conviction 50; only 10.5% of signals have a thesis.
- **Cause:** Model cascade output and/or thin news context.
- **Fix:** Inspect `llm_engine.py` prompt and fallback chain; add news summaries (currently 0). This is P2, not the cause of the bad predictions.

### 11. Hardcoded metrics across ribbon, thesis and signal feed (P0, fixed)
- **Symptom:** Spot fell back to `22,500`; the sparkline padded to 10 identical points; pulse cards, chart series and ladder totals returned plausible literals when Supabase had no rows.
- **Cause:** Placeholder values left from the design pass, plus `or <literal>` defaults that made a missing feed look like data.
- **Fix (in code):** `get_ribbon_data`, `get_latest_thesis`, `get_signals_feed`, `get_signal_detail` and `get_chart_data` now have no literals. `market_pulse` = `pcr`, `net_oi_delta`, `rsi`, `vix`; `flow_charts` = `price_series`, `pcr_series`, `macd_series`, `vix_series`, `strikes_near_spot`, `vwap`. Missing feed columns render as `—` (nullable end-to-end). `target`/`invalidation` are real OI walls vs spot, else session high/low; `supports`/`contradicts` are measured facts; `meta_updated` is the real snapshot age.

### 12. SQLite fallbacks substituted a stale local DB for live data (P0, fixed)
- **Symptom:** Charts and the chain could return rows from `options_flow.db` (ends 2026-10-01) while the ribbon showed 2026-11-06 — two dates in one screen with no marker.
- **Cause:** `if not rows: <sqlite query>` in c1/c2/c3, the chain ladder and the signal feed.
- **Fix (in code):** all sqlite fallbacks deleted from those endpoints. Supabase or an explicit empty state only. `get_options_chain_ladder` returns `net_pcr: None` instead of a fabricated `1.0`.

### 13. Expiry selector read the wrong snapshot timestamp (P1, fixed)
- **Symptom:** The ribbon's expiry list was empty even though the chain had rows.
- **Cause:** It queried `options_chain` with `timestamp = market_context.timestamp`; the two writes differ by ~1 s.
- **Fix (in code):** the expiry list now comes from the chain's own latest snapshot. Expiries before the session date are labelled `expired` instead of a negative-DTE countdown, and `meta_updated` gains `· chain series expired`.

### 14. ΔOI compared non-adjacent snapshots (P1, fixed)
- **Symptom:** `Net ΔOI (last snapshot)` jumped by days' worth of OI.
- **Cause:** "previous snapshot" was simply the next-smaller timestamp, with no session or gap check.
- **Fix (in code):** ΔOI is computed only when the previous snapshot is the same date and ≤900 s earlier; otherwise it reports zero/empty rather than a multi-session difference.

### 15. Drawdown was a sum of percentage points (P0, fixed)
- **Symptom:** Max drawdown read `-465%` — a number that cannot exist for a real account.
- **Cause:** the equity curve adds per-trade percentages (1 unit/trade), and drawdown subtracted the peak from that sum and formatted it as a percent.
- **Fix (in code):** drawdown is now peak-to-trough of the curve in **stake units** (`-4.66 units`), and the KPI sub-label says "peak-to-trough of the cumulative curve".

### 16. Independence and regime caveats (open, from Gemini review)
Gemini's review of the measurement logic found these still-open limits. They are documented rather than hidden; none is fixed by UI wording alone.
1. **Wilson CI overstates precision.** Signals overlap and are autocorrelated, and RULES outcomes are preferred over LLM for the same signal, so effective n is nearer 10–15 than 155. `ci_str` now says `(assumes independent trades)`.
2. **Profit factor assumes equal notional.** Deep-ITM premiums dominate the percentage return; `profit_factor_sub` now says `(% per trade, equal notional)`.
3. **Two-session sample.** All clean trades are 14–15 Oct (see #5). 52.9% / +7.36% describe that sample only, not a 30-day edge.
4. **Conviction % read as a win probability** — fixed in UI: relabelled **Model score** (hero gauge, cards, drawer, table header) with a "not a probability of profit" tooltip. The formula is unchanged, so the caveat still belongs here.
5. **NEUTRAL target equalled spot**, so the ladder showed `+0.0 pts`. Fixed in UI: when target is within 0.5 pts of spot the ladder shows `—` and "no level beyond spot" instead of a 0.00% target. The backend still returns the measured level.
6. **Split-brain pipeline.** `market_context` (2026-11-06) and the chain expiries (27 Oct / 03 Nov) come from different writes. The expired label and the `chain series expired` suffix flag it; the real fix is one collector writing both.

### 17. IV spikes were labelled "Volume breakout" (P2, fixed)
- **Symptom:** Every `IV_SPIKE` signal showed `Volume breakout` in the feed, strip and drawer.
- **Cause:** the display mapping tested `"SPIKE" in st_type` before checking for `IV`, so an IV spike matched the volume branch.
- **Fix (in code):** `IV_SPIKE` → `IV spike`; `VOLUME_SPIKE` keeps `Volume breakout`. The client-side fallback in `TopSignalsStrip.tsx` got the same ordering.

### 18. Win rate had no denominator (P1, fixed)
- **Symptom:** The hub showed `52.9% · n=155` with no indication that 642 rows had been dropped, so it read as the win rate of the strategy rather than of the trades that happened to be measurable.
- **Cause:** Exclusions were lumped into one `skipped` bucket, which mixed ex-ante scope filters (exploratory, non-directional, premium floor) with ex-post execution failures (late entry, unpriceable quote). Only the former are safe to drop from the denominator.
- **Fix (in code):** `excluded_by_reason` now splits `late_entry` and `low_premium`, and the response carries an `execution_funnel`: 259 actionable → 155 filled (59.8%) · 34 missed (late entry) · 70 unpriceable (stale quote). The KPI is relabelled **Conditional win rate** with a tooltip saying it covers filled trades only, and the funnel is printed above the exclusion list. Reviewed with Gemini (Argon Medium) 2026-11-10.
- **Bounds, not an assumed spread:** the honest range comes from `execution_bounds`. A late entry is never opened, so it can be neither a win nor a loss — only the 70 unpriceable trades are censored. Counting every one as a loss gives **82/225 = 36.4%**, every one as a win gives **152/225 = 67.6%** (Manski partial-identification bounds, no fill assumption). Gemini proposed a −2% bid-ask penalty for stale trades; rejected because that number is invented and no stored field can support it (`entry_premium == exit_premium`, `net_pnl_pct` is exactly 0 on all 70).
- **Is the censoring hiding losers?** No evidence that it is. `_underlying_hit_rate()` scores trades on NIFTY spot at entry vs spot at the 15:20 IST exit, which kept printing while the option quote froze. Filled trades: 85/155 = **54.8%** against an actual option win rate of 52.9% (proxy calibrated to ~2pp). Frozen-quote trades: 42/70 = **60.0%**.
- **But that cannot narrow the bounds.** Gemini (Argon Medium) rejected reading the 5.2pp gap as "the censored trades were better", and it is right: two-proportion z = 0.72, **p = 0.47**, so the gap is sampling noise on n=70. The proxy is also path-blind (spot at 15:20 ignores a morning whipsaw that stops an option out) and moneyness-blind (deep-ITM and OTM strikes map the same spot move to different P&L). It is reported as `spot direction`, never as an implied option win rate, and the p-value is printed so a noisy gap cannot be read as a real one. The bounds stay [36.4%, 67.6%].
- **2026-11-11 regression — `SKIPPED_MONEYNESS` was in the wrong bucket (fixed).** The first live session produced 28 `SKIPPED_MONEYNESS` rows, and they fell into the catch-all `skipped` bucket, which feeds `unpriceable`. But `resolver.py` checks moneyness **before** stale/late/premium and rejects any strike more than `MAX_MONEYNESS_PCT = 0.015` (1.5%) from spot — an **ex-ante** strike filter, the same class as the premium floor. So the funnel was understating the fill rate: `199/334 = 59.6%` instead of `199/306 = 65.0%`. Now a separate `moneyness` bucket, excluded from `actionable` and from the bounds' `opened`. `censored_rows` is collected in the same loop as the counts, so `opened == filled + unpriceable` holds by construction instead of by two parallel filters that could drift.
- **The spot proxy was flaky (fixed).** A transient Supabase error on one day's `market_context` fetch was swallowed with `continue`, silently dropping those trades from the denominator: `censored_n` came back 65 in one call and 70 in another. Now each day retries once, and if it still fails the function returns `(0, 0)` so `censored_hit_pct` is `None` and the UI shows nothing — no number built on a partial sample.
- **Live numbers after the first real session (30-day window, 14 Oct → 11 Nov, 3 sessions):** win rate **53.3%**, n=199, 95% CI 46–60; funnel **306 actionable → 199 filled (65.0%) · 37 missed · 70 unpriceable**; bounds **[39.4%, 65.4%]** on 269 opened; spot direction 60.0% vs 55.3%, p=0.49; exclusions `{stale_ltp:70, exploratory:221, late_entry:37, low_premium:51, moneyness:28, non_directional:294}` = 701, and 701 + 199 filled = 900 rows, every one accounted for.

## Resolved

### `fetchSignalDetail` unused
- **Symptom:** `/api/signals/{id}` existed but the frontend never called it.
- **Fix:** wired to chart marker clicks in `ChartsDashboard.tsx`.

### Supabase anon vs service key
- **Symptom:** Inserts/queries failed or behaved inconsistently.
- **Fix:** Prefer `SUPABASE_SERVICE_ROLE_KEY` (commit `f5d021c`).

### Missing `rsi` key
- **Symptom:** Ribbon endpoint crashed on thesis access.
- **Fix:** Added `rsi` and made thesis access resilient (commit `95baccf`).

### 403-gated LLM models
- **Symptom:** Cascade stopped on unavailable models.
- **Fix:** Skip gated models and continue down the chain (commit `ebdf6f8`).

## Graph audit note

Graphify reports 343 dangling-endpoint edges and 15 collapsed edge pairs. These are AST artifacts (cross-file calls resolved to declarations), not runtime bugs. Recorded here so the warning is not mistaken for a defect.
