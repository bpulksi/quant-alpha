"""
Research Agent — CLI Orchestrator
===================================
Combines news, Ollama sentiment, arbitrage, TradingAgents, and opportunity scoring.
Writes research_state.json for dashboard. Sends Telegram alerts.

Usage:
  python research_agent.py signal BTCUSDT [--quant-data '{"confidence":0.75,"action":"BUY","volume_ratio":1.8}']
  python research_agent.py scan          # all crypto + stock assets, writes research_state.json
  python research_agent.py arbitrage     # arbitrage-only, fast
"""

import os, sys, json, argparse
from datetime import datetime, timezone
from dotenv import load_dotenv
load_dotenv()

from state_manager import save_json

CRYPTO_SYMBOLS = os.getenv(
    "SYMBOL",
    "BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT,AVAXUSDT,ADAUSDT,DOTUSDT,LINKUSDT,LTCUSDT,DOGEUSDT,BNBUSDT,SUIUSDT"
).split(",")

STOCK_SYMBOLS_ENV = os.getenv(
    "STOCK_SYMBOLS",
    "AAPL,MSFT,NVDA,GOOGL,META,AMZN,TSLA,SPY,QQQ,IWM,COIN,MSTR,PLTR,AMD,SOFI"
).split(",")

# Combined list: crypto first, then stocks
SYMBOLS = CRYPTO_SYMBOLS + STOCK_SYMBOLS_ENV

ENABLE_TA = os.getenv("ENABLE_TRADING_AGENTS", "false").lower() == "true"

from news_fetcher        import fetch_all_news, is_stock
from ollama_analyst      import score_news, check_ollama_running
from arbitrage_scanner   import scan_asset, scan_arbitrage
from opportunity_ranker  import compute_opportunity_score, rank_opportunities
from macro_intelligence  import blend_macro_into_news, get_macro_score

# ─── Core signal function ─────────────────────────────────────────────────────

def research_signal(symbol: str, quant: dict = None) -> dict:
    """
    Full research pass for one symbol.
    quant: {"confidence": float, "action": str, "volume_ratio": float}
    Returns the full signal dict (also printed as JSON for multi_trader.js).
    """
    if quant is None:
        quant = {"confidence": 0.5, "action": "BUY", "volume_ratio": 1.0}

    ml_conf      = float(quant.get("confidence", 0.5))
    ml_action    = str(quant.get("action", "BUY"))
    volume_ratio = float(quant.get("volume_ratio", 1.0))

    stock = is_stock(symbol)

    # 1. News + sentiment
    news_items = fetch_all_news(symbol, lookback_hours=24)
    headlines  = [n["title"] for n in news_items]
    # For stocks use ticker as-is; for crypto strip USDT
    ticker_for_sentiment = symbol if stock else symbol.replace("USDT", "")
    sentiment  = score_news(ticker_for_sentiment, headlines)

    # 2. Arbitrage -- crypto only (stocks have no cross-exchange spread to exploit)
    if stock:
        arb = {"spread_pct": 0.0, "net_spread": 0.0, "is_actionable": False,
               "buy_exchange": "", "sell_exchange": "", "prices": {}}
    else:
        arb = scan_asset(symbol)

    # 3. TradingAgents multi-agent analysis (opt-in — slow ~3 min/asset)
    ta_score    = None
    ta_decision = None
    ta_reasoning = None
    ta_source   = "disabled"

    if ENABLE_TA:
        try:
            from trading_agents_bridge import get_ta_signal
            print(f"  [TA] Fetching TradingAgents signal for {symbol}...")
            ta_result   = get_ta_signal(symbol)
            ta_score    = ta_result.get("ta_score", 0.0)
            ta_decision = ta_result.get("decision", "hold")
            ta_reasoning = ta_result.get("reasoning", "")
            ta_source   = ta_result.get("source", "trading_agents")
        except Exception as e:
            print(f"  [TA] TradingAgents unavailable: {e}")
            ta_source = f"error: {e}"

    # 4. Macro intelligence overlay (expert signals, decay-weighted)
    macro_result = get_macro_score(symbol)
    macro_score  = macro_result["macro_score"]   # -1 to +1
    # Blend macro into news score (30% macro weight -- soft overlay, not override)
    blended_news = blend_macro_into_news(sentiment["score"], symbol, weight=0.30)

    # 5. Opportunity score (with or without TA)
    ranking = compute_opportunity_score(
        ml_confidence  = ml_conf,
        ml_action      = ml_action,
        news_score     = blended_news,      # macro-adjusted news score
        arb_net_spread = arb.get("net_spread", 0.0),
        volume_ratio   = volume_ratio,
        ta_score       = ta_score,
    )

    result = {
        "symbol":               symbol,
        "timestamp":            datetime.now(timezone.utc).isoformat(),
        "ollama_available":     check_ollama_running(),

        # News
        "news_count":           len(news_items),
        "news_score":           round(sentiment["score"], 4),
        "news_reasoning":       sentiment.get("reasoning", ""),
        "key_events":           sentiment.get("key_events", []),
        "sentiment_source":     sentiment.get("source", "none"),

        # Arbitrage
        "arbitrage_spread_pct": arb.get("spread_pct", 0.0),
        "arbitrage_net_pct":    arb.get("net_spread", 0.0),
        "arbitrage_actionable": arb.get("is_actionable", False),
        "arb_buy_exchange":     arb.get("buy_exchange", ""),
        "arb_sell_exchange":    arb.get("sell_exchange", ""),
        "prices":               arb.get("prices", {}),

        # TradingAgents
        "ta_score":             ta_score,
        "ta_decision":          ta_decision,
        "ta_reasoning":         ta_reasoning,
        "ta_source":            ta_source,
        "trading_agents_enabled": ENABLE_TA,

        # Macro intelligence
        "macro_score":          macro_score,
        "macro_summary":        macro_result["summary"],
        "macro_signal_count":   macro_result["signal_count"],
        "news_score_raw":       round(sentiment["score"], 4),    # pre-macro
        "news_score_blended":   round(blended_news, 4),          # post-macro

        # Final score
        "opportunity_score":    ranking["opportunity_score"],
        "is_actionable":        ranking["is_actionable"],
        "score_components":     ranking["components"],
    }
    return result

