# api_server.py — FastAPI REST server powering the OFA React Terminal
import logging
from typing import Optional
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import api_service
from sync_supabase import sync_data

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("ofa_api")

app = FastAPI(
    title="OFA — Options Flow Analyzer API",
    description="High-performance backend for the OFA AI Thesis Terminal",
    version="3.0.0"
)

# Enable CORS for React frontend (Vite dev server on 5173, production, etc.)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/health")
def health():
    """Healthcheck endpoint."""
    return {"status": "ok", "service": "ofa-api-server", "version": "3.0.0"}

@app.get("/api/ribbon")
def get_ribbon(symbol: str = Query("NIFTY"), date: Optional[str] = Query(None)):
    """Returns top sticky ticker ribbon data (Spot, PCR, RSI, VWAP, Max Pain, Walls)."""
    try:
        return api_service.get_ribbon_data(symbol=symbol, session_date=date)
    except Exception as e:
        logger.error("Failed to fetch ribbon data: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/thesis")
def get_thesis(symbol: str = Query("NIFTY")):
    """Returns latest AI thesis verdict, conviction stars, indicator chips, and correlated news."""
    try:
        return api_service.get_latest_thesis(symbol=symbol)
    except Exception as e:
        logger.error("Failed to fetch thesis: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/signals")
def get_signals(
    symbol: str = Query("NIFTY"),
    limit: int = Query(50),
    bias: Optional[str] = Query(None),
    type: Optional[str] = Query(None)
):
    """Returns feed of detected anomaly signals with setup, strength, and AI theses."""
    try:
        return api_service.get_signals_feed(symbol=symbol, limit=limit, bias_filter=bias, type_filter=type)
    except Exception as e:
        logger.error("Failed to fetch signals: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/signals/{signal_id}")
def get_signal_detail(signal_id: int):
    """Returns comprehensive signal detail for the 440px slide-over drawer."""
    detail = api_service.get_signal_detail(signal_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Signal not found")
    return detail

@app.get("/api/chain")
def get_options_chain(symbol: str = Query("NIFTY")):
    """Returns center-anchored options chain with ATM highlight and Call/Put walls."""
    try:
        return api_service.get_options_chain_ladder(symbol=symbol)
    except Exception as e:
        logger.error("Failed to fetch options chain: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/backtest")
def get_backtest(range: int = Query(7, description="Evaluation window in days (7, 14, 30, or 0 for All)")):
    """Returns backtesting analytics, daily win rates, setup breakdown, and verified trade history."""
    try:
        return api_service.get_backtest_hub_data(range_days=range)
    except Exception as e:
        logger.error("Failed to fetch backtest data: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/charts/{chart_id}")
def get_chart(chart_id: str, symbol: str = Query("NIFTY")):
    """Returns chart datasets: c1 (price+flow), c2 (oi by strike), c3 (iv skew), etc."""
    try:
        return api_service.get_chart_data(chart_id=chart_id, symbol=symbol)
    except Exception as e:
        logger.error("Failed to fetch chart %s: %s", chart_id, e)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/sync")
def trigger_sync():
    """Triggers delta-sync from Supabase cloud into local SQLite."""
    try:
        chain_count, sig_count = sync_data()
        return {
            "status": "ok",
            "message": f"Synced {chain_count} options chain rows and {sig_count} signals from cloud.",
            "chain_rows": chain_count,
            "signals": sig_count
        }
    except Exception as e:
        logger.error("Sync failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Cloud sync failed: {e}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api_server:app", host="0.0.0.0", port=8000, reload=True)
