"""
Portfolio Tracker — 90-Day Paper Trading Challenge
====================================================
Tracks a virtual $1000 portfolio across all paper trades.
Learns from wins/losses to adjust confidence thresholds over time.
Run: python portfolio_tracker.py report    → full P&L report
Run: python portfolio_tracker.py learn     → update adaptive thresholds
"""

import os, sys
from datetime import datetime
from collections import defaultdict
from state_manager import load_json, save_json, state_path

TRACKER_FILE = state_path("portfolio_state.json")
LOG_FILE     = state_path("multi-trade-log.json")
CHALLENGE_START = "2026-05-07"
CHALLENGE_DAYS  = 90
STARTING_CAPITAL = 100000.0   # EUR equivalent — 100k paper trading fund

# ─── State ────────────────────────────────────────────────────────────────

def load_state():
    default = {
        "start_date": CHALLENGE_START,
        "starting_capital": STARTING_CAPITAL,
        "virtual_capital": STARTING_CAPITAL,
        "open_positions": {},
        "closed_trades": [],
        "daily_pnl": {},
        "adaptive": {
            "min_confidence": 0.50,
            "min_ml_prob": 0.55,
            "regime_weights": {"TRENDING": 1.0, "RANGING": 0.8, "VOLATILE": 0.6},
            "best_assets": [],
            "avoid_assets": [],
            "version": 1,
        }
    }
    return load_json("portfolio_state.json", default=default)

def save_state(state):
    save_json("portfolio_state.json", state)

# ─── Sync from trade log ──────────────────────────────────────────────────

def sync_from_log(state):
    """Read multi-trade-log.json and build virtual P&L from paper trades."""
    if not os.path.exists(LOG_FILE):
        return state

    log = load_json("multi-trade-log.json", default={"trades": []})

    already_processed = {t["log_ref"] for t in state["closed_trades"] if "log_ref" in t}

    capital = state["virtual_capital"]
    open_pos = state["open_positions"]

    for i, entry in enumerate(log.get("trades", [])):
        ref = f"{entry['timestamp']}_{entry['symbol']}"
        if ref in already_processed:
            continue
        if not entry.get("orderPlaced") or not entry.get("paperTrading"):
            continue

        symbol   = entry["symbol"]
        action   = entry.get("signal", {}).get("action", "HOLD")
        price    = entry.get("price", 0)
        size_usd = entry.get("tradeSize", 0)
        ts       = entry.get("timestamp", "")
        regime   = entry.get("regime", "")
        ml_conf  = entry.get("mlConfidence", 0)

        if price <= 0 or size_usd <= 0:
            continue

        date = ts[:10]

        if action == "BUY" and symbol not in open_pos:
            qty = size_usd / price
            open_pos[symbol] = {
                "entry_price": price, "qty": qty,
                "size_usd": size_usd, "date": date,
                "regime": regime, "ml_conf": ml_conf,
            }
            capital -= size_usd  # spend capital

        elif action == "SELL" and symbol in open_pos:
            pos = open_pos.pop(symbol)
            exit_value = pos["qty"] * price
            entry_value = pos["size_usd"]
            pnl = exit_value - entry_value
            pnl_pct = (pnl / entry_value) * 100
            capital += exit_value

            trade_rec = {
                "log_ref": ref, "symbol": symbol,
                "entry_price": round(pos["entry_price"], 6),
                "exit_price": round(price, 6),
                "qty": round(pos["qty"], 8),
                "entry_date": pos["date"], "exit_date": date,
                "pnl_usd": round(pnl, 4),
                "pnl_pct": round(pnl_pct, 3),
                "regime": pos["regime"], "ml_conf": pos["ml_conf"],
            }
            state["closed_trades"].append(trade_rec)

            # Daily P&L
            state["daily_pnl"][date] = round(
                state["daily_pnl"].get(date, 0) + pnl, 4
            )

    state["virtual_capital"] = round(capital, 4)
    state["open_positions"] = open_pos
    return state

# ─── Learning Engine ───────────────────────────────────────────────────────

