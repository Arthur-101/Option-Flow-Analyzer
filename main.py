# main.py — Entry point for Options Flow Analyzer

import logging
import sys

from db import init_db
from ws_feed import start_feed
from scheduler import build_scheduler
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


# ── Bootstrap ─────────────────────────────────────────────────────────────────

def main() -> None:
    logger.info("═" * 60)
    logger.info("Options Flow Analyzer — starting up")
    logger.info("═" * 60)

    # 1. Initialise database
    init_db()

    # 2. Start WebSocket feed in background (streams OI + volume + LTP live)
    logger.info("Starting Angel One WebSocket feed …")
    start_feed(SYMBOLS)

    # 3. Wait briefly for WebSocket to connect and receive first ticks
    import time
    logger.info("Waiting 15s for WebSocket to warm up …")
    time.sleep(15)

    # 4. Hand off to scheduler (blocking)
    scheduler = build_scheduler()
    logger.info(
        "Scheduler started — flushing to DB every 5 min during market hours. "
        "Press Ctrl+C to stop."
    )

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutdown requested — stopping scheduler")
        scheduler.shutdown(wait=False)
        logger.info("Options Flow Analyzer stopped cleanly.")


if __name__ == "__main__":
    main()
