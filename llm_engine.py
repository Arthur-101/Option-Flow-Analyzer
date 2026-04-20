# llm_engine.py — LLM thesis generation using DeepSeek V3 via OpenRouter
#
# Takes a signal + market context + news headlines.
# Returns structured thesis: text, bias, confidence.
# Writes results back to signals table.
#
# Design principles:
# - System prompt is CONSTANT → enables better reasoning consistency
# - Context is variable → injected per call
# - LLM interprets contradictions, never hardcoded rules
# - Max 20 calls per poll cycle (DeepSeek has higher limits than Gemini)

import os
import json
import logging
import sqlite3
import requests
import time
from datetime import datetime, timezone
from config import DB_PATH

logger = logging.getLogger(__name__)

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL   = os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-v3.2")  # DeepSeek V3
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

MAX_CALLS_PER_CYCLE = 20   # DeepSeek handles higher throughput than Gemini
DELAY_BETWEEN_CALLS = 1.5  # 1 second delay between calls for safety

# ── System prompt (CONSTANT — enables reasoning consistency) ───────────────────

SYSTEM_PROMPT = """You are an institutional options flow analyst specializing in NSE NIFTY index options.

Your role is to interpret unusual options flow signals and generate concise, actionable trading theses.

You understand:
- OI_BUILDUP means new positions are being opened (directional intent)
- OI_UNWIND means positions are being closed (potential reversal or target achieved)
- VOLUME_SPIKE with flat OI means intraday speculation (less conviction)
- IV_SPIKE means elevated premium payment, often before an expected move
- PCR > 1.3 indicates defensive/bearish market positioning
- PCR < 0.7 indicates aggressive/bullish positioning
- RSI > 70 means market is extended (signals may be late-stage)
- RSI < 30 means market is oversold (signals may be counter-trend bounce)
- MACD crossover direction confirms or contradicts the flow signal

Rules:
1. Never make categorical buy/sell recommendations
2. Express uncertainty when context is ambiguous or contradictory
3. Consider whether flow is institutional (large OI, specific expiry) or retail (scattered strikes)
4. A CE buildup during high PCR environment means smart money is going against the crowd
5. Always reason about WHO is likely making this trade and WHY

Output ONLY valid JSON. No markdown, no explanation outside the JSON.

JSON format:
{
  "thesis": "2-3 sentence analytical thesis explaining the signal in market context",
  "bias": "BULLISH" | "BEARISH" | "NEUTRAL",
  "confidence": 1-5,
  "reasoning_notes": "brief note on key contradictions or confirmations that drove your assessment"
}

Confidence scale:
1 = very uncertain, contradictory signals
2 = weak signal, limited confirmation  
3 = moderate conviction, some confirmation
4 = strong signal, multiple confirmations
5 = very high conviction, clear institutional intent with confirming context"""


# ── Prompt builder ─────────────────────────────────────────────────────────────

def _build_prompt(signal: dict, context: dict, headlines: list[str]) -> str:
    """
    Builds the variable part of the prompt.
    Structured clearly so LLM can reason about confirmations and contradictions.
    """

    # Format MACD
    macd = context.get("macd")
    macd_str = "insufficient data"
    if macd:
        macd_str = (
            f"MACD={macd['macd_line']} Signal={macd['signal_line']} "
            f"Histogram={macd['histogram']} ({macd['crossover']} crossover, "
            f"momentum {macd['momentum']})"
        )

    # Format news
    news_str = "No recent relevant news available."
    if headlines:
        news_str = "\n".join(f"- {h}" for h in headlines)

    prompt = f"""Analyse this NIFTY options flow signal and generate a thesis.

=== SIGNAL ===
Type: {signal['signal_type']}
Strike: {signal['strike']} {signal['option_type']}
Expiry: {signal['expiry']}
OI Change: {signal.get('oi_change', 'N/A')} contracts
Volume: {signal.get('volume', 'N/A')}
IV: {signal.get('iv', 'N/A')}%
Signal Strength: {signal.get('signal_strength', 'N/A')}/5
Detection Mode: {signal.get('mode', 'N/A')}

=== MARKET CONTEXT ===
NIFTY Spot: {context.get('current_spot', 'N/A')}
Session Open: {context.get('session_open', 'N/A')}
Session Move: {context.get('session_move_pct', 'N/A')}%
Spot vs VWAP: {context.get('spot_vs_vwap', 'N/A')}
VWAP: {context.get('vwap', 'N/A')}

RSI(14): {context.get('rsi', 'N/A')} → {context.get('rsi_state', 'N/A')}
MACD: {macd_str}

PCR: {context.get('pcr', 'N/A')} → {context.get('pcr_state', 'N/A')}
Total CE OI: {context.get('total_ce_oi', 'N/A')}
Total PE OI: {context.get('total_pe_oi', 'N/A')}

=== RECENT NEWS ===
{news_str}

Generate your thesis JSON now:"""

    return prompt


