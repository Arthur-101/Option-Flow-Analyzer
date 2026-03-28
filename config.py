# config.py — Central configuration for Options Flow Analyzer

# ── Instruments ────────────────────────────────────────────────────────────────
SYMBOLS = ["NIFTY"]          # add "BANKNIFTY" later if needed

# ── Scheduler ─────────────────────────────────────────────────────────────────
POLL_INTERVAL_MINUTES = 5
MARKET_OPEN_TIME  = "09:15"  # IST
MARKET_CLOSE_TIME = "15:30"  # IST

# ── Database ──────────────────────────────────────────────────────────────────
DB_PATH = "options_flow.db"

# ── Retention (days) ──────────────────────────────────────────────────────────
RETENTION_OPTIONS_CHAIN_DAYS = 60
RETENTION_NEWS_RAW_DAYS      = 7
RETENTION_NEWS_SUMMARIES_DAYS = 30
# signals table: never deleted

# ── Anomaly detection thresholds ──────────────────────────────────────────────
OI_SURGE_MULTIPLIER   = 2.0   # flag if OI change > 2x rolling 20-day avg
VOLUME_SPIKE_ZSCORE   = 3.0   # flag if volume > 3 std devs above 20-day mean
ROLLING_WINDOW_DAYS   = 20    # lookback window for baseline calculations