def learn_and_adapt(state):
    """
    Analyse closed trades and update adaptive thresholds.
    - Raise min_confidence if win rate < 50%
    - Lower min_confidence if win rate > 65% (be more active)
    - Build best/avoid asset lists
    - Adjust regime weights
    """
    trades = state["closed_trades"]
    if len(trades) < 10:
        print("  Not enough trades yet to learn (need 10+). Keep running!")
        return state

    # Overall win rate
    wins   = [t for t in trades if t["pnl_usd"] > 0]
    losses = [t for t in trades if t["pnl_usd"] <= 0]
    win_rate = len(wins) / len(trades)

    adp = state["adaptive"]

    # Confidence threshold adjustment
    if win_rate < 0.45:
        adp["min_confidence"] = min(adp["min_confidence"] + 0.03, 0.80)
        adp["min_ml_prob"]    = min(adp["min_ml_prob"] + 0.02, 0.80)
        print(f"  [CHART] Win rate low ({win_rate:.0%}) — raising confidence threshold to {adp['min_confidence']:.2f}")
    elif win_rate > 0.65:
        adp["min_confidence"] = max(adp["min_confidence"] - 0.02, 0.45)
        print(f"  🎯 Win rate high ({win_rate:.0%}) — loosening confidence threshold to {adp['min_confidence']:.2f}")
    else:
        print(f"  ✅ Win rate healthy ({win_rate:.0%}) — thresholds unchanged")

    # Per-asset performance
    by_asset = defaultdict(list)
    for t in trades:
        by_asset[t["symbol"]].append(t["pnl_usd"])

    asset_wr = {}
    for sym, pnls in by_asset.items():
        w = sum(1 for p in pnls if p > 0)
        asset_wr[sym] = w / len(pnls)

    adp["best_assets"]  = [s for s, wr in sorted(asset_wr.items(), key=lambda x: -x[1]) if wr >= 0.55][:5]
    adp["avoid_assets"] = [s for s, wr in sorted(asset_wr.items(), key=lambda x: x[1])  if wr <= 0.35][:3]

    # Regime weights
    for regime in ["TRENDING", "RANGING", "VOLATILE"]:
        rt = [t for t in trades if t.get("regime") == regime]
        if len(rt) >= 5:
            rwr = sum(1 for t in rt if t["pnl_usd"] > 0) / len(rt)
            adp["regime_weights"][regime] = round(0.5 + rwr, 2)

    adp["version"] += 1
    adp["last_updated"] = datetime.utcnow().isoformat()

    state["adaptive"] = adp
    save_state(state)

    print(f"\n  [BRAIN] Adaptive model v{adp['version']} saved")
    print(f"  Best assets:  {adp['best_assets']}")
    print(f"  Avoid:        {adp['avoid_assets']}")
    print(f"  Regime weights: {adp['regime_weights']}")
    print(f"  Min confidence: {adp['min_confidence']:.2f}")
    return state

# ─── Report Generator ─────────────────────────────────────────────────────

