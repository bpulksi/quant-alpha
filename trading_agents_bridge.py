"""
TradingAgents Bridge — Multi-Agent LLM Analysis for Crypto
============================================================
Wraps TauricResearch/TradingAgents to run a full multi-agent debate
(Technical → Sentiment → News → Bull/Bear Researchers → Trader → Risk → Portfolio Manager)
using Ollama (llama3.2:3b) locally — 100% free, no API keys needed.

Output feeds into opportunity_ranker.py as the highest-weight signal.

Standalone test:
  python trading_agents_bridge.py BTC
  python trading_agents_bridge.py ETH
"""

import os, sys, json, time
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
load_dotenv()

BOT_DIR    = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(BOT_DIR, "ta_signal_cache.json")

# Map our USDT symbols -> yfinance crypto format
SYMBOL_MAP = {
    "BTCUSDT": "BTC-USD",  "ETHUSDT": "ETH-USD",  "SOLUSDT": "SOL-USD",
    "XRPUSDT": "XRP-USD",  "AVAXUSDT": "AVAX-USD", "ADAUSDT": "ADA-USD",
    "DOTUSDT": "DOT-USD",  "LINKUSDT": "LINK-USD", "LTCUSDT": "LTC-USD",
    "DOGEUSDT": "DOGE-USD","BNBUSDT":  "BNB-USD",  "SUIUSDT": "SUI-USD",
}

# Stock symbols -- plain tickers, yfinance uses them directly
STOCK_SYMBOLS = {
    "AAPL","MSFT","NVDA","GOOGL","META","AMZN","TSLA",
    "SPY","QQQ","IWM","COIN","MSTR","PLTR","AMD","SOFI",
}

def is_stock(symbol: str) -> bool:
    """True if this is a plain stock ticker (not a USDT crypto pair)."""
    upper = symbol.upper()
    return not upper.endswith("USDT") and upper.replace("USDT","") in STOCK_SYMBOLS or upper in STOCK_SYMBOLS

# Decision string → numeric score mapping
# Also covers free-text fallback phrases from llama3.2:3b
DECISION_SCORES = {
    "strong buy":   1.0,
    "overweight":   0.7,   # portfolio manager free-text equivalent of buy
    "buy":          0.7,
    "hold":         0.0,
    "neutral":      0.0,
    "underweight": -0.7,   # portfolio manager free-text equivalent of sell
    "sell":        -0.7,
    "strong sell":  -1.0,
}

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
# Cache TTL: re-run analysis every N hours (TradingAgents takes ~2-5 min per asset)
CACHE_TTL_HOURS = 4

# ─── Cache helpers ────────────────────────────────────────────────────────────

def _load_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE) as f:
            return json.load(f)
    return {}

def _save_cache(cache: dict):
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)

def _cache_fresh(entry: dict, ttl_hours: float = CACHE_TTL_HOURS) -> bool:
    ts = entry.get("timestamp")
    if not ts:
        return False
    age = (datetime.now(timezone.utc).timestamp() - datetime.fromisoformat(ts).timestamp()) / 3600
    return age < ttl_hours

# ─── Core analysis function ───────────────────────────────────────────────────

