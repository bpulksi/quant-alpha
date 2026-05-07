"""
Stock Price Fetcher -- Alpaca Market Data API
=============================================
Fetches latest quotes for stock symbols via Alpaca's market data API.
Used by multi_trader.js (called via subprocess) and research_agent.py.

Alpaca market data is free for delayed quotes (15 min) without subscription.
Real-time quotes available with Alpaca Unlimited Data Plan.

Usage:
  python stock_price_fetcher.py AAPL
  python stock_price_fetcher.py AAPL MSFT NVDA
  python stock_price_fetcher.py --is-market-open
"""

import os, sys, json, urllib.request
from datetime import datetime, timezone
from dotenv import load_dotenv
load_dotenv()

ALPACA_API_KEY    = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
PAPER_TRADING     = os.getenv("PAPER_TRADING", "true").lower() != "false"

# Alpaca market data base URL (same for paper and live)
DATA_BASE_URL = "https://data.alpaca.markets"

def _alpaca_headers() -> dict:
    return {
        "APCA-API-KEY-ID":     ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
        "User-Agent":          "TradingBot/1.0",
    }

def get_stock_price(symbol: str) -> dict:
    """
    Fetch latest trade price for a stock symbol.
    Returns {symbol, price, timestamp, source} or raises.
    """
    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
        raise RuntimeError("Alpaca API keys not set in .env")

    url = f"{DATA_BASE_URL}/v2/stocks/{symbol}/trades/latest"
    req = urllib.request.Request(url, headers=_alpaca_headers())
    try:
        resp = urllib.request.urlopen(req, timeout=8)
        data = json.loads(resp.read())
        trade = data.get("trade", {})
        price = float(trade.get("p", 0))
        ts    = trade.get("t", datetime.now(timezone.utc).isoformat())
        return {"symbol": symbol, "price": price, "timestamp": ts, "source": "alpaca_trade"}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        raise RuntimeError(f"Alpaca {e.code} for {symbol}: {body[:200]}")

def get_stock_prices(symbols: list) -> dict:
    """
    Fetch latest prices for multiple symbols in one batch request.
    Returns {AAPL: 182.5, MSFT: 420.1, ...}
    """
    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
        return {}

    syms_str = ",".join(symbols)
    url = f"{DATA_BASE_URL}/v2/stocks/trades/latest?symbols={syms_str}"
    req = urllib.request.Request(url, headers=_alpaca_headers())
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())
        trades = data.get("trades", {})
        return {sym: float(trades[sym]["p"]) for sym in trades if "p" in trades[sym]}
    except Exception as e:
        print(f"  [StockPrice] Batch fetch error: {e}")
        return {}

def is_market_open() -> bool:
    """
    Check if NYSE is currently open via Alpaca clock endpoint.
    Returns True if market is open right now.
    """
    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
        # Fallback: check by time (NYSE: Mon-Fri 09:30-16:00 ET)
        from datetime import datetime
        import time
        # Get ET offset (EST=-5, EDT=-4)
        utc_now = datetime.now(timezone.utc)
        # Simple check: UTC-5 (ignore DST for safety -- use slightly wider window)
        et_hour = (utc_now.hour - 5) % 24
        weekday = utc_now.weekday()  # 0=Mon, 4=Fri
        return weekday < 5 and 9 <= et_hour < 16

    base = "https://paper-api.alpaca.markets" if PAPER_TRADING else "https://api.alpaca.markets"
    url  = f"{base}/v2/clock"
    req  = urllib.request.Request(url, headers=_alpaca_headers())
    try:
        resp = urllib.request.urlopen(req, timeout=5)
        data = json.loads(resp.read())
        return bool(data.get("is_open", False))
    except Exception:
        return False

def get_market_status() -> dict:
    """Return full market clock info."""
    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
        return {"is_open": is_market_open(), "source": "time_estimate"}

    base = "https://paper-api.alpaca.markets" if PAPER_TRADING else "https://api.alpaca.markets"
    url  = f"{base}/v2/clock"
    req  = urllib.request.Request(url, headers=_alpaca_headers())
    try:
        resp = urllib.request.urlopen(req, timeout=5)
        data = json.loads(resp.read())
        return {
            "is_open":    data.get("is_open", False),
            "next_open":  data.get("next_open", ""),
            "next_close": data.get("next_close", ""),
            "timestamp":  data.get("timestamp", ""),
            "source":     "alpaca_clock",
        }
    except Exception as e:
        return {"is_open": is_market_open(), "source": "time_estimate", "error": str(e)}


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
            print(f"Error: {e}")
    else:
        prices = get_stock_prices([s.upper() for s in args])
        for sym, price in sorted(prices.items()):
            print(f"  {sym:<8} ${price:>10.2f}")