def print_report(state):
    trades   = state["closed_trades"]
    open_pos = state["open_positions"]
    capital  = state["virtual_capital"]

    # Mark-to-market open positions (approximate — use last known price)
    open_value = sum(p["size_usd"] for p in open_pos.values())
    total_value = capital + open_value

    start_date = datetime.strptime(CHALLENGE_START, "%Y-%m-%d")
    today      = datetime.utcnow()
    days_run   = (today - start_date).days
    days_left  = max(0, CHALLENGE_DAYS - days_run)
    pnl_total  = total_value - STARTING_CAPITAL
    pnl_pct    = (pnl_total / STARTING_CAPITAL) * 100
    annualized = (pnl_pct / max(days_run, 1)) * 365

    wins   = [t for t in trades if t["pnl_usd"] > 0]
    losses = [t for t in trades if t["pnl_usd"] <= 0]
    win_rate = len(wins) / len(trades) * 100 if trades else 0

    avg_win  = sum(t["pnl_usd"] for t in wins)  / len(wins)  if wins   else 0
    avg_loss = sum(t["pnl_usd"] for t in losses) / len(losses) if losses else 0
    pf = abs(sum(t["pnl_usd"] for t in wins) / sum(t["pnl_usd"] for t in losses)) if losses and sum(t["pnl_usd"] for t in losses) != 0 else 999

    # Best/worst trades
    best  = max(trades, key=lambda t: t["pnl_usd"]) if trades else None
    worst = min(trades, key=lambda t: t["pnl_usd"]) if trades else None

    # Daily P&L streak
    daily = state.get("daily_pnl", {})
    sorted_days = sorted(daily.items())

    sep = "=" * 55

    print(f"\n{sep}")
    print(f"  [TROPHY] 90-DAY PAPER TRADING CHALLENGE REPORT")
    print(f"  Started: {CHALLENGE_START}  |  Day {days_run}/{CHALLENGE_DAYS}  ({days_left} days left)")
    print(sep)
    print(f"  Starting Capital:  EUR{STARTING_CAPITAL:>10,.2f}")
    print(f"  Current Value:     EUR{total_value:>10,.2f}")
    print(f"  Total P&L:         EUR{pnl_total:>+10,.2f}  ({pnl_pct:+.2f}%)")
    print(f"  Annualized Return: {annualized:>+.1f}%")
    print(f"  Open Positions:    {len(open_pos)}  (est. EUR{open_value:.2f})")
    print(sep)
    print(f"  TRADE STATS")
    print(f"  Total Closed:   {len(trades)}")
    print(f"  Win Rate:       {win_rate:.1f}%  ({len(wins)}W / {len(losses)}L)")
    print(f"  Avg Win:       +EUR{avg_win:.4f}")
    print(f"  Avg Loss:       EUR{avg_loss:.4f}")
    print(f"  Profit Factor:  {pf:.2f}x")
    if best:
        print(f"  Best Trade:    +EUR{best['pnl_usd']:.4f}  ({best['symbol']} {best['exit_date']})")
    if worst:
        print(f"  Worst Trade:    EUR{worst['pnl_usd']:.4f}  ({worst['symbol']} {worst['exit_date']})")
    print(sep)

    # Per-asset breakdown
    if trades:
        by_asset = defaultdict(list)
        for t in trades:
            by_asset[t["symbol"]].append(t["pnl_usd"])
        print(f"  ASSET BREAKDOWN")
        print(f"  {'Symbol':<12} {'Trades':>6} {'Win%':>6} {'Total P&L':>10}")
        print("  " + "-" * 40)
        for sym, pnls in sorted(by_asset.items(), key=lambda x: -sum(x[1])):
            wr = sum(1 for p in pnls if p > 0) / len(pnls) * 100
            print(f"  {sym:<12} {len(pnls):>6} {wr:>5.0f}% {sum(pnls):>+10.4f}")
        print(sep)

    # Daily P&L last 10 days
    if sorted_days:
        print(f"  DAILY P&L (last 10 days)")
        for date, pnl in sorted_days[-10:]:
            bar = "#" * int(abs(pnl) / max(abs(v) for _, v in sorted_days) * 20) if sorted_days else ""
            sign = "+" if pnl >= 0 else ""
            print(f"  {date}  {sign}EUR{pnl:.4f}  {'[GREEN]' if pnl >= 0 else '[RED]'} {bar}")
        print(sep)

    # Adaptive learning status
    adp = state.get("adaptive", {})
    print(f"  [BRAIN] ADAPTIVE LEARNING (v{adp.get('version',1)})")
    print(f"  Min Confidence:   {adp.get('min_confidence', 0.50):.2f}")
    print(f"  Best Assets:      {adp.get('best_assets', [])}")
    print(f"  Avoid Assets:     {adp.get('avoid_assets', [])}")
    print(f"  Regime Weights:   {adp.get('regime_weights', {})}")
    print(sep)

    # Projection
    if days_run > 7 and pnl_pct != 0:
        daily_rate = pnl_pct / days_run
        projected  = STARTING_CAPITAL * (1 + (daily_rate / 100) * CHALLENGE_DAYS)
        print(f"  [CHART] PROJECTION at current rate:")
        print(f"  Day 90 estimate: EUR{projected:.2f}  ({(projected-STARTING_CAPITAL)/STARTING_CAPITAL*100:+.1f}%)")
        print(sep)

    print()


# ─── CLI ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"

    state = load_state()
    state = sync_from_log(state)
    save_state(state)

    if cmd == "report":
        print_report(state)
        # Always regenerate performance analytics alongside the report
        try:
            from performance_analytics import run_once as perf_run
            print("\n" + "=" * 55)
            print("  PERFORMANCE ANALYTICS & GO/NO-GO VERDICT")
            print("=" * 55)
            perf_run()
        except Exception as e:
            print(f"  [perf] {e}")
    elif cmd == "learn":
        print("\n[BRAIN] Running adaptive learning engine...")
        state = learn_and_adapt(state)
        save_state(state)
        print_report(state)
        try:
            from performance_analytics import run_once as perf_run
            perf_run()
        except Exception as e:
            print(f"  [perf] {e}")
    elif cmd == "reset":
        if os.path.exists(TRACKER_FILE):
            os.remove(TRACKER_FILE)
        print("Portfolio state reset.")
    else:
        print("Usage: python portfolio_tracker.py [report|learn|reset]")
