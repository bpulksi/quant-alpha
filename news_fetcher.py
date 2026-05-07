"""
News Fetcher -- CryptoPanic + Reddit + RSS + Yahoo Finance
==========================================================
Fetches recent news headlines for crypto AND stock assets.
Falls back gracefully if API keys are missing.

Standalone test:
  python news_fetcher.py BTC
  python news_fetcher.py AAPL 6
  python news_fetcher.py NVDA 24
"""

import os, sys, json, time, urllib.request, urllib.parse
from datetime import datetime, timezone
from dotenv import load_dotenv
load_dotenv()

CRYPTOPANIC_TOKEN    = os.getenv("CRYPTOPANIC_TOKEN", "")   # free tier available
REDDIT_CLIENT_ID     = os.getenv("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET", "")

# Map internal USDT symbols to tickers
SYMBOL_MAP = {
    "BTCUSDT": "BTC",  "ETHUSDT": "ETH",  "SOLUSDT": "SOL",
    "XRPUSDT": "XRP",  "AVAXUSDT": "AVAX","ADAUSDT": "ADA",
    "DOTUSDT": "DOT",  "LINKUSDT": "LINK","LTCUSDT": "LTC",
    "DOGEUSDT": "DOGE","BNBUSDT": "BNB",  "SUIUSDT": "SUI",
}

# Stock symbols -- plain tickers (no USDT suffix)
STOCK_SYMBOLS = {
    # Tech / AI
    "AAPL","MSFT","NVDA","GOOGL","META","AMZN","TSLA","AMD","PLTR","CRM","ORCL","SNOW",
    # Crypto proxies
    "COIN","MSTR","SOFI",
    # Financials
    "JPM","V","MA","GS",
    # Healthcare
    "LLY","UNH","JNJ","MRNA",
    # Energy
    "XOM","CVX",
    # Consumer
    "WMT","COST","MCD",
    # ETFs
    "SPY","QQQ","IWM","GLD","TLT","XLE","XLF","XLV",
}

# Full name keywords for broader RSS matching
TICKER_KEYWORDS = {
    # ── Crypto ────────────────────────────────────────────────────────────
    "BTC":    ["BTC", "BITCOIN"],
    "ETH":    ["ETH", "ETHEREUM", "ETHER"],
    "SOL":    ["SOL", "SOLANA"],
    "XRP":    ["XRP", "RIPPLE"],
    "AVAX":   ["AVAX", "AVALANCHE"],
    "ADA":    ["ADA", "CARDANO"],
    "DOT":    ["DOT", "POLKADOT"],
    "LINK":   ["LINK", "CHAINLINK"],
    "LTC":    ["LTC", "LITECOIN"],
    "DOGE":   ["DOGE", "DOGECOIN"],
    "BNB":    ["BNB", "BINANCE"],
    "SUI":    ["SUI"],
    "UNI":    ["UNI", "UNISWAP"],
    "XLM":    ["XLM", "STELLAR"],
    "ATOM":   ["ATOM", "COSMOS"],
    "TRX":    ["TRX", "TRON"],
    "INJ":    ["INJ", "INJECTIVE"],
    "RENDER": ["RENDER", "RNDR"],
    "TAO":    ["TAO", "BITTENSOR"],
    "FIL":    ["FIL", "FILECOIN"],
    # ── Tech / AI Stocks ──────────────────────────────────────────────────
    "AAPL":  ["AAPL", "APPLE"],
    "MSFT":  ["MSFT", "MICROSOFT"],
    "NVDA":  ["NVDA", "NVIDIA"],
    "GOOGL": ["GOOGL", "GOOGLE", "ALPHABET"],
    "META":  ["META", "FACEBOOK", "INSTAGRAM"],
    "AMZN":  ["AMZN", "AMAZON", "AWS"],
    "TSLA":  ["TSLA", "TESLA"],
    "AMD":   ["AMD", "ADVANCED MICRO"],
    "PLTR":  ["PLTR", "PALANTIR"],
    "CRM":   ["CRM", "SALESFORCE"],
    "ORCL":  ["ORCL", "ORACLE"],
    "SNOW":  ["SNOW", "SNOWFLAKE"],
    # ── Crypto proxies ────────────────────────────────────────────────────
    "COIN":  ["COIN", "COINBASE"],
    "MSTR":  ["MSTR", "MICROSTRATEGY"],
    "SOFI":  ["SOFI"],
    # ── Financials ────────────────────────────────────────────────────────
    "JPM":   ["JPM", "JPMORGAN", "CHASE"],
    "V":     ["VISA"],
    "MA":    ["MA", "MASTERCARD"],
    "GS":    ["GS", "GOLDMAN SACHS", "GOLDMAN"],
    # ── Healthcare ────────────────────────────────────────────────────────
    "LLY":   ["LLY", "ELI LILLY", "MOUNJARO", "GLP-1"],
    "UNH":   ["UNH", "UNITEDHEALTH", "UNITED HEALTH"],
    "JNJ":   ["JNJ", "JOHNSON"],
    "MRNA":  ["MRNA", "MODERNA"],
    # ── Energy ────────────────────────────────────────────────────────────
    "XOM":   ["XOM", "EXXON", "EXXONMOBIL"],
    "CVX":   ["CVX", "CHEVRON"],
    # ── Consumer ──────────────────────────────────────────────────────────
    "WMT":   ["WMT", "WALMART"],
    "COST":  ["COST", "COSTCO"],
    "MCD":   ["MCD", "MCDONALD"],
    # ── ETFs ──────────────────────────────────────────────────────────────
    "SPY":   ["SPY", "S&P 500", "S&P500"],
    "QQQ":   ["QQQ", "NASDAQ", "NDX"],
    "IWM":   ["IWM", "RUSSELL 2000"],
    "GLD":   ["GLD", "GOLD", "GOLD ETF"],
    "TLT":   ["TLT", "TREASURY", "BOND", "10-YEAR"],
    "XLE":   ["XLE", "ENERGY ETF", "OIL"],
    "XLF":   ["XLF", "FINANCIALS ETF", "BANKS"],
    "XLV":   ["XLV", "HEALTHCARE ETF"],
}

def is_stock(symbol: str) -> bool:
    """Return True if this is a stock symbol (not crypto)."""
    upper = symbol.upper().replace("USDT", "")
    return upper in STOCK_SYMBOLS

def _to_ticker(symbol: str) -> str:
    """Convert internal symbol to clean ticker. BTCUSDT->BTC, AAPL->AAPL."""
    upper = symbol.upper()
    if upper in SYMBOL_MAP:
        return SYMBOL_MAP[upper]
    return upper.replace("USDT", "")

def _matches_ticker(text: str, ticker: str) -> bool:
    """Check if text mentions this ticker by symbol or full name."""
    upper = text.upper()
    keywords = TICKER_KEYWORDS.get(ticker.upper(), [ticker.upper()])
    return any(kw in upper for kw in keywords)

def _age_hours(ts_str: str) -> float:
    """Return hours since a UTC ISO or RFC 2822 timestamp string."""
    if not ts_str:
        return 12.0
    try:
        s = ts_str.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 3600
    except Exception:
        pass
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(ts_str)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 3600
    except Exception:
        return 12.0

def _recency_weight(age_h: float) -> float:
    if age_h <= 1:   return 1.0
    if age_h <= 24:  return 0.5
    if age_h <= 168: return 0.1
    return 0.05

# ---- CryptoPanic (crypto only) -----------------------------------------------

def fetch_cryptopanic(ticker: str, limit: int = 20) -> list:
    if not CRYPTOPANIC_TOKEN:
        return []
    url = (
        f"https://cryptopanic.com/api/v1/posts/"
        f"?auth_token={CRYPTOPANIC_TOKEN}"
        f"&currencies={ticker}&public=true&limit={limit}"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "TradingBot/1.0"})
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())
        results = []
        for post in data.get("results", []):
            age = _age_hours(post.get("published_at", ""))
            results.append({
                "title":    post.get("title", ""),
                "body":     "",
                "source":   post.get("source", {}).get("title", "CryptoPanic"),
                "published_ts": post.get("published_at", ""),
                "age_hours":    round(age, 2),
                "recency_weight": _recency_weight(age),
            })
        return results
    except Exception as e:
        print(f"  [CryptoPanic] Error for {ticker}: {e}")
        return []

# ---- Reddit (PRAW) -----------------------------------------------------------

def fetch_reddit(ticker: str, limit: int = 10) -> list:
    if not REDDIT_CLIENT_ID or not REDDIT_CLIENT_SECRET:
        return []
    try:
        import praw
        # Pick subreddits based on crypto vs stock
        if ticker in STOCK_SYMBOLS:
            subs = "stocks+investing+wallstreetbets+stockmarket"
        else:
            subs = "CryptoCurrency+Bitcoin+ethereum+solana"
        reddit = praw.Reddit(
            client_id=REDDIT_CLIENT_ID,
            client_secret=REDDIT_CLIENT_SECRET,
            user_agent="TradingBot/1.0 by ResearchAgent",
        )
        results = []
        for submission in reddit.subreddit(subs).search(ticker, sort="new", time_filter="day", limit=limit):
            age = (time.time() - submission.created_utc) / 3600
            results.append({
                "title":    submission.title,
                "body":     (submission.selftext or "")[:300],
                "source":   f"r/{submission.subreddit.display_name}",
                "published_ts": datetime.fromtimestamp(submission.created_utc, tz=timezone.utc).isoformat(),
                "age_hours":    round(age, 2),
                "recency_weight": _recency_weight(age),
            })
        return results
    except Exception as e:
        print(f"  [Reddit] Error for {ticker}: {e}")
        return []

# ---- CoinGecko Trending (crypto only) ----------------------------------------

def fetch_coingecko_trending(ticker: str) -> list:
    if ticker in STOCK_SYMBOLS:
        return []
    url = "https://api.coingecko.com/api/v3/search/trending"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "TradingBot/1.0"})
        data = json.loads(urllib.request.urlopen(req, timeout=8).read())
        trending_names   = [c["item"]["name"].upper()   for c in data.get("coins", [])]
        trending_symbols = [c["item"]["symbol"].upper() for c in data.get("coins", [])]
        keywords = TICKER_KEYWORDS.get(ticker.upper(), [ticker.upper()])
        is_trending = any(
            kw in trending_names or kw in trending_symbols for kw in keywords
        )
        if is_trending:
            return [{
                "title":    f"{ticker} is currently trending on CoinGecko -- high search interest",
                "body":     "",
                "source":   "CoinGecko Trending",
                "published_ts": datetime.now(timezone.utc).isoformat(),
                "age_hours":    0.0,
                "recency_weight": 1.0,
            }]
    except Exception as e:
        print(f"  [CoinGecko Trending] Error for {ticker}: {e}")
    return []

# ---- Multi-RSS Feed ----------------------------------------------------------

CRYPTO_RSS_URLS = [
    "https://cointelegraph.com/rss",
    "https://bitcoinmagazine.com/.rss/full/",
    "https://decrypt.co/feed",
    "https://cryptobriefing.com/feed/",
]

STOCK_RSS_URLS = [
    "https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US",
    "https://feeds.marketwatch.com/marketwatch/realtimeheadlines/",
    "https://seekingalpha.com/api/sa/combined/{ticker}.xml",
]

def fetch_rss(ticker: str) -> list:
    results = []
    try:
        import feedparser
        if ticker in STOCK_SYMBOLS:
            # Stock RSS: Yahoo Finance per-ticker + general MarketWatch
            urls = [
                f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US",
                "https://feeds.marketwatch.com/marketwatch/realtimeheadlines/",
            ]
        else:
            urls = CRYPTO_RSS_URLS

        for url in urls:
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:40]:
                    title = entry.get("title", "")
                    # For per-ticker Yahoo feeds every entry is relevant; for general feeds filter
                    if "yahoo" not in url and "finance.yahoo" not in url:
                        if not _matches_ticker(title, ticker):
                            continue
                    published = entry.get("published", "") or entry.get("updated", "")
                    age = _age_hours(published) if published else 48.0
                    if age > 168:
                        continue
                    results.append({
                        "title":    title,
                        "body":     entry.get("summary", "")[:300],
                        "source":   feed.feed.get("title", url),
                        "published_ts": published,
                        "age_hours":    round(age, 2),
                        "recency_weight": _recency_weight(age),
                    })
            except Exception:
                continue
    except Exception as e:
        print(f"  [RSS] Error for {ticker}: {e}")
    return results

# ---- Aggregator --------------------------------------------------------------

def fetch_all_news(symbol: str, lookback_hours: int = 24) -> list:
    """Fetch from all sources, deduplicate by title, recency-filter."""
    ticker = _to_ticker(symbol)
    stock  = is_stock(symbol)

    cp  = fetch_cryptopanic(ticker) if (CRYPTOPANIC_TOKEN and not stock) else []
    cg  = fetch_coingecko_trending(ticker) if not stock else []
    rd  = fetch_reddit(ticker)
    rss = fetch_rss(ticker)

    all_news = cp + cg + rd + rss

    # Deduplicate by title prefix (first 40 chars)
    seen   = set()
    unique = []
    for item in all_news:
        key = item["title"][:40].lower().strip()
        if key and key not in seen:
            seen.add(key)
            unique.append(item)

    fresh = [n for n in unique if n["age_hours"] <= lookback_hours]
    fresh.sort(key=lambda x: (-x["recency_weight"], x["age_hours"]))
    return fresh


if __name__ == "__main__":
    sym = sys.argv[1] if len(sys.argv) > 1 else "BTC"
    hours = int(sys.argv[2]) if len(sys.argv) > 2 else 24
    asset_type = "STOCK" if is_stock(sym) else "CRYPTO"
    print(f"\nFetching {asset_type} news for {sym} (last {hours}h)...")
    news = fetch_all_news(sym, hours)
    print(f"Found {len(news)} unique items\n")
    for n in news[:10]:
        print(f"  [{n['age_hours']:.1f}h] [{n['source']}] {n['title'][:80]}")