# ─── Full scan ────────────────────────────────────────────────────────────────

def research_scan() -> list:
    """Run research_signal for all SYMBOLS (no quant data — uses neutral defaults)."""
    results = []
    for sym in SYMBOLS:
        print(f"  Scanning {sym}...", end=" ", flush=True)
        try:
            r = research_signal(sym)
            results.append(r)
            ta_str = f"  ta={r['ta_score']:+.2f}" if r["ta_score"] is not None else ""
            print(f"score={r['opportunity_score']:.3f}  news={r['news_score']:+.2f}"
                  f"  arb={r['arbitrage_net_pct']:.3f}%{ta_str}")
        except Exception as e:
            print(f"ERROR: {e}")
    return rank_opportunities(results)

# ─── Write research_state.json ────────────────────────────────────────────────

def write_research_state(results: list, arb_results: list = None):
    state = {
        "last_updated":     datetime.now(timezone.utc).isoformat(),
        "ollama_available": check_ollama_running(),
        "trading_agents_enabled": ENABLE_TA,
        "crypto_count":     len(CRYPTO_SYMBOLS),
        "stock_count":      len(STOCK_SYMBOLS_ENV),
        "top_opportunities": results[:5],
        "actionable":       [r for r in results if r.get("is_actionable")],
        "arbitrage_alerts": [r for r in (arb_results or results) if r.get("arbitrage_actionable")],
        "all_results":      results,
    }
    save_json("research_state.json", state)
    print(f"\n  [OK] research_state.json written ({len(results)} assets)")

# ─── Telegram alerts ─────────────────────────────────────────────────────────

def send_research_telegram(results: list):
    from telegram_notify import send_message
    actionable = [r for r in results if r.get("is_actionable")]
    if not actionable:
        return
    lines = ["*Research Intelligence Alert*\n"]
    for r in actionable[:5]:
        sym   = r["symbol"]
        score = r["opportunity_score"]
        news  = r["news_score"]
        arb   = r["arbitrage_net_pct"]
        ta    = r.get("ta_score")
        lines.append(f"*{sym}* — score `{score:.3f}`")
        lines.append(f"  News: `{news:+.2f}` | Arb net: `{arb:.3f}%`")
        if ta is not None:
            lines.append(f"  TradingAgents: `{r.get('ta_decision','?')}` (score `{ta:+.2f}`)")
        if r.get("key_events"):
            lines.append(f"  _{r['key_events'][0][:80]}_")
    lines.append(f"\n_Scanned: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_")
    send_message("\n".join(lines))

# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Research Agent")
    parser.add_argument("command", choices=["signal", "scan", "arbitrage"])
    parser.add_argument("symbol", nargs="?", default=None)
    parser.add_argument("--quant-data", dest="quant_data", default=None,
                        help="JSON string: {confidence, action, volume_ratio}")
    args = parser.parse_args()

    ta_status = "ON (slow ~3min/asset)" if ENABLE_TA else "OFF (set ENABLE_TRADING_AGENTS=true to enable)"

    if args.command == "signal":
        if not args.symbol:
            print("Usage: research_agent.py signal BTCUSDT [--quant-data '{}']")
            sys.exit(1)
        print(f"  TradingAgents: {ta_status}", file=sys.stderr)
        quant  = json.loads(args.quant_data) if args.quant_data else None
        result = research_signal(args.symbol.upper(), quant)
        # Print JSON for multi_trader.js to parse (stdout only)
        print(json.dumps(result))

    elif args.command == "scan":
        print(f"\n[Research] Full scan of {len(CRYPTO_SYMBOLS)} crypto + {len(STOCK_SYMBOLS_ENV)} stock assets ({len(SYMBOLS)} total)...")
        print(f"  TradingAgents: {ta_status}")
        results = research_scan()
        write_research_state(results)
        send_research_telegram(results)
        print(f"\nTop opportunities:")
        for r in results[:5]:
            act    = "*** ACTIONABLE ***" if r["is_actionable"] else ""
            ta_str = f"  ta={r['ta_score']:+.2f}({r.get('ta_decision','?')})" if r.get("ta_score") is not None else ""
            print(f"  {r['symbol']:<12} score={r['opportunity_score']:.3f}  "
                  f"news={r['news_score']:+.2f}  arb={r['arbitrage_net_pct']:.3f}%{ta_str}  {act}")

    elif args.command == "arbitrage":
        print(f"\n[Research] Arbitrage-only scan...")
        results = scan_arbitrage(SYMBOLS)
        alerts  = [r for r in results if r.get("is_actionable")]
        print(f"\nActionable spreads (>{0.30}% net): {len(alerts)}")
        for r in results:
            flag = "*** ARB ***" if r.get("is_actionable") else ("ok" if r.get("is_profitable") else "")
            print(f"  {r['symbol']:<12} spread={r.get('spread_pct',0):.3f}%  "
                  f"net={r.get('net_spread',0):.3f}%  "
                  f"{r.get('buy_exchange','?')}->{r.get('sell_exchange','?')}  {flag}")

if __name__ == "__main__":
    main()
