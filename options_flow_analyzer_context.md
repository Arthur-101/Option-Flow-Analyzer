# Options Flow Analyzer — Full Project Context

> Paste this file at the start of any new Claude chat to restore full context.
> Last updated: March 2026 (v2 — LLM model + alerts decisions added)

---

## What this project is

An AI-powered options flow analyzer for Indian markets (NSE). It monitors NIFTY index options every 5 minutes, detects unusual activity (OI surges, volume spikes, IV anomalies), fetches related news, and uses an LLM to generate a human-readable thesis explaining what smart money might be positioning for. Delivers daily alerts via Telegram and a Streamlit dashboard.

**This is a portfolio project** — not a commercial trading system. The goal is to demonstrate agentic AI + financial data engineering skills to hiring managers.

---

## Scope: Tier 1 only (decided)

We are only building Tier 1 for now:

- **Instruments:** NIFTY 50 index options + optionally BANKNIFTY
- **Polling interval:** Every 5 minutes, 9:15am–3:30pm IST, weekdays only
- **Data per cycle:** ~300–500 KB (trivially small)
- **Cycles per day:** ~75
- **Daily storage:** ~8–12 MB

Tier 2 (mid-cap stocks on trigger) and Tier 3 (on-demand) are deferred to later.

---

## Key decisions already made

| Decision | Choice | Reason |
|---|---|---|
| Data source | `nsepython` (start) → Angel One SmartAPI (upgrade) | nsepython works today, no auth. Angel One is free official API |
| Storage | SQLite (.db file) | Zero setup, full SQL, handles millions of rows easily |
| Cloud backup | Google Drive (daily .db file copy via pydrive2) | Free 15GB tier, version history |
| LLM (dev/testing) | Gemini 2.5 Flash free tier | 1,000 req/day free — zero cost while building |
| LLM (production) | DeepSeek V3.2 | Best reasoning per rupee, ~₹6–7/month at our volume |
| Dashboard | Streamlit | Free deploy on streamlit.io |
| Alerts | Telegram Bot API | Free, no approval needed, 10-min setup. WhatsApp rejected — requires Meta business approval + per-message cost, overkill for a dev tool |
| Scheduler | APScheduler | Runs inside Python script |
| News source | RSS feeds (primary) + NewsAPI (fallback) | RSS is free/unlimited, covers ET/Moneycontrol/NSE |

---

## Database schema — 4 tables

### Table 1: `options_chain`
Stores raw options data from every pull.

```sql
CREATE TABLE options_chain (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME NOT NULL,
    symbol TEXT NOT NULL,          -- e.g. 'NIFTY'
    expiry DATE NOT NULL,          -- e.g. '2025-04-25'
    strike REAL NOT NULL,          -- e.g. 19500.0
    option_type TEXT NOT NULL,     -- 'CE' or 'PE'
    oi INTEGER,                    -- open interest
    oi_change INTEGER,             -- change from previous pull
    volume INTEGER,
    iv REAL,                       -- implied volatility %
    last_price REAL,
    spot_price REAL                -- NIFTY spot at time of pull
);

CREATE INDEX idx_oc_timestamp ON options_chain(timestamp);
CREATE INDEX idx_oc_symbol_strike ON options_chain(symbol, strike, option_type, expiry);
```

**Retention:** 60 days. Delete daily with:
```sql
DELETE FROM options_chain WHERE timestamp < datetime('now', '-60 days');
```

**Row format:** Long format — one row per strike per pull (NOT columns per timestamp).
Each pull adds ~400–800 rows. At steady state: ~3.6M rows, ~500–700 MB.

---

### Table 2: `news_raw`
Raw headlines fetched when a signal fires.

```sql
CREATE TABLE news_raw (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fetched_at DATETIME NOT NULL,
    symbol TEXT NOT NULL,
    headline TEXT NOT NULL,
    source TEXT,
    url TEXT,
    published_at DATETIME
);
```

**Retention:** 7 days. Once summarized, raw headlines are disposable.

---

### Table 3: `news_summaries`
LLM-generated 2-sentence summaries attached to each signal.

