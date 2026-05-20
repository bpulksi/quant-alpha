"""
Ollama LLM Sentiment Analyst — with VADER fallback
====================================================
Scores crypto news headlines from -1.0 (very bearish) to +1.0 (very bullish).
Uses local llama3.2:3b via Ollama; falls back to VADER if Ollama is unavailable.

Standalone test:
  python ollama_analyst.py
"""

import json, re, urllib.request, urllib.parse, os
from functools import lru_cache
from dotenv import load_dotenv
load_dotenv()

OLLAMA_BASE   = "http://localhost:11434"
OLLAMA_MODEL  = os.getenv("OLLAMA_MODEL", "llama3.2:3b")

# ─── Ollama helpers ───────────────────────────────────────────────────────────

def check_ollama_running() -> bool:
    try:
        req = urllib.request.Request(f"{OLLAMA_BASE}/api/tags")
        urllib.request.urlopen(req, timeout=2)
        return True
    except Exception:
        return False

@lru_cache(maxsize=128)
def _cached_score_with_ollama(ticker: str, headlines: tuple) -> dict:
    top = headlines[:10]
    hl_text = "\n".join(f"- {h}" for h in top)
    prompt = (
        f"Analyse these crypto news headlines for {ticker}. "
        f"Return ONLY valid JSON with no extra text:\n"
        f"{{\"score\": 0.0, \"reasoning\": \"...\", \"key_events\": [\"...\", \"...\"]}}\n"
        f"Score range: -1.0 (very bearish) to +1.0 (very bullish).\n\n"
        f"Headlines:\n{hl_text}"
    )
    body = json.dumps({
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1},
    }).encode()
    try:
        req = urllib.request.Request(
            f"{OLLAMA_BASE}/api/generate",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req, timeout=45)
        data = json.loads(resp.read())
        raw  = data.get("response", "")
        # Extract JSON from response
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            result = json.loads(match.group())
            score  = float(result.get("score", 0.0))
            score  = max(-1.0, min(1.0, score))
            return {
                "score":      score,
                "reasoning":  result.get("reasoning", ""),
                "key_events": result.get("key_events", []),
                "source":     "ollama",
                "model":      OLLAMA_MODEL,
            }
    except Exception as e:
        print(f"  [Ollama] Error: {e}")
    return None

def score_with_ollama(ticker: str, headlines: list) -> dict:
    """Wrapper to make headlines hashable for the lru_cache."""
    return _cached_score_with_ollama(ticker, tuple(headlines))

# ─── VADER fallback ───────────────────────────────────────────────────────────

def score_with_vader(headlines: list) -> dict:
    try:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        sia = SentimentIntensityAnalyzer()
        scores = [sia.polarity_scores(h)["compound"] for h in headlines]
        avg   = sum(scores) / len(scores) if scores else 0.0
        return {
            "score":      round(avg, 4),
            "reasoning":  f"VADER average of {len(scores)} headlines",
            "key_events": [],
            "source":     "vader",
        }
    except Exception as e:
        return {"score": 0.0, "reasoning": f"VADER failed: {e}", "key_events": [], "source": "error"}

# ─── Main entry ───────────────────────────────────────────────────────────────

def score_news(ticker: str, headlines: list) -> dict:
    """Try Ollama first, fall back to VADER automatically."""
    if not headlines:
        return {"score": 0.0, "reasoning": "No headlines", "key_events": [], "source": "none"}
    if check_ollama_running():
        result = score_with_ollama(ticker, headlines)
        if result:
            return result
        print(f"  [Ollama] Fell back to VADER for {ticker}")
    else:
        print(f"  [Ollama] Not running — using VADER for {ticker}")
    return score_with_vader(headlines)


# ─── Standalone test ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    test_headlines = [
        "Bitcoin ETF sees $500M inflow as institutional demand surges",
        "Crypto market rallies amid positive macro data",
        "BTC breaks resistance at $90K on heavy volume",
        "Whale wallets accumulate Bitcoin ahead of halving",
        "SEC approves spot Bitcoin ETF for three more issuers",
    ]
    print(f"Ollama running: {check_ollama_running()}")
    result = score_news("BTC", test_headlines)
    print(json.dumps(result, indent=2))
