# main.py — Entry point for Options Flow Analyzer

import logging
import sys
import time
import threading

from db import init_db
from ws_feed import start_feed
from scheduler import start_scheduler
from config import SYMBOLS


# ── Logging setup ─────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("options_flow.log", encoding="utf-8"),
    ],
)

logger = logging.getLogger(__name__)


# ── Bootstrap ──────────────────────────────────────────────────────────────────

def main() -> None:
    logger.info("═" * 60)
    logger.info("Options Flow Analyzer — starting up")
    logger.info("═" * 60)

    # 1. Initialise database
    init_db()

    # 2. Start WebSocket feed in background thread
    logger.info("Starting Angel One WebSocket feed …")
    start_feed(SYMBOLS)

    # 3. Wait for WebSocket to connect and receive first ticks
    logger.info("Waiting 15s for WebSocket to warm up …")
    time.sleep(15)

    # 4. Start scheduler in background (already calls scheduler.start() internally)
    start_scheduler()
    logger.info(
        "Scheduler started — flushing + detecting every 5 min during market hours. "
        "Press Ctrl+C to stop."
    )

    # 5. Keep main thread alive — scheduler + WebSocket run in background threads
    stop_event = threading.Event()
    try:
        stop_event.wait()   # blocks until KeyboardInterrupt
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutdown requested — stopping.")
        logger.info("Options Flow Analyzer stopped cleanly.")


if __name__ == "__main__":
    main()