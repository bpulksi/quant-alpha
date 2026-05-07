"""
Macro Intelligence -- Expert Transcript & Macro Signal Layer
=============================================================
Processes expert opinion transcripts, macroeconomic notes, and
thematic signals. Produces per-symbol macro_score adjustments
that blend into the opportunity ranker as a soft overlay.

Macro signals are directional overrides that shift news_score
for affected assets without overriding the full ML pipeline.

Storage: macro_signals.json  (manually curated + auto-updated)
Dashboard: reads macro_signals.json for macro overlay panel

CLI:
  python macro_intelligence.py add           -- interactive add
  python macro_intelligence.py show          -- show active signals
  python macro_intelligence.py score NVDA    -- get macro score for symbol
  python macro_intelligence.py expire        -- remove expired signals
"""

import os, sys
from datetime import datetime, timezone, timedelta
from state_manager import load_json, save_json, state_path

MACRO_FILE = state_path("macro_signals.json")

# Default TTL for macro signals (they decay over time -- macro takes months to play out)
DEFAULT_TTL_DAYS = 30

# Symbols we track
ALL_SYMBOLS = [
    # Crypto — Alpaca-tradeable
    "BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT","AVAXUSDT","ADAUSDT",
    "DOTUSDT","LINKUSDT","LTCUSDT","DOGEUSDT","UNIUSDT","XLMUSDT",
    # Crypto — data-only (research signals, no orders)
    "BNBUSDT","SUIUSDT","ATOMUSDT","TRXUSDT","INJUSDT","RENDERUSDT","TAOUSDT","FILUSDT",
    # Stocks — Tech / AI
    "AAPL","MSFT","NVDA","GOOGL","META","AMZN","TSLA","AMD","PLTR","CRM","ORCL","SNOW",
    # Stocks — Crypto proxies
    "COIN","MSTR","SOFI",
    # Stocks — Financials
    "JPM","V","MA","GS",
    # Stocks — Healthcare
    "LLY","UNH","JNJ","MRNA",
    # Stocks — Energy
    "XOM","CVX",
    # Stocks — Consumer
    "WMT","COST","MCD",
    # ETFs — Broad market + sector
    "SPY","QQQ","IWM","GLD","TLT","XLE","XLF","XLV",
]

# ── Load / Save ───────────────────────────────────────────────────────────

def load_signals() -> dict:
    return load_json("macro_signals.json",
                     default={"signals": [], "last_updated": datetime.now(timezone.utc).isoformat()})

def save_signals(data: dict):
    data["last_updated"] = datetime.now(timezone.utc).isoformat()
    save_json("macro_signals.json", data)

# ── Core scoring ──────────────────────────────────────────────────────────

def get_macro_score(symbol: str, data: dict = None) -> dict:
    """
    Return the blended macro score for one symbol.
    score: -1.0 (strong bearish) to +1.0 (strong bullish)
    Returns {score, signals, summary}
    """
    if data is None:
        data = load_signals()

    now = datetime.now(timezone.utc)
    sym_upper = symbol.upper()
    # Normalise: BTCUSDT -> BTC for matching, plain AAPL -> AAPL
    sym_bare  = sym_upper.replace("USDT", "")

    active    = []
    score_sum = 0.0
    weight_sum = 0.0

    for sig in data.get("signals", []):
        # Check expiry
        expires = sig.get("expires")
        if expires:
            try:
                exp_dt = datetime.fromisoformat(expires)
                if exp_dt.tzinfo is None:
                    exp_dt = exp_dt.replace(tzinfo=timezone.utc)
                if now > exp_dt:
                    continue
            except Exception:
                pass

        # Check if this signal applies to this symbol
        targets = [t.upper() for t in sig.get("targets", [])]
        if sym_upper not in targets and sym_bare not in targets:
            # Check category match
            cats = [c.upper() for c in sig.get("categories", [])]
            sym_cat = _symbol_category(sym_bare)
            if not any(c in cats for c in sym_cat):
                continue

        # Age decay: signals lose 30% weight per week
        added = sig.get("added_at", now.isoformat())
        try:
            added_dt = datetime.fromisoformat(added)
            if added_dt.tzinfo is None:
                added_dt = added_dt.replace(tzinfo=timezone.utc)
            age_days = (now - added_dt).total_seconds() / 86400
        except Exception:
            age_days = 0
        decay = max(0.1, 1.0 - (age_days / DEFAULT_TTL_DAYS) * 0.7)

        weight  = sig.get("weight", 1.0) * decay
        direction = float(sig.get("direction", 0.0))

        score_sum  += direction * weight
        weight_sum += weight
        active.append({
            "title":     sig.get("title", ""),
            "direction": direction,
            "weight":    round(weight, 3),
            "age_days":  round(age_days, 1),
            "source":    sig.get("source", ""),
        })

    final_score = round(score_sum / weight_sum, 4) if weight_sum > 0 else 0.0
    final_score = max(-1.0, min(1.0, final_score))

    return {
        "symbol":         symbol,
        "macro_score":    final_score,
        "signal_count":   len(active),
        "active_signals": active,
        "summary":        _score_label(final_score),
    }

