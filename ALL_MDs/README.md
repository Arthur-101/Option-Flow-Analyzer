# OFA Backend — Documentation Index

> Scope: `ofa/` — the analysis engine, FastAPI service layer, local DB access, legacy Streamlit app.
> Last verified: 2026-11-07.

## Files

| File | What it tracks |
|---|---|
| [PROJECT.md](PROJECT.md) | Architecture, modules, API endpoints, data sources, run commands |
| [DONE.md](DONE.md) | Completed work, newest first |
| [TODO.md](TODO.md) | Open work, prioritized |
| [PHASES.md](PHASES.md) | Roadmap phases and their status |
| [ISSUES.md](ISSUES.md) | Known issues, root causes, fixes |

Related docs:
- Collector: [../../ofa_collector/ALL_MDs/README.md](../../ofa_collector/ALL_MDs/README.md)
- Frontend: [../../ofa_frontend/ALL_MDs/README.md](../../ofa_frontend/ALL_MDs/README.md)

## Current status

- **Active stack:** `api_server.py` (FastAPI) + `api_service.py`, consumed by `ofa_frontend`; launched from repo root by `run_app.py`.
- **Legacy stack:** `api.py` + `frontend/` + Streamlit (`app.py`, `pages/`); launched by `start_terminal.py`.
- **Primary data source:** Supabase (cloud), with local SQLite fallback (`options_flow.db`).
- **API:** 9 routes under `/api` (8 data routes + `/api/health`). Smoke-tested 2026-11-07.
- **Build state:** backend imports and serves; frontend `npm run build` passes.

## Run

```powershell
# from repo root — starts backend :8000 and frontend :5173
python run_app.py

# backend only
cd ofa
python -m uvicorn api_server:app --port 8000 --reload
```

## Quick facts

- `ofa/options_flow.db`: 659,138 chain rows, 26 sessions (2026-03-30 → 2026-10-01), 1,594 signals.
- Supabase is live; latest session seen 2026-11-06 (spot 25,030.35, PCR 0.64, RSI 85.73).
- Local DB is **stale** relative to Supabase and is only a fallback path.
