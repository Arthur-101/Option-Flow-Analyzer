# news_fetcher.py — RSS news fetcher for OFA
#
# Triggered when a signal fires, not on a schedule.
# Fetches recent NIFTY-relevant headlines from ET Markets and Moneycontrol.
# Stores raw headlines in news_raw table.
# Returns list of headline strings for LLM context.

import logging
import sqlite3
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from config import DB_PATH

logger = logging.getLogger(__name__)

# ── RSS feed sources ───────────────────────────────────────────────────────────

RSS_FEEDS = [
    {
        "name": "ET Markets",
        "url": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    },
    {
        "name": "Moneycontrol",
        "url": "https://www.moneycontrol.com/rss/marketoutlook.xml",
    },
]

# Keywords to filter relevant headlines (case-insensitive)
RELEVANT_KEYWORDS = [
    "nifty", "sensex", "market", "index", "option", "derivative",
    "fii", "dii", "institutional", "expiry", "volatility", "iv",
    "bull", "bear", "rally", "fall", "crash", "breakout",
    "rbi", "fed", "rate", "inflation", "gdp", "earnings",
]

# Only fetch headlines published within this many hours
MAX_AGE_HOURS = 6

# Max headlines to return to LLM (keep token count low)
MAX_HEADLINES = 8


# ── Fetch and parse RSS ────────────────────────────────────────────────────────

def _parse_rss(feed_url: str, feed_name: str) -> list[dict]:
    """Parse RSS feed and return list of article dicts."""
    try:
        resp = requests.get(feed_url, timeout=10, headers={
            "User-Agent": "Mozilla/5.0 (compatible; OFA/1.0)"
        })
        resp.raise_for_status()
    except Exception as e:
        logger.warning("RSS fetch failed for %s: %s", feed_name, e)
        return []

    articles = []
    try:
        root = ET.fromstring(resp.content)
        items = root.findall(".//item")

        for item in items:
            title = item.findtext("title", "").strip()
            pub_date_str = item.findtext("pubDate", "").strip()
            link = item.findtext("link", "").strip()

            if not title:
                continue

            # Parse publication date
            pub_dt = None
            for fmt in [
                "%a, %d %b %Y %H:%M:%S %z",
                "%a, %d %b %Y %H:%M:%S GMT",
            ]:
                try:
                    pub_dt = datetime.strptime(pub_date_str, fmt)
                    if pub_dt.tzinfo is None:
                        pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                    break
                except ValueError:
                    continue

            articles.append({
                "headline": title,
                "source": feed_name,
                "url": link,
                "published_at": pub_dt,
            })

    except ET.ParseError as e:
        logger.warning("RSS parse error for %s: %s", feed_name, e)

    return articles


def _is_relevant(headline: str) -> bool:
    """Check if headline contains any relevant keyword."""
    hl_lower = headline.lower()
    return any(kw in hl_lower for kw in RELEVANT_KEYWORDS)


def _is_recent(pub_dt: datetime | None) -> bool:
    """Check if article was published within MAX_AGE_HOURS."""
    if pub_dt is None:
        return True  # include if no date available
    cutoff = datetime.now(timezone.utc) - timedelta(hours=MAX_AGE_HOURS)
    return pub_dt >= cutoff


# ── Store to DB ────────────────────────────────────────────────────────────────

def _store_headlines(articles: list[dict], symbol: str) -> None:
    """Store fetched headlines in news_raw table."""
    if not articles:
        return

    conn = sqlite3.connect(DB_PATH)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    conn.executemany("""
        INSERT INTO news_raw (fetched_at, symbol, headline, source, url, published_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, [
        (
            now,
            symbol,
            a["headline"],
            a["source"],
            a["url"],
            a["published_at"].strftime("%Y-%m-%d %H:%M:%S") if a["published_at"] else None,
        )
        for a in articles
    ])
    conn.commit()
    conn.close()
    logger.info("Stored %d headlines in news_raw", len(articles))


# ── Main entry point ───────────────────────────────────────────────────────────

def fetch_news(symbol: str) -> list[str]:
    """
    Fetch and filter recent relevant news headlines.
    Returns list of headline strings for LLM context (max MAX_HEADLINES).
    Also stores all fetched headlines in news_raw table.

    Called once per signal fire, not on a schedule.
    """
    all_articles = []

    for feed in RSS_FEEDS:
        articles = _parse_rss(feed["url"], feed["name"])
        all_articles.extend(articles)

    # Filter: relevant keywords + recent enough
    filtered = [
        a for a in all_articles
        if _is_relevant(a["headline"]) and _is_recent(a["published_at"])
    ]

    # Deduplicate by headline text
    seen = set()
    deduped = []
    for a in filtered:
        if a["headline"] not in seen:
            seen.add(a["headline"])
            deduped.append(a)

    # Sort by recency
    deduped.sort(
        key=lambda x: x["published_at"] or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True
    )

    # Store in DB
    _store_headlines(deduped, symbol)

    # Return just headline strings for LLM
    headlines = [a["headline"] for a in deduped[:MAX_HEADLINES]]

    logger.info(
        "[%s] News fetched: %d total → %d relevant → %d returned to LLM",
        symbol, len(all_articles), len(deduped), len(headlines)
    )

    return headlines