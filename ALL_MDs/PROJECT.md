# OFA Backend — Project Details

> `ofa/` is the Python engine behind the OFA terminal. It reads market data, computes analytics, exposes REST endpoints, and hosts the legacy Streamlit UI.

## Two stacks in one folder

| Stack | Entrypoint | Frontend | Status |
|---|---|---|---|
| **React terminal (current)** | `api_server.py` → `api_service.py` | `ofa_frontend/` (Vite + React 19) | Active, developed |
| **Streamlit terminal (legacy)** | `api.py`, `app.py`, `pages/` | `frontend/`, Streamlit pages | Legacy, kept for reference |

`run_app.py` (repo root) launches the current stack. `start_terminal.py` launches the legacy stack.

## Module map

| Module | Responsibility |
|---|---|
| `api_server.py` | FastAPI app, request validation, route definitions |
| `api_service.py` | Service layer: Supabase-first queries, SQLite fallback, thesis/backtest/chart shaping |
| `api.py` | Legacy FastAPI app used by the old Streamlit-era frontend |
| `app.py`, `pages/`, `ui/` | Legacy Streamlit UI |
| `db.py` | Local SQLite schema, connections, queries |
| `config.py` | Env/config (symbols, DB path, keys) |
| `detector.py` | Signal detection logic (local variant) |
| `resolver.py` | Trade outcome resolution (targets, stops, MFE/MAE) |
| `llm_engine.py` | LLM thesis generation with model fallback chain |
| `news_fetcher.py` | News headline ingestion |
| `context.py` | Market context / snapshot assembly |
| `holidays.py` | NSE holiday calendar |
| `scheduler.py` | APScheduler jobs (reset/poll/export/archive) |
| `ws_feed.py`, `angel_fetcher.py` | Angel One SmartAPI WebSocket and instrument fetch |
| `sync_supabase.py` | Local → Supabase sync |
| `catchup.py` | Import data from the Railway collector into local SQLite |
| `backfill_signals.py` | Backfill execution metrics for historical signals |

## API surface (`api_server.py`) — 9 routes

| Method | Route | Purpose |
|---|---|---|
| GET | `/api/health` | Liveness + Supabase status |
| GET | `/api/ribbon` | Spot, PCR, RSI, VIX, max pain, walls, AI stance |
| GET | `/api/thesis` | Latest LLM thesis for a symbol |
| GET | `/api/signals` | Signal feed with filters (`bias`, `type`, `ranked`, `limit`) |
| GET | `/api/signals/{id}` | Single signal detail (service implemented; frontend client unused) |
| GET | `/api/chain` | Options chain ladder for nearest active weekly expiry |
| GET | `/api/backtest` | Backtest hub data (`range_days`, `horizon`) |
| GET | `/api/charts/{chart_id}` | Chart datasets `c1`–`c6` |
| POST | `/api/sync` | Trigger a sync job |

## Data sources

1. **Supabase (primary):** `market_context`, `signals`, `news`, `trades`, `options_chain`, `daily_strike_stats`.
2. **Local SQLite (`options_flow.db`):** fallback and historical analysis. 659k chain rows, 26 sessions, 1,594 signals.
3. **`options_flow_historical_apr2026.db`:** 553k rows, April 2026 fallback dataset.

Supabase selection prefers `SUPABASE_SERVICE_ROLE_KEY`, then anon key. The service layer degrades to SQLite when Supabase is unreachable.

## Local DB state (2026-11-07)

- Sessions: 2026-03-30 → 2026-10-01 (stale vs cloud).
- Signals: 1,594; 508 have LLM theses.
- `outcome_correct` / `outcome_7d`: 0 populated.
- News summaries: 0.
- Root `options_flow.db` (scratch, 12 signals) and `ofa.db` (0 bytes) are not used by this stack.

## Backtest state

- Backtest reads the Supabase `trades` table directly.
- Excludes `SKIPPED_*` and `NON_DIRECTIONAL` from the win-rate denominator.
- Latest run: 3 evaluated trades, 0% win rate, average −0.50%.

## Environment

`ofa/.env` holds Angel One and Supabase credentials. `ofa/.env.example` documents the expected keys. `requirements.txt` is incomplete (see ISSUES.md).

## Run

```powershell
cd ofa
python -m uvicorn api_server:app --port 8000 --reload
# legacy
python -m uvicorn api:app --port 8000 --reload
python -m streamlit run app.py
```