```sql
CREATE TABLE news_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at DATETIME NOT NULL,
    signal_id INTEGER,             -- FK to signals table
    symbol TEXT NOT NULL,
    summary TEXT NOT NULL,         -- 2-sentence LLM output
    news_window_hours INTEGER      -- how many hours of news this covers
);
```

**Retention:** 30 days. Used by backtester to explain past signals.

---

### Table 4: `signals`
Every anomaly flagged + LLM thesis + outcome. **Never delete this table.**

```sql
CREATE TABLE signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fired_at DATETIME NOT NULL,
    symbol TEXT NOT NULL,
    expiry DATE,
    strike REAL,
    option_type TEXT,              -- 'CE', 'PE', or 'INDEX'
    signal_type TEXT NOT NULL,     -- 'OI_SURGE', 'VOLUME_SPIKE', 'IV_SPIKE', 'BLOCK_TRADE'
    signal_strength REAL,          -- z-score or multiplier vs average
    llm_thesis TEXT,               -- full LLM reasoning output
    llm_bias TEXT,                 -- 'BULLISH', 'BEARISH', 'NEUTRAL'
    llm_confidence INTEGER,        -- 1-5
    news_summary_id INTEGER,       -- FK to news_summaries
    outcome_7d REAL,               -- % price change 7 days later (filled by backtester)
    outcome_correct BOOLEAN,       -- did price move in thesis direction?
    outcome_filled_at DATETIME     -- when backtester filled the outcome
);
```

**Retention:** Forever. This is the project's accuracy track record and portfolio showpiece.

---

## Storage summary at steady state

| Table | Retention | Size |
|---|---|---|
| options_chain | 60 days | ~500–700 MB |
| news_raw | 7 days | ~5–10 MB |
| news_summaries | 30 days | ~1–2 MB |
| signals | Forever | ~2–5 MB (even after 1 year) |
| **Total** | | **~720 MB** |

Fits in SQLite on any laptop. Backs up to Google Drive as a single file copy daily.

---

## System architecture (4 layers)

```
DATA LAYER
  nsepython / Angel One API  →  OI feed  →  News RSS/NewsAPI

DETECTION LAYER
  Anomaly detector (OI surge, volume spike)
  IV skew tracker (put/call IV spread)
  Block trade filter (size threshold)
  Heuristic pre-filter (eliminates obvious hedges before LLM)

REASONING LAYER
  Signal scorer (ranks by significance)
  LLM thesis writer (Gemini Flash free → DeepSeek V3.2 in production)

DELIVERY LAYER
  Streamlit dashboard (live flow table)
  Telegram bot (daily alert digest)
  Daily markdown briefing
```

---

## Anomaly detection logic

**OI surge:** Flag if OI change > 2× rolling 20-day average for that strike.

**Volume spike:** Flag if volume > 3 standard deviations above 20-day mean.

**IV skew:** Compute put/call IV spread per expiry. Alert on unusual skew vs historical norm.

**Block trade:** Flag individual trades above a configurable size threshold.

**Heuristic pre-filter (runs before LLM, eliminates ~60% of boring signals):**
- Deep ITM options → likely synthetic position, skip
- Elevated put/call ratio already present → defensive positioning, label differently
- Offsetting positions same strike → spread trade, label accordingly

---

## LLM prompt structure

```
You are an expert options market analyst. Analyze the following unusual options activity
and generate a trading thesis.

SIGNAL DATA:
- Stock: {symbol}
- Expiry: {expiry}
- Strike: {strike} {option_type}
- OI change: +{oi_change} contracts ({oi_multiple}x above 20-day avg)
- Volume: {volume} ({volume_multiple}x normal)
- IV: {iv}% (vs {iv_avg}% historical avg)
- Spot price: {spot} (strike is {otm_pct}% OTM)
- Time to expiry: {dte} days

7-DAY CONTEXT:
{programmatic_summary_from_db}

RECENT NEWS (last 48hrs):
{news_summary}

Generate:
1. Positioning hypothesis (what might smart money be anticipating?)
2. Bull/bear bias: [BULLISH / BEARISH / NEUTRAL]
3. Confidence score: 1–5 with reasoning
4. Key risks that could invalidate this thesis
5. Similar historical setups if relevant

Be specific. Avoid generic statements. Show reasoning step by step.
```

