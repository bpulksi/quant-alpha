"""
Stock Price Fetcher — Alpaca SDK (alpaca-py)
=============================================
Fetches latest quotes for stock symbols via the official alpaca-py SDK.
Used by multi_trader.js (called via subprocess) and research_agent.py.

Upgrade from urllib raw calls → alpaca-py TradingClient + StockHistoricalDataClient:
  - Proper error types, automatic retry, typed responses
  - Clock endpoint via TradingClient (same API key)
  - Batch stock quotes via StockLatestTradeRequest

Usage:
  python stock_price_fetcher.py AAPL
  python stock_price_fetcher.py AAPL MSFT NVDA
  python stock_price_fetcher.py --is-market-open
"""

import os, sys, json
from datetime import datetime, timezone
from dotenv import load_dotenv
load_dotenv()

ALPACA_API_KEY    = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
PAPER_TRADING     = os.getenv("PAPER_TRADING", "true").lower() != "false"

# ── SDK client factory ────────────────────────────────────────────────────────

def _trading_client():
    from alpaca.trading.client import TradingClient
    return TradingClient(
        api_key    = ALPACA_API_KEY,
        secret_key = ALPACA_SECRET_KEY,
        paper      = PAPER_TRADING,
    )

def _stock_data_client():
    from alpaca.data.historical import StockHistoricalDataClient
    return StockHistoricalDataClient(
        api_key    = ALPACA_API_KEY or None,
        secret_key = ALPACA_SECRET_KEY or None,
    )

# ── Price fetching ────────────────────────────────────────────────────────────

def get_stock_price(symbol: str) -> dict:
    """
    Fetch latest trade price for a stock symbol via alpaca-py SDK.
    Returns {symbol, price, timestamp, source} or raises.
    """
    prices = get_stock_prices([symbol])
    if symbol.upper() not in prices:
        raise RuntimeError(f"No price returned for {symbol}")
    return {
        "symbol":    symbol.upper(),
        "price":     prices[symbol.upper()],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source":    "alpaca_sdk",
    }

def get_stock_prices(symbols: list) -> dict:
    """
    Fetch latest trade prices for multiple symbols in one SDK call.
    Returns {AAPL: 182.5, MSFT: 420.1, ...}
    Falls back to urllib if SDK fails (e.g. no API keys configured).
    """
    if not symbols:
        return {}

    syms_upper = [s.upper() for s in symbols]

    # ── SDK path (preferred) ──────────────────────────────────────────────
    if ALPACA_API_KEY and ALPACA_SECRET_KEY:
        try:
            from alpaca.data.requests import StockLatestTradeRequest
            client  = _stock_data_client()
            request = StockLatestTradeRequest(symbol_or_symbols=syms_upper)
            trades  = client.get_stock_latest_trade(request)
            return {sym: float(trade.price) for sym, trade in trades.items()}
        except Exception as e:
            print(f"  [StockPrice] alpaca-py error, falling back to urllib: {e}")

    # ── urllib fallback (no API keys / SDK error) ─────────────────────────
    import urllib.request, urllib.error
    headers   = {
        "APCA-API-KEY-ID":     ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
        "User-Agent":          "QuantAlpha/2.0",
    }
    syms_str = ",".join(syms_upper)
    url = f"https://data.alpaca.markets/v2/stocks/trades/latest?symbols={syms_str}"
    req = urllib.request.Request(url, headers=headers)
    try:
        resp   = urllib.request.urlopen(req, timeout=10)
        data   = json.loads(resp.read())
        trades = data.get("trades", {})
        return {sym: float(trades[sym]["p"]) for sym in trades if "p" in trades[sym]}
    except Exception as e:
        print(f"  [StockPrice] urllib fallback error: {e}")
        return {}

# ── Market clock ──────────────────────────────────────────────────────────────

def is_market_open() -> bool:
    status = get_market_status()
    return bool(status.get("is_open", False))

def get_market_status() -> dict:
    """
    Return full NYSE clock via alpaca-py TradingClient.
    Falls back to UTC time estimate if no API keys.
    """
    # ── SDK path ──────────────────────────────────────────────────────────
    if ALPACA_API_KEY and ALPACA_SECRET_KEY:
        try:
            clock = _trading_client().get_clock()
            return {
                "is_open":    clock.is_open,
                "next_open":  clock.next_open.isoformat() if clock.next_open else "",
                "next_close": clock.next_close.isoformat() if clock.next_close else "",
                "timestamp":  clock.timestamp.isoformat() if clock.timestamp else "",
                "source":     "alpaca_sdk",
            }
        except Exception as e:
            print(f"  [MarketClock] alpaca-py error: {e}")

    # ── UTC time estimate fallback ────────────────────────────────────────
    utc_now  = datetime.now(timezone.utc)
    et_hour  = (utc_now.hour - 5) % 24          # rough ET (ignores DST)
    weekday  = utc_now.weekday()                 # 0=Mon, 4=Fri
    is_open  = weekday < 5 and 9 <= et_hour < 16
    return {"is_open": is_open, "source": "time_estimate"}


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    args = sys.argv[1:]

    if "--is-market-open" in args:
        status = get_market_status()
        print(json.dumps(status))
        sys.exit(0)

    if not args:
        args = ["AAPL", "MSFT", "NVDA"]

    if len(args) == 1:
        try:
            result = get_stock_price(args[0].upper())
            print(json.dumps(result, indent=2))
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        prices = get_stock_prices([s.upper() for s in args])
        for sym, price in sorted(prices.items()):
            print(f"  {sym:<8} ${price:>10.2f}")
