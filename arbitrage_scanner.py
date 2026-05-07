"""
Arbitrage Scanner — Bybit vs Kraken vs Coinbase
================================================
Detects price discrepancies across exchanges.
All APIs are public (no auth required), no geo-block from Germany.

Standalone test:
  python arbitrage_scanner.py BTC ETH SOL
"""

import json, sys, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

# Taker fee assumptions
FEES = {"bybit": 0.10, "kraken": 0.26, "coinbase": 0.20}  # percent

# Symbol translations per exchange
KRAKEN_MAP = {
    "BTC": "XBTUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT",
    "XRP": "XRPUSDT", "ADA": "ADAUSDT", "DOGE": "DOGEUSDT",
    "LTC": "LTCUSDT", "DOT": "DOTUSDT", "LINK": "LINKUSDT",
    "AVAX": "AVAXUSDT", "BNB": None, "SUI": None,  # not on Kraken
}

COINBASE_MAP = {
    "BTC": "BTC-USD", "ETH": "ETH-USD", "SOL": "SOL-USD",
    "XRP": "XRP-USD", "ADA": "ADA-USD", "DOGE": "DOGE-USD",
    "LTC": "LTC-USD", "DOT": "DOT-USD", "LINK": "LINK-USD",
    "AVAX": "AVAX-USD", "BNB": "BNB-USD", "SUI": "SUI-USD",
}

SYMBOL_MAP = {
    "BTCUSDT": "BTC", "ETHUSDT": "ETH", "SOLUSDT": "SOL",
    "XRPUSDT": "XRP", "AVAXUSDT": "AVAX", "ADAUSDT": "ADA",
    "DOTUSDT": "DOT", "LINKUSDT": "LINK", "LTCUSDT": "LTC",
    "DOGEUSDT": "DOGE", "BNBUSDT": "BNB", "SUIUSDT": "SUI",
}

def _to_ticker(symbol: str) -> str:
    return SYMBOL_MAP.get(symbol.upper(), symbol.upper().replace("USDT", ""))

def _get(url: str, timeout: int = 8) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "TradingBot/1.0"})
    resp = urllib.request.urlopen(req, timeout=timeout)
    return json.loads(resp.read())

# ─── Per-exchange fetchers ────────────────────────────────────────────────────

def fetch_bybit_price(ticker: str) -> float:
    symbol = ticker.upper() + "USDT"
    url = f"https://api.bybit.com/v5/market/tickers?category=spot&symbol={symbol}"
    data = _get(url)
    lst = data["result"]["list"]
    if lst:
        return float(lst[0]["lastPrice"])
    return None

def fetch_kraken_price(ticker: str) -> float:
    pair = KRAKEN_MAP.get(ticker.upper())
    if not pair:
        return None
    url = f"https://api.kraken.com/0/public/Ticker?pair={pair}"
    data = _get(url)
    if data.get("error"):
        return None
    result = data.get("result", {})
    if not result:
        return None
    key = next(iter(result))
    return float(result[key]["c"][0])

def fetch_coinbase_price(ticker: str) -> float:
    pair = COINBASE_MAP.get(ticker.upper())
    if not pair:
        return None
    url = f"https://api.coinbase.com/v2/prices/{pair}/spot"
    data = _get(url)
    return float(data["data"]["amount"])

# ─── Spread calculator ────────────────────────────────────────────────────────

def calculate_spread(prices: dict) -> dict:
    """
    prices: {"bybit": float, "kraken": float, "coinbase": float} — None = unavailable
    Returns spread analysis dict.
    """
    valid = {ex: p for ex, p in prices.items() if p is not None}
    if len(valid) < 2:
        return {"spread_pct": 0.0, "net_spread": 0.0, "is_profitable": False, "is_actionable": False, "valid": False}

    max_ex  = max(valid, key=valid.get)
    min_ex  = min(valid, key=valid.get)
    max_p   = valid[max_ex]
    min_p   = valid[min_ex]

    spread_pct = (max_p - min_p) / min_p * 100
    fee_buy  = FEES.get(min_ex, 0.20)
    fee_sell = FEES.get(max_ex, 0.20)
    net_spread = spread_pct - fee_buy - fee_sell

    return {
        "spread_pct":    round(spread_pct, 4),
        "net_spread":    round(net_spread, 4),
        "buy_exchange":  min_ex,
        "sell_exchange": max_ex,
        "buy_price":     round(min_p, 6),
        "sell_price":    round(max_p, 6),
        "is_profitable": net_spread > 0.0,
        "is_actionable": net_spread > 0.30,   # > 0.30% net = covers fees
        "valid": True,
    }

# ─── Single-asset scan ────────────────────────────────────────────────────────

def scan_asset(symbol: str) -> dict:
    ticker = _to_ticker(symbol)
    prices = {"bybit": None, "kraken": None, "coinbase": None}

    def _fetch(ex, fn):
        try:
            return ex, fn(ticker)
        except Exception as e:
            return ex, None

    with ThreadPoolExecutor(max_workers=3) as pool:
        futs = [
            pool.submit(_fetch, "bybit",    fetch_bybit_price),
            pool.submit(_fetch, "kraken",   fetch_kraken_price),
            pool.submit(_fetch, "coinbase", fetch_coinbase_price),
        ]
        for f in as_completed(futs):
            ex, price = f.result()
            prices[ex] = price

    spread = calculate_spread(prices)
    spread["symbol"]  = symbol
    spread["ticker"]  = ticker
    spread["prices"]  = {k: round(v, 6) if v else None for k, v in prices.items()}
    return spread

# ─── Multi-asset scan (concurrent) ───────────────────────────────────────────

def scan_arbitrage(symbols: list) -> list:
    results = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futs = {pool.submit(scan_asset, s): s for s in symbols}
        for f in as_completed(futs):
            try:
                results.append(f.result())
            except Exception as e:
                print(f"  [Arb] Error: {e}")
    results.sort(key=lambda x: -x.get("net_spread", -999))
    return results


if __name__ == "__main__":
    tickers = sys.argv[1:] if len(sys.argv) > 1 else ["BTC", "ETH", "SOL"]
    symbols = [t if t.endswith("USDT") else t + "USDT" for t in tickers]
    print(f"\nScanning arbitrage for: {', '.join(symbols)}")
    results = scan_arbitrage(symbols)
    print(f"\n{'Symbol':<12} {'Spread%':>8} {'Net%':>8} {'Buy':>10} {'Sell':>10} {'Actionable'}")
    print("-" * 65)
    for r in results:
        act = "YES ***" if r.get("is_actionable") else ("yes" if r.get("is_profitable") else "no")
        px = r.get("prices", {})
        print(f"{r['symbol']:<12} {r.get('spread_pct',0):>7.3f}% {r.get('net_spread',0):>7.3f}%  "
              f"{r.get('buy_exchange','?'):>10}  {r.get('sell_exchange','?'):>10}  {act}")
