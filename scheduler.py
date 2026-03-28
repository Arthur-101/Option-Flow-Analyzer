# scheduler.py — APScheduler job definitions

import time
import logging
from datetime import datetime

import pytz
from apscheduler.schedulers.blocking import BlockingScheduler

from config import POLL_INTERVAL_MINUTES, MARKET_OPEN_TIME, MARKET_CLOSE_TIME, SYMBOLS
from ws_feed import flush_to_db, is_connected, tick_count
from db import purge_old_data

logger = logging.getLogger(__name__)

IST = pytz.timezone("Asia/Kolkata")


# ── Market hours guard ────────────────────────────────────────────────────────

def _is_market_open() -> bool:
    """
    Returns True only during NSE trading hours on weekdays (IST).
    Skips weekends automatically.
    """
    now = datetime.now(IST)

    # Skip Saturday (5) and Sunday (6)
    if now.weekday() >= 5:
        return False

    open_h,  open_m  = map(int, MARKET_OPEN_TIME.split(":"))
    close_h, close_m = map(int, MARKET_CLOSE_TIME.split(":"))

    market_open  = now.replace(hour=open_h,  minute=open_m,  second=0, microsecond=0)
    market_close = now.replace(hour=close_h, minute=close_m, second=0, microsecond=0)

    return market_open <= now <= market_close


# ── Poll job (runs every 5 min, guarded by market hours) ─────────────────────

def poll_job() -> None:
    """Called by APScheduler every POLL_INTERVAL_MINUTES minutes."""
    if not _is_market_open():
        logger.debug("Market closed — skipping poll")
        return

    if not is_connected():
        logger.warning("WebSocket not connected — skipping flush (ticks=%d)", tick_count())
        return

    logger.info("── Flush cycle  (ticks in store: %d) ──────────────────", tick_count())
    for symbol in SYMBOLS:
        try:
            rows = flush_to_db(symbol)
            logger.info("%s: %d rows written to DB", symbol, len(rows))
        except Exception as exc:
            logger.error("Unhandled error for %s: %s", symbol, exc, exc_info=True)


# ── Daily purge job (runs once at midnight) ───────────────────────────────────

def purge_job() -> None:
    """Delete rows older than retention window. Runs daily at 00:05 IST."""
    logger.info("Running daily retention purge …")
    try:
        purge_old_data()
    except Exception as exc:
        logger.error("Purge failed: %s", exc, exc_info=True)


# ── Scheduler factory ─────────────────────────────────────────────────────────

def build_scheduler() -> BlockingScheduler:
    """
    Create and configure the APScheduler instance.
    Returns a BlockingScheduler — call .start() on it from main.py.
    """
    scheduler = BlockingScheduler(timezone=IST)

    # Poll every N minutes
    scheduler.add_job(
        poll_job,
        trigger="interval",
        minutes=POLL_INTERVAL_MINUTES,
        id="poll_options_chain",
        name=f"Poll options chain every {POLL_INTERVAL_MINUTES} min",
        misfire_grace_time=60,   # tolerate up to 60s delay before skipping
    )

    # Daily purge at 00:05 IST
    scheduler.add_job(
        purge_job,
        trigger="cron",
        hour=0,
        minute=5,
        id="daily_purge",
        name="Daily data retention purge",
    )

    return scheduler