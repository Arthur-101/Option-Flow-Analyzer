# scheduler.py — APScheduler setup for main OFA project
#
# Jobs:
#   poll_job  — every 5 min 9:15–15:30 IST (Mon-Fri)
#               flush → detect → context + news → LLM thesis
#   purge_job — daily 00:05 IST

import logging
import sqlite3
import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from config import SYMBOLS, POLL_INTERVAL_MINUTES, DB_PATH

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")

_scheduler: BackgroundScheduler | None = None


def _poll_job():
    from ws_feed import flush_to_db
    from detector import run_detection
    from context import build_context
    from news_fetcher import fetch_news
    from llm_engine import generate_theses

    for sym in SYMBOLS:
        try:
            # ── Step 1: Flush WebSocket ticks → DB ────────────────────────
            rows = flush_to_db(sym)
            if not rows:
                logger.info("poll_job: no rows flushed for %s", sym)
                continue
            logger.info("poll_job: %d rows flushed for %s", len(rows), sym)

            # ── Step 2: Run anomaly detector ──────────────────────────────
            new_signals = run_detection(sym)

            if not new_signals:
                logger.info("poll_job: no new signals for %s", sym)
                continue

            logger.info("poll_job: %d signals fired for %s", len(new_signals), sym)
            for s in new_signals:
                logger.info(
                    "  → %s | %s %.0f %s | strength=%.2f | bias=%s | mode=%s",
                    s["signal_type"], sym, s["strike"], s["option_type"],
                    s["signal_strength"], s["bias"], s["mode"]
                )

            # ── Step 3: Fetch signal IDs from DB (just inserted) ──────────
            # detector.py doesn't return IDs, so we fetch the latest ones
            signals_with_ids = _fetch_latest_signals(sym, len(new_signals))

            # ── Step 4: Build market context ──────────────────────────────
            context = build_context(sym)

            # ── Step 5: Fetch relevant news ───────────────────────────────
            headlines = fetch_news(sym)
            logger.info("poll_job: %d headlines fetched", len(headlines))

            # ── Step 6: Generate LLM theses ───────────────────────────────
            n_generated = generate_theses(signals_with_ids, context, headlines)
            logger.info("poll_job: %d theses generated for %s", n_generated, sym)

        except Exception as e:
            logger.error("poll_job error for %s: %s", sym, e, exc_info=True)


def _fetch_latest_signals(symbol: str, limit: int) -> list[dict]:
    """
    Fetch the most recently inserted signal rows (with IDs) for a symbol.
    Used to pass signal IDs to the LLM engine.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT *
        FROM signals
        WHERE symbol = ?
          AND DATE(fired_at) = DATE('now')
          AND llm_thesis IS NULL
        ORDER BY id DESC
        LIMIT ?
    """, (symbol, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


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

    # Every 5 min, 9:15–15:30 IST
    _scheduler.add_job(
        _poll_job,
        trigger="cron",
        day_of_week="mon-fri",
        hour="9-15",
        minute=f"*/{POLL_INTERVAL_MINUTES}",
        id="poll_job",
        name="5-min flush + detection + LLM",
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