def _symbol_category(sym: str) -> list:
    """Map symbol to broad categories for theme-based signal matching."""
    cats = []
    ai_stocks    = {"NVDA","MSFT","GOOGL","META","AMZN","PLTR","AMD","CRM","ORCL","SNOW"}
    crypto_syms  = {"BTC","ETH","SOL","XRP","AVAX","ADA","DOT","LINK","LTC","DOGE",
                    "BNB","SUI","UNI","XLM","ATOM","TRX","INJ","RENDER","TAO","FIL"}
    index_etfs   = {"SPY","QQQ","IWM"}
    sector_etfs  = {"GLD","TLT","XLE","XLF","XLV"}
    crypto_proxy = {"COIN","MSTR"}
    financials   = {"JPM","V","MA","GS","SOFI"}
    healthcare   = {"LLY","UNH","JNJ","MRNA"}
    energy       = {"XOM","CVX"}
    consumer     = {"WMT","COST","MCD","TSLA","AAPL"}
    defi_coins   = {"UNI","AAVE","LINK","ATOM","INJ"}
    ai_crypto    = {"RENDER","TAO","FIL","INJ"}

    if sym in ai_stocks:
        cats.extend(["AI_STOCKS","TECH_STOCKS","US_MARKET"])
    if sym in crypto_syms:
        cats.extend(["CRYPTO","ALTCOINS"])
    if sym == "BTC":
        cats.append("BITCOIN")
    if sym in {"ETH","UNI","LINK","ATOM","INJ"}:
        cats.append("DEFI")
    if sym in ai_crypto:
        cats.extend(["AI_CRYPTO","CRYPTO"])
    if sym in index_etfs:
        cats.extend(["ETF","US_MARKET","INDEX"])
    if sym in sector_etfs:
        cats.extend(["ETF","US_MARKET"])
        if sym == "GLD": cats.append("COMMODITIES")
        if sym == "TLT": cats.append("BONDS")
        if sym == "XLE": cats.append("ENERGY")
        if sym == "XLF": cats.append("FINANCIALS")
        if sym == "XLV": cats.append("HEALTHCARE")
    if sym in crypto_proxy:
        cats.extend(["CRYPTO_PROXY","US_MARKET"])
    if sym in financials:
        cats.extend(["FINANCIALS","US_MARKET"])
    if sym in healthcare:
        cats.extend(["HEALTHCARE","US_MARKET"])
    if sym in energy:
        cats.extend(["ENERGY","US_MARKET"])
    if sym in consumer:
        cats.extend(["CONSUMER","US_MARKET"])
    return cats

def _score_label(score: float) -> str:
    if score >= 0.6:  return "STRONG BULLISH"
    if score >= 0.3:  return "BULLISH"
    if score >= 0.1:  return "MILD BULLISH"
    if score >= -0.1: return "NEUTRAL"
    if score >= -0.3: return "MILD BEARISH"
    if score >= -0.6: return "BEARISH"
    return "STRONG BEARISH"

# ── Add signal ────────────────────────────────────────────────────────────

def add_signal(
    title:      str,
    direction:  float,        # -1.0 to +1.0
    targets:    list = None,  # specific symbols e.g. ["NVDA","AMD"]
    categories: list = None,  # broad e.g. ["AI_STOCKS","CRYPTO"]
    source:     str  = "",
    weight:     float = 1.0,
    ttl_days:   int   = DEFAULT_TTL_DAYS,
    notes:      str   = "",
):
    data = load_signals()
    now  = datetime.now(timezone.utc)
    sig  = {
        "title":      title,
        "direction":  round(direction, 3),
        "targets":    [t.upper() for t in (targets or [])],
        "categories": [c.upper() for c in (categories or [])],
        "source":     source,
        "weight":     weight,
        "notes":      notes,
        "added_at":   now.isoformat(),
        "expires":    (now + timedelta(days=ttl_days)).isoformat(),
    }
    data["signals"].append(sig)
    save_signals(data)
    print(f"  [OK] Signal added: '{title}' direction={direction:+.2f} ttl={ttl_days}d")
    return sig

