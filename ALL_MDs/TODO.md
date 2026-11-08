# OFA Backend — To Do

> Prioritized. Keep this list short; move finished items to [DONE.md](DONE.md).

## P0 — correctness / data integrity

- [ ] **Deploy and verify the honest backtest.** Excludes stale/exploratory trades, dedupes RULES vs LLM per signal, defaults to 30 days, removes horizon scaling, returns `sample_warning` below 30 clean trades. Code done; verify against a post-fix session.
- [ ] **Re-run `backfill_signals.py` with the ₹10 floor.** It now enforces ₹10, strict expiry, same-session ticks, and a 15-minute entry cap. Do not trust pre-fix signal-level PnL.
- [ ] **Populate outcomes in the local DB.** `outcome_correct` and `outcome_7d` are 0/1,594. Run `backfill_signals.py` or point the resolver at the local DB and verify.
- [ ] **Reconcile local vs cloud staleness.** Local DB ends 2026-10-01; Supabase is current to 2026-11-06. Decide whether local fallback should be refreshed or explicitly marked read-only historical.
- [ ] **Fix `requirements.txt`.** Missing `fastapi`, `uvicorn`, `pandas`, `streamlit`, `plotly`. A clean install cannot run the API or Streamlit app.
- [ ] **Verify `/api/signals/{id}` end-to-end.** Service function exists; frontend never calls it.

## P1 — feature completeness

- [ ] **Replace remaining mock chart data.** Backend returns `c1`–`c6`, but only `c2` is real in the UI (see frontend docs). Backend-side, confirm each chart ID returns honest, documented data.
- [ ] **News summaries.** 0 summaries in local DB. Wire `news_fetcher.py` output through to `get_ribbon_data`/thesis context.
- [ ] **Thesis coverage and conviction.** Only 89/847 signals have a thesis; 74/89 are NEUTRAL. Pause LLM trade execution until the quant baseline is clean, but keep generating theses for offline evaluation.
- [ ] **Signal-logic redesign.** Kill or redesign `IV_SPIKE` (11.4% win), add a regime filter (BEARISH 31.3% vs BULLISH 56.0%), replace always-top-10% percentile thresholds, cap signals per flush, and shorten the 5-minute entry lag.

## P2 — hardening

- [ ] **Add API tests.** No pytest suite. At minimum cover service fallbacks and route contracts.
- [ ] **Pin dependencies.** `requirements.txt` is unpinned except APScheduler; builds are not reproducible.
- [ ] **Move API base URL out of the frontend.** Currently hardcoded to `http://127.0.0.1:8000/api` (frontend change).
- [ ] **Document env keys.** Ensure `.env.example` matches every key read by `api_service.py`.

## Explicitly out of scope

- Rewriting the legacy Streamlit stack.
- Multi-symbol support beyond NIFTY until the single-symbol path is trustworthy.