The "7-day context" is generated programmatically from SQL — not raw data. Example:
```
OI has been building in 19500 CE since Monday (+180k total)
IV has risen 28% → 34% over 5 sessions
Two prior block trades: Tue 11am (50k), Thu 2pm (80k)
Price consolidated 1,320–1,345 for 4 days
```

---

## LLM model decision

**Why not a big model:** This task is structured financial analysis with a fixed prompt template. It does not need deep reasoning chains. A smaller, cheaper model with a well-designed prompt outperforms a reasoning model with a lazy prompt — and costs 20x less.

**Do NOT use reasoning/thinking models** (o-series, Gemini thinking mode) — they generate 10–30x more tokens per request unnecessarily for this type of structured output.

### Model comparison for this project

| Model | Input cost | Output cost | Your monthly cost | Verdict |
|---|---|---|---|---|
| Gemini 2.5 Flash (free tier) | Free | Free | ₹0 | Use during weeks 1–4 |
| DeepSeek V3.2 | $0.14/1M | $0.28/1M | ~₹6–7 | Use in production (weeks 5+) |
| Claude Haiku 4.5 | $1/1M | $5/1M | ~₹15 | Easy migration if already on Anthropic |
| GPT-5 Nano | $0.05/1M | $0.40/1M | ~₹1 | Cheapest paid, quality may be generic |

**Volume math:** ~10 signals/day × 1,200 tokens each = 12,000 tokens/day. Even expensive models cost almost nothing at this volume.

**Prompt caching tip:** Your system prompt is identical for every call. With caching enabled on DeepSeek, cached tokens cost ~90% less — bringing monthly cost even lower.

**Switching models is one line of code** — just swap the model string and API key. Test all of them once your prompt is locked in and pick whichever gives the best thesis quality.

---

## Alerts decision — Telegram over WhatsApp

**Chosen: Telegram Bot API**

Reasons WhatsApp was rejected:
- Requires Meta Business API approval + verified business account
- Charges per message via BSP (e.g. Twilio)
- Weeks of setup bureaucracy for a portfolio project

Reasons Telegram wins:
- Completely free, no approval process
- Create bot via @BotFather, get token, sending messages in 10 minutes
- Anyone who would use a trading signal tool already has Telegram

**WhatsApp is only the right choice** when end users are non-technical (e.g. civic bots, farmer advisory, SHG manager). For a developer trading tool, Telegram is the standard.

**Telegram core implementation (the whole integration in 4 lines):**
```python
import requests

def send_alert(token, chat_id, message):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": message})
```

**When to build it:** Week 6 — after the system is generating real signals. Building alerts early means sending yourself notifications about bugs.

---

Answers: "If I had followed my signals in the past, would I have made money?"

Process:
1. For every signal in the `signals` table, look up actual price 7 days later
2. Check if price moved in the thesis direction (BULLISH = price went up)
3. Record `outcome_correct` and `outcome_7d` back into the signals table
4. Generate report: accuracy by signal type, by confidence level, by market regime

Target output:
```
Total signals:        47
Correct direction:    31  (66% accuracy)
Best signal type:     OI surge on weekly expiry (78% accurate)
Worst signal type:    IV spike on far expiry  (41% accurate)
```

This report is the portfolio showstopper — almost nobody validates their signals.

---

## Week-by-week build plan

| Week | Focus | Deliverable |
|---|---|---|
| 1 | Data ingestion + SQLite storage | Live pipeline writing to DB every 5 min |
| 2 | Anomaly detection engine | Anomaly log with timestamped signals |
| 3 | LLM reasoning + news fetcher | JSON alert objects with thesis + confidence |
| 4 | Streamlit dashboard | Working end-to-end system with visual demo |
| 5 | Backtesting + accuracy evaluation | Accuracy report — the portfolio showstopper |
| 6 | Telegram alerts + Google Drive backup | Daily digest bot + automated .db backup |
| 7 | Polish + portfolio presentation | Live URL + GitHub + 3-min demo video |