# ── OpenRouter API call ────────────────────────────────────────────────────────

def _call_openrouter(prompt: str) -> dict | None:
    """
    Call OpenRouter API (DeepSeek V3) and parse JSON response.
    Returns parsed dict or None on failure.
    """
    if not OPENROUTER_API_KEY:
        logger.error("OPENROUTER_API_KEY not set")
        return None

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "HTTP-Referer": "https://github.com/Arthur-101/Option-Flow-Analyzer",  # Optional - for rankings
        "X-Title": "Options Flow Analyzer",  # Optional - shows in OpenRouter dashboard
        "Content-Type": "application/json"
    }

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {
                "role": "system",
                "content": SYSTEM_PROMPT
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        "temperature": 0.3,
        "max_tokens": 1024,
        "response_format": {"type": "json_object"}  # Force JSON output
    }

    try:
        resp = requests.post(
            OPENROUTER_API_URL,
            headers=headers,
            json=payload,
            timeout=60,  # DeepSeek V3 can take longer than Gemini
        )
        resp.raise_for_status()
        data = resp.json()

        # Extract response content
        text = data["choices"][0]["message"]["content"].strip()

        # Strip markdown fences if present (some models still add them)
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()

        # Find JSON object if wrapped in other text
        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end > start:
            text = text[start:end]

        return json.loads(text)

    except requests.RequestException as e:
        logger.error("OpenRouter API request failed: %s", e)
        if hasattr(e, 'response') and e.response is not None:
            try:
                error_detail = e.response.json()
                logger.error("Error details: %s", error_detail)
            except:
                logger.error("Response text: %s", e.response.text[:500])
    except (KeyError, IndexError) as e:
        logger.error("OpenRouter response parse error: %s", e)
    except json.JSONDecodeError as e:
        logger.error("OpenRouter returned invalid JSON: %s | Raw text: %s", e, text[:200])

    return None


# ── DB write ───────────────────────────────────────────────────────────────────

def _write_thesis_to_db(signal_id: int, result: dict) -> None:
    """Write LLM output back to the signals table."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        UPDATE signals
        SET llm_thesis     = ?,
            llm_bias       = ?,
            llm_confidence = ?
        WHERE id = ?
    """, (
        result.get("thesis"),
        result.get("bias"),
        result.get("confidence"),
        signal_id,
    ))
    conn.commit()
    conn.close()
    logger.info(
        "Signal %d thesis written: bias=%s confidence=%d",
        signal_id, result.get("bias"), result.get("confidence", 0)
    )


# ── Main entry point ───────────────────────────────────────────────────────────

def generate_theses(signals: list[dict], context: dict, headlines: list[str]) -> int:
    """
    Generate LLM theses for a list of signals.
    Writes results directly to signals table.

    Args:
        signals:   list of signal dicts (must include 'id' field)
        context:   market context dict from context.py
        headlines: list of news headline strings from news_fetcher.py

    Returns:
        Number of theses successfully generated.
    """
    if not signals:
        return 0

    if not OPENROUTER_API_KEY:
        logger.warning("OPENROUTER_API_KEY not set — skipping LLM thesis generation")
        return 0

    # Rate limit: only process top N signals per cycle
    # Prioritise by signal_strength descending
    sorted_signals = sorted(
        signals,
        key=lambda s: s.get("signal_strength", 0),
        reverse=True
    )[:MAX_CALLS_PER_CYCLE]

    generated = 0
    for i, signal in enumerate(sorted_signals):
        signal_id = signal.get("id")
        if not signal_id:
            logger.warning("Signal missing id field — skipping")
            continue

        try:
            prompt = _build_prompt(signal, context, headlines)
            result = _call_openrouter(prompt)

            if result:
                _write_thesis_to_db(signal_id, result)
                generated += 1
                logger.info(
                    "Thesis: %s %s %.0f %s → %s (confidence %d): %s",
                    signal["signal_type"], signal["symbol"],
                    signal.get("strike", 0), signal.get("option_type", ""),
                    result.get("bias"), result.get("confidence", 0),
                    result.get("thesis", "")[:80] + "..."
                )
            else:
                logger.warning("No thesis generated for signal %d", signal_id)

            # Rate limiting delay (except after last call)
            if i < len(sorted_signals) - 1:
                time.sleep(DELAY_BETWEEN_CALLS)

        except Exception as e:
            logger.error("Thesis generation error for signal %d: %s", signal_id, e)

    logger.info("Thesis generation complete: %d/%d signals processed",
                generated, len(sorted_signals))
    return generated