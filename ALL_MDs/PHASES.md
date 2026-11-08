# OFA Backend — Phases

> Status: ✅ done · 🟡 in progress · ⬜ not started

| Phase | Goal | Status | Notes |
|---|---|---|---|
| **0. Local data capture** | SQLite schema, Angel One feed, signal detection | ✅ | `db.py`, `ws_feed.py`, `detector.py`; DB holds 659k chain rows |
| **1. Analytics engine** | PCR, RSI, max pain, walls, IV skew, timeline | ✅ | Local computations in `api.py` / `api_service.py` |
| **2. LLM thesis** | News + context → thesis with model fallback | ✅ | 508 local theses; latest cloud thesis NEUTRAL, 2★, conviction 50 |
| **3. Cloud migration** | Supabase as source of truth; collector on Render | ✅ | Supabase live; collector pipeline operational |
| **4. React API layer** | `api_server.py` + `api_service.py` for the new terminal | ✅ | 8 routes; smoke-tested 2026-11-07 |
| **5. Outcome resolution** | Targets, stops, MFE/MAE, backtest stats | 🟡 | Engine exists; local outcomes unpopulated; only 3 cloud trades evaluated |
| **6. Institutional hub** | Campaign clustering, cluster win rates, calibration | 🟡 | Clustering shipped 2026-10-13; UI partially mock |
| **7. Production hardening** | Tests, pinned deps, env docs, observability | ⬜ | `requirements.txt` incomplete; no test suite |

## Phase gates

- Phase 5 is not complete until `outcome_correct` / `outcome_7d` are populated and the backtest denominator is verified on a meaningful sample (≥ 30 trades).
- Phase 6 is not complete until every chart (`c1`–`c6`) returns real data and the UI renders it without mock fallbacks.
- Phase 7 starts only after Phase 5 and 6 data correctness is settled.

## Legacy track

The Streamlit terminal (`app.py`, `pages/`, `api.py`) is frozen. No new features; fix only if it blocks the React terminal.