**Build order rationale:** Alerts and backup are intentionally last. They add zero value while building and testing. Wire up Telegram only once the system is generating real signals you actually want to receive.

---

## Data sources — legality

- **NSE unofficial API** via `nsepython`: grey area legally, widely used by Indian developers, fine for portfolio/personal use. Not for commercial products.
- **Angel One SmartAPI**: fully official, free, requires Angel One demat account.
- **Zerodha Kite Connect**: official, ₹2,000/month, most powerful.
- **Yahoo Finance (`yfinance`)**: free, no auth, options data sparse/delayed for Indian stocks.

**Recommended starting point:** `nsepython` for Day 1 (zero setup). Upgrade to Angel One SmartAPI for reliability.

---

## Quick start (Day 1 — 5 lines)

```bash
pip install nsepython pandas sqlalchemy apscheduler
```

```python
from nsepython import nse_optionchain_scrapper
data = nse_optionchain_scrapper("NIFTY")
print(data['records']['data'][0])  # first strike's data
```

---

## Key constraints already resolved

| Challenge | Solution |
|---|---|
| "Real-time processing is too hard" | Poll every 5 min, not streaming. One API call, pandas diff. |
| "Context window for LLM" | Generate programmatic SQL summary string (~500 tokens), not raw data |
| "Can't distinguish hedge vs bet" | Heuristic pre-filter eliminates obvious hedges before LLM sees signal |
| "40–70MB per full cycle" | Tier 1 only = NIFTY chain = ~300–500KB per cycle. Trivially small. |
| "Storage will explode" | Long-format rows + 60-day rolling delete. Caps at ~720MB forever. |
| "Google Drive for DB?" | Use SQLite as actual DB, copy .db file to Drive daily as backup |

---

## Disclaimer to add to project

"This project is for educational and research purposes only. It does not constitute financial advice. All signals are for learning about market microstructure, not for making trading decisions."

---

## What's NOT built yet (future scope)

- Tier 2: mid-cap stocks on price-move trigger
- Tier 3: on-demand stocks
- Real-time streaming (current design is poll-based)
- Execution / paper trading integration
- Multi-index support beyond NIFTY/BANKNIFTY
- Mobile app / WhatsApp alerts

---

## Reference & Resources

Links saved for use during frontend build (Week 4+) and beyond.
Add new links here as the project grows.

### Charting & Visualization
| Resource | URL | How to use |
|---|---|---|
| TradingView Lightweight Charts | https://www.tradingview.com/lightweight-charts/ | Embed NIFTY price + OI charts in Streamlit via `st.components.v1.html()`. Use for candlestick, histogram (OI), and signal marker overlays. Apache 2.0 — free to use. |
| Lightweight Charts Docs | https://tradingview.github.io/lightweight-charts/ | Official docs. Start with the realtime updates tutorial — directly relevant to the 5-min polling loop. |

### UI/UX Design Reference
| Resource | URL | How to use |
|---|---|---|
| Unusual Whales | https://unusualwhales.com/ | Design inspiration only (paid SaaS). Reference for: flow table layout, CE/PE color coding, block trade badge style, OI heatmap by strike. |

### Chart Type Reference
| Resource | URL | How to use |
|---|---|---|
| DataVizProject | https://datavizproject.com/ | Visual encyclopedia of chart types. Consult when deciding which chart to use for OI heatmaps, IV skew, volume distribution, etc. No code — pure reference. |

### UI Component Libraries
| Resource | URL | How to use |
|---|---|---|
| Tailwind UI — App UI | https://tailwindcss.com/plus/ui-blocks/application-ui | Paid component library. Reference for flow table layout, signal cards, stats panels, sidebar layouts, navbars. Buy license or use as design inspiration only. |
| Flowbite Charts | https://flowbite.com/docs/plugins/charts/ | Free, open-source Tailwind + Chart.js components with dark mode support. Use directly in Streamlit HTML embeds or standalone frontend. Free alternative to Tailwind UI for charts. |

### To be added
- News / RSS feed sources
- Angel One SmartAPI docs
- DeepSeek API docs
- Any other tools, datasets, or references

---

*Context file v2 — generated from full project planning conversation. Resume building from Week 1 code.*