def get_ta_signal(symbol: str, force_refresh: bool = False) -> dict:
    """
    Run TradingAgents full multi-agent analysis for one symbol.
    Returns cached result if fresh enough.

    Result dict:
    {
        "symbol": "BTCUSDT",
        "yf_ticker": "BTC-USD",
        "decision": "buy",           # raw decision string
        "ta_score": 0.7,             # -1.0 to +1.0
        "reasoning": "...",          # summary from agents
        "timestamp": "...",
        "source": "trading_agents" | "cache" | "error"
    }
    """
    # Normalise symbol
    symbol = symbol.upper()
    # Only append USDT for crypto symbols not already in stock list and not ending in USDT
    if symbol not in STOCK_SYMBOLS and not symbol.endswith("USDT"):
        symbol = symbol + "USDT"

    # Determine yfinance ticker
    if symbol in STOCK_SYMBOLS:
        yf_ticker = symbol   # stocks: AAPL, MSFT, etc. work directly in yfinance
    else:
        yf_ticker = SYMBOL_MAP.get(symbol)
    if not yf_ticker:
        return {"symbol": symbol, "ta_score": 0.0, "decision": "hold",
                "reasoning": f"No yfinance mapping for {symbol}", "source": "error"}

    # Check cache
    cache = _load_cache()
    if not force_refresh and symbol in cache and _cache_fresh(cache[symbol]):
        result = cache[symbol].copy()
        result["source"] = "cache"
        print(f"  [TA] {symbol} — using cached result ({result['decision']}, score={result['ta_score']})")
        return result

    # Run TradingAgents
    print(f"  [TA] Running multi-agent analysis for {symbol} ({yf_ticker})...")
    t0 = time.time()

    try:
        from tradingagents.graph.trading_graph import TradingAgentsGraph
        from tradingagents.default_config import DEFAULT_CONFIG

        config = DEFAULT_CONFIG.copy()
        config["llm_provider"]    = "ollama"
        config["deep_think_llm"]  = OLLAMA_MODEL
        config["quick_think_llm"] = OLLAMA_MODEL
        config["backend_url"]     = "http://localhost:11434/v1"
        config["max_debate_rounds"]       = 1   # 1 round = faster, still thorough
        config["max_risk_discuss_rounds"] = 1
        config["output_language"]  = "English"

        # Stocks get fundamentals analyst (P/E, earnings, balance sheet)
        # Crypto skips fundamentals -- no balance sheets / P/E ratios
        analysts = ["market", "social", "news", "fundamentals"] if symbol in STOCK_SYMBOLS else ["market", "social", "news"]
        ta = TradingAgentsGraph(
            selected_analysts=analysts,
            debug=False,
            config=config,
        )

        trade_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        _, decision_raw = ta.propagate(yf_ticker, trade_date)

        # Parse decision string
        decision_str  = str(decision_raw).lower().strip()
        ta_score = 0.0
        matched  = "hold"
        for key, score in sorted(DECISION_SCORES.items(), key=lambda x: -len(x[0])):
            if key in decision_str:
                ta_score = score
                matched  = key
                break

        elapsed = time.time() - t0
        print(f"  [TA] {symbol} -> {matched} (score={ta_score:.1f}) in {elapsed:.0f}s")

        result = {
            "symbol":    symbol,
            "yf_ticker": yf_ticker,
            "decision":  matched,
            "ta_score":  ta_score,
            "reasoning": (decision_raw[:500] if isinstance(decision_raw, str) else str(decision_raw)[:500]).encode("ascii", "replace").decode("ascii"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source":    "trading_agents",
            "elapsed_s": round(elapsed, 1),
        }

        # Cache it
        cache[symbol] = result
        _save_cache(cache)
        return result

    except Exception as e:
        elapsed = time.time() - t0
        print(f"  [TA] Error for {symbol}: {e}")
        result = {
            "symbol":    symbol,
            "yf_ticker": yf_ticker,
            "decision":  "hold",
            "ta_score":  0.0,
            "reasoning": str(e).encode("ascii", "replace").decode("ascii"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source":    "error",
            "elapsed_s": round(elapsed, 1),
        }
        cache[symbol] = result
        _save_cache(cache)
        return result

# ─── Standalone test ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    sym = sys.argv[1] if len(sys.argv) > 1 else "BTC"
    if not sym.endswith("USDT"):
        sym = sym.upper() + "USDT"

    force = "--force" in sys.argv
    print(f"\nTradingAgents bridge — analysing {sym} (force={force})\n")
    result = get_ta_signal(sym, force_refresh=force)
    print(json.dumps(result, indent=2))
