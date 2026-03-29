# Option Flow Analyzer (recently started)
 *Everything written in here is how it will work in the future after it is finished*
> An AI-powered NSE options flow monitor that detects unusual activity in NIFTY index options and generates trading theses using LLMs.

**Portfolio project** demonstrating agentic AI + financial data engineering on Indian markets.

---

## What It Does

- Monitors **NIFTY index options** every 5 minutes during market hours via Angel One WebSocket
- Detects **unusual activity** — OI surges, volume spikes, IV skew anomalies
- Uses **LLMs (Gemini / DeepSeek)** to generate structured trading theses for flagged signals
- Stores everything in **SQLite** with a 60-day rolling retention window
- Exposes a **Streamlit dashboard** for live flow visualization and backtesting

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   Railway Cloud (ofa-collector)          │
│                                                          │
│  Angel One WebSocket → flush every 5min → SQLite (temp) │
│  FastAPI: GET /data?date=  ←── your local machine        │
│  3:31 PM IST: CSV export → Arthur-101/ofa-data (GitHub) │
└─────────────────────────────────────────────────────────┘
                          │
                    catchup.py
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│                  Local Machine (this repo)               │
│                                                          │
│  options_flow.db  ←── imported rows from Railway         │
│  anomaly_detector.py → signals table                     │
│  llm_engine.py → trading thesis per signal               │
│  Streamlit dashboard → visualize everything              │
└─────────────────────────────────────────────────────────┘
```

**Three GitHub repos:**
| Repo | Purpose |
|------|---------|
| [`Option-Flow-Analyzer`](https://github.com/Arthur-101/Option-Flow-Analyzer) | Main local project — detection, LLM, dashboard |
| [`ofa-collector`](https://github.com/Arthur-101/ofa-collector) | Railway cloud collector — WebSocket + FastAPI |
| [`ofa-data`](https://github.com/Arthur-101/ofa-data) | Daily CSV archive — one file per trading day |

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Data source | Angel One SmartAPI (WebSocket, SnapQuote mode) |
| Storage | SQLite (`options_flow.db`) |
| Cloud collector | Railway (free tier) + FastAPI |
| Scheduling | APScheduler |
| IV computation | Black-Scholes Newton-Raphson (local, no paid feed) |
| LLM | Gemini 2.5 Flash (free) → DeepSeek V3 (production) |
| News | NewsAPI + RSS feeds |
| Dashboard | Streamlit + TradingView Lightweight Charts |
| Alerts | Telegram Bot |

---

## Project Structure

```
Option-Flow-Analyzer/
├── main.py                  # Entry point
├── ws_feed.py               # Angel One WebSocket feed + IV computation
├── angel_fetcher.py         # Login + instrument master
├── db.py                    # SQLite schema + queries
├── scheduler.py             # APScheduler market-hours jobs
├── config.py                # Constants and thresholds
├── catchup.py               # Pull missed data from Railway API
├── fetch_instruments.py     # Manually refresh instrument master
├── test_full_pipeline.py    # Verify DB write pipeline
├── test_websocket.py        # Verify WebSocket live feed
├── z_empty_db.py            # Dev tool: wipe options_chain table
└── requirements.txt
```

---

## Database Schema

```sql
options_chain       -- 60-day retention, primary data store
  timestamp         -- UTC
  symbol            -- NIFTY
  expiry            -- YYYY-MM-DD
  strike            -- float
  option_type       -- CE / PE
  oi                -- open interest (contracts)
  oi_change         -- diff from previous snapshot
  volume            -- day total volume
  iv                -- implied volatility % (Black-Scholes)
  last_price        -- LTP in ₹
  spot_price        -- NIFTY spot in ₹

signals             -- never deleted, anomaly detection output
news_raw            -- 7-day retention
news_summaries      -- 30-day retention
```

---

## Anomaly Detection (Week 2)

| Signal | Threshold |
|--------|-----------|
| OI Surge | OI change > 2× rolling 20-day average |
| Volume Spike | Volume > 3 standard deviations above 20-day mean |
| IV Skew | Put/Call IV spread > 1.5× historical average |

Heuristic pre-filter eliminates deep ITM options, offsetting spreads, and elevated P/C ratios before sending to LLM — reducing noise by ~60%.

---

## Setup

### Prerequisites
- Python 3.11+
- Angel One demat account with API access enabled
- `.env` file with credentials

### Installation

```bash
git clone https://github.com/Arthur-101/Option-Flow-Analyzer.git
cd Option-Flow-Analyzer
pip install -r requirements.txt
```

### Environment Variables

Create a `.env` file:
```
ANGEL_API_KEY=your_api_key
ANGEL_CLIENT_ID=your_client_id
ANGEL_PASSWORD=your_password
ANGEL_TOTP_SECRET=your_totp_secret
```

### Run

```bash
# Start the main data collection pipeline
python main.py

# Pull today's data from Railway (run after waking up)
python catchup.py
```

---

## Daily Workflow

```
9:15 AM IST  →  Railway auto-collects data (no action needed)
~1:00 PM IST →  You wake up
                python catchup.py  ← imports morning data locally
                python main.py     ← continues collecting live
3:30 PM IST  →  Market closes, Railway exports CSV to ofa-data
```

---

## Roadmap

- [x] **Week 1** — Data pipeline (WebSocket feed, SQLite, IV computation)
- [x] **Week 2** — Cloud collector (Railway + FastAPI + GitHub CSV export)
- [ ] **Week 2** — Anomaly detection engine (OI surge, volume spike, IV skew)
- [ ] **Week 3** — LLM integration (Gemini → trading thesis generation)
- [ ] **Week 4** — Streamlit dashboard (live flow table, TradingView charts)
- [ ] **Week 5** — Backtesting (signal accuracy by type and confidence)
- [ ] **Week 6** — Telegram alerts + Google Drive backup
- [ ] **Week 7** — Polish, demo video, portfolio launch

---

## Cost

| Service | Cost |
|---------|------|
| Angel One SmartAPI | ₹0 |
| Railway (free tier) | ₹0 |
| Gemini 2.5 Flash | ₹0 (free tier) |
| DeepSeek V3 (Week 5+) | ~₹7/month |
| Everything else | ₹0 |
| **Total** | **~₹7/month** |

---

## Important Notes

> ⚠️ **This is a portfolio and learning project — not financial advice.**
> All signals and theses generated are for educational purposes only.
> Never commit `.env` to GitHub. Never trade real money based on this output.

---

## API Reference (ofa-collector)

Live at `https://ofa-collector.up.railway.app`

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Liveness check — WS state, tick count |
| `GET /status` | DB row count + feed state |
| `GET /data?date=YYYY-MM-DD` | All options chain rows for a date |