# ── Expire stale signals ──────────────────────────────────────────────────

def expire_stale(data: dict = None) -> int:
    if data is None:
        data = load_signals()
    now = datetime.now(timezone.utc)
    before = len(data["signals"])
    live = []
    for sig in data["signals"]:
        exp = sig.get("expires")
        if not exp:
            live.append(sig); continue
        try:
            exp_dt = datetime.fromisoformat(exp)
            if exp_dt.tzinfo is None:
                exp_dt = exp_dt.replace(tzinfo=timezone.utc)
            if now <= exp_dt:
                live.append(sig)
        except Exception:
            live.append(sig)
    data["signals"] = live
    save_signals(data)
    return before - len(live)

# ── Blend into research score ─────────────────────────────────────────────

def blend_macro_into_news(news_score: float, symbol: str, weight: float = 0.30) -> float:
    """
    Blend macro_score into news_score.
    weight=0.30 means macro is 30% of the blended score.
    Returns adjusted news_score in [-1, +1].
    """
    result = get_macro_score(symbol)
    macro  = result["macro_score"]
    if macro == 0.0:
        return news_score   # no macro signal -- no change
    blended = news_score * (1 - weight) + macro * weight
    return round(max(-1.0, min(1.0, blended)), 4)

# ── Bulk score for dashboard ──────────────────────────────────────────────

def score_all(symbols: list = None) -> list:
    """Return macro scores for all symbols."""
    data = load_signals()
    syms = symbols or ALL_SYMBOLS
    return [get_macro_score(sym, data) for sym in syms]

# ── Write macro_state.json for dashboard ──────────────────────────────────

def write_macro_state():
    data   = load_signals()
    scores = score_all()
    state  = {
        "last_updated":  datetime.now(timezone.utc).isoformat(),
        "signal_count":  len(data["signals"]),
        "scores":        scores,
        "active_themes": _extract_themes(data),
    }
    save_json("macro_state.json", state)
    print(f"  [OK] macro_state.json written ({len(scores)} symbols)")

def _extract_themes(data: dict) -> list:
    """Extract unique active signal titles as theme list."""
    now = datetime.now(timezone.utc)
    themes = []
    for sig in data["signals"]:
        exp = sig.get("expires")
        if exp:
            try:
                exp_dt = datetime.fromisoformat(exp)
                if exp_dt.tzinfo is None:
                    exp_dt = exp_dt.replace(tzinfo=timezone.utc)
                if now > exp_dt:
                    continue
            except Exception:
                pass
        themes.append({
            "title":     sig["title"],
            "direction": sig["direction"],
            "source":    sig.get("source", ""),
            "categories":sig.get("categories", []),
        })
    return themes

# ── CLI ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    cmd  = sys.argv[1] if len(sys.argv) > 1 else "show"
    arg2 = sys.argv[2] if len(sys.argv) > 2 else ""

    if cmd == "show":
        data = load_signals()
        print(f"\nMacro Intelligence -- {len(data['signals'])} signals loaded")
        print("=" * 65)
        scores = score_all()
        for s in sorted(scores, key=lambda x: x["macro_score"]):
            bar_len = int(abs(s["macro_score"]) * 20)
            bar_dir = ">" if s["macro_score"] >= 0 else "<"
            bar = bar_dir * bar_len
            col = "+" if s["macro_score"] >= 0 else ""
            sym = s["symbol"].replace("USDT","")
            print(f"  {sym:<8}  {col}{s['macro_score']:>+.3f}  {bar:<20}  {s['summary']:<18}  ({s['signal_count']} signals)")
        print()

    elif cmd == "score":
        if not arg2:
            print("Usage: macro_intelligence.py score SYMBOL")
            sys.exit(1)
        result = get_macro_score(arg2.upper())
        print(f"\nMacro score for {result['symbol']}: {result['macro_score']:+.3f}  ({result['summary']})")
        for s in result["active_signals"]:
            print(f"  [{s['direction']:+.2f} w={s['weight']:.2f}] {s['title'][:60]}  [{s['source']}]")

    elif cmd == "expire":
        removed = expire_stale()
        print(f"  Expired {removed} stale signals.")

    elif cmd == "state":
        write_macro_state()

    else:
        print("Usage: macro_intelligence.py [show|score SYMBOL|expire|state]")
