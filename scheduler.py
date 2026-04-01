# scheduler.py — APScheduler setup for main OFA project
#
# Jobs:
#   poll_job      — every 5 min 9:15–15:30 IST (Mon-Fri)
#                   flush WS ticks → DB, then run anomaly detector
#   purge_job     — daily 00:05 IST: delete rows older than retention window

import logging
import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from config import SYMBOLS, POLL_INTERVAL_MINUTES

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")

_scheduler: BackgroundScheduler | None = None


def _poll_job():
    from ws_feed import flush_to_db
    from detector import run_detection

    for sym in SYMBOLS:
        try:
            # Step 1: flush WebSocket ticks to DB
            rows = flush_to_db(sym)
            if rows:
                logger.info("poll_job: %d rows flushed for %s", len(rows), sym)

                # Step 2: run anomaly detector on fresh data
                signals = run_detection(sym)
                if signals:
                    logger.info("poll_job: %d signals fired for %s", len(signals), sym)
                    for s in signals:
                        logger.info(
                            "  → %s | %s %.0f %s | strength=%.2f | bias=%s | mode=%s",
                            s["signal_type"], sym, s["strike"], s["option_type"],
                            s["signal_strength"], s["bias"], s["mode"]
                        )
        except Exception as e:
            logger.error("poll_job error for %s: %s", sym, e, exc_info=True)


def _purge_job():
    from db import purge_old_data
    logger.info("purge_job fired")
    try:
        purge_old_data()
    except Exception as e:
        logger.error("purge_job error: %s", e)


def start_scheduler() -> BackgroundScheduler:
    global _scheduler

    _scheduler = BackgroundScheduler(timezone=IST)

    # Every 5 min, 9:15–15:30 IST — flush + detect
    _scheduler.add_job(
        _poll_job,
        trigger="cron",
        day_of_week="mon-fri",
        hour="9-15",
        minute=f"*/{POLL_INTERVAL_MINUTES}",
        id="poll_job",
        name="5-min flush + detection",
        misfire_grace_time=60,
    )

    # Daily purge at 00:05 IST
    _scheduler.add_job(
        _purge_job,
        trigger="cron",
        hour=0,
        minute=5,
        id="purge_job",
        name="Daily retention purge",
        misfire_grace_time=300,
    )

    _scheduler.start()
    logger.info("Scheduler started with %d jobs", len(_scheduler.get_jobs()))
    for job in _scheduler.get_jobs():
        logger.info("  → %s | next run: %s", job.name, job.next_run_time)

    return _scheduler