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
from dotenv import load_dotenv
from config import DB_PATH

load_dotenv()
logger = logging.getLogger(__name__)

# ── LLM Configuration (OpenAI-compatible: OpenRouter, DeepSeek, Groq, etc.) ───
LLM_API_KEY = os.getenv("LLM_API_KEY") or os.getenv("OPENROUTER_API_KEY")
LLM_API_URL = os.getenv("LLM_API_URL") or os.getenv("OPENROUTER_API_URL", "https://openrouter.ai/api/v1/chat/completions")

# Model Fallback Chain — comma-separated, tried in order.
# If LLM_MODELS is set, it takes priority. Otherwise falls back to LLM_MODEL.
_models_raw = os.getenv("LLM_MODELS", "")
LLM_MODELS = [m.strip() for m in _models_raw.split(",") if m.strip()]
if not LLM_MODELS:
    LLM_MODELS = [os.getenv("LLM_MODEL") or os.getenv("OPENROUTER_MODEL", "bytedance-seed/seed-1.6-flash")]
LLM_MODEL = LLM_MODELS[0]  # Primary model (first in chain)

# Aliases for backward compatibility
OPENROUTER_API_KEY = LLM_API_KEY
OPENROUTER_API_URL = LLM_API_URL
OPENROUTER_MODEL   = LLM_MODEL

# HTTP status codes that trigger fallback to next model
# 404 included because OpenRouter returns it when a free model variant is retired
_RETRYABLE_STATUS_CODES = {404, 429, 500, 502, 503, 504}

MAX_CALLS_PER_CYCLE = 20
DELAY_BETWEEN_CALLS = 1.5  # 1.5 second delay between calls for safety

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


# ── LLM API call with Cascading Model Fallback ───────────────────────────────

def _call_single_model(prompt: str, model: str) -> dict | None:
    """
    Call a single OpenAI-compatible LLM model and parse JSON response.
    Returns (parsed_dict, None) on success, or (None, error_info) on failure.
    Raises _ModelRetryable for errors that should trigger fallback.
    """
    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "HTTP-Referer": "https://github.com/Arthur-101/Option-Flow-Analyzer",
        "X-Title": "Options Flow Analyzer",
        "Content-Type": "application/json"
    }

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.3,
        "max_tokens": 1024,
        "response_format": {"type": "json_object"}
    }

    resp = requests.post(
        LLM_API_URL,
        headers=headers,
        json=payload,
        timeout=30,
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


def _call_llm(prompt: str) -> dict | None:
    """
    Cascading Model Fallback — tries each model in LLM_MODELS sequentially.

    Falls back to the next model on:
      - HTTP 429 (rate limited), 500/502/503/504 (server errors)
      - Timeout / connection errors
      - HTTP 400 (context length / bad request)
      - Invalid JSON output from the model

    Returns parsed thesis dict on success, or None if ALL models fail.
    """
    if not LLM_API_KEY:
        logger.error("LLM_API_KEY (or OPENROUTER_API_KEY) not set in .env")
        return None

    total = len(LLM_MODELS)

    for idx, model in enumerate(LLM_MODELS, 1):
        try:
            logger.info("[Model %d/%d] Trying %s...", idx, total, model)
            result = _call_single_model(prompt, model)
            logger.info("[Model %d/%d] ✅ %s responded successfully", idx, total, model)
            return result

        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else 0
            # Try to extract error message for logging
            err_msg = ""
            if e.response is not None:
                try:
                    err_msg = e.response.json().get("error", {}).get("message", "")[:200]
                except Exception:
                    err_msg = e.response.text[:200]

            if status in _RETRYABLE_STATUS_CODES:
                logger.warning(
                    "[Model %d/%d] ⚠️ %s returned HTTP %d (retryable): %s",
                    idx, total, model, status, err_msg
                )
                # Continue to next model
            elif status == 400:
                logger.warning(
                    "[Model %d/%d] ⚠️ %s returned HTTP 400 (bad request / context length): %s",
                    idx, total, model, err_msg
                )
                # Continue to next model
            elif status == 403:
                logger.warning(
                    "[Model %d/%d] ⚠️ %s returned HTTP 403 (model restricted/gated): %s",
                    idx, total, model, err_msg
                )
                # Continue to next model
            elif status == 401:
                logger.error(
                    "[Model %d/%d] ❌ %s returned HTTP 401 (Unauthorized): Check your LLM_API_KEY in .env",
                    idx, total, model
                )
                return None  # Bad API key — don't bother trying other models
            else:
                logger.warning(
                    "[Model %d/%d] ⚠️ %s returned HTTP %d: %s",
                    idx, total, model, status, err_msg
                )
                # Continue to next model

        except (requests.ConnectionError, requests.Timeout) as e:
            logger.warning(
                "[Model %d/%d] ⚠️ %s timed out or connection failed: %s",
                idx, total, model, e
            )
            # Continue to next model

        except json.JSONDecodeError as e:
            logger.warning(
                "[Model %d/%d] ⚠️ %s returned invalid JSON: %s",
                idx, total, model, e
            )
            # Continue to next model (a different model may produce valid JSON)

        except (KeyError, IndexError) as e:
            logger.warning(
                "[Model %d/%d] ⚠️ %s response parse error: %s",
                idx, total, model, e
            )
            # Continue to next model

        except Exception as e:
            logger.error(
                "[Model %d/%d] ❌ %s unexpected error: %s",
                idx, total, model, e
            )
            # Continue to next model

    logger.error("All %d models in the fallback chain failed", total)
    return None


# Backward-compatible alias
_call_openrouter = _call_llm


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
    Uses cascading model fallback — tries each model in LLM_MODELS sequentially.
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

    if not LLM_API_KEY:
        logger.warning("LLM_API_KEY (or OPENROUTER_API_KEY) not set — skipping LLM thesis generation")
        return 0

    logger.info(
        "LLM Model Chain (%d models): %s",
        len(LLM_MODELS), " → ".join(LLM_MODELS)
    )

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
            result = _call_llm(prompt)

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
                logger.warning("No thesis generated for signal %d (all models failed)", signal_id)

            # Rate limiting delay (except after last call)
            if i < len(sorted_signals) - 1:
                time.sleep(DELAY_BETWEEN_CALLS)

        except Exception as e:
            logger.error("Thesis generation error for signal %d: %s", signal_id, e)

    logger.info("Thesis generation complete: %d/%d signals processed",
                generated, len(sorted_signals))
    return generated