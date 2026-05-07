"""
Performance Analytics -- Go/No-Go Engine
=========================================
Computes institutional-grade trading metrics from the paper trade log.
Used by portfolio_tracker.py and dashboard.html (via perf_state.json).

Metrics:
  - Win Rate          % of closed trades that were profitable
  - Profit Factor     gross profit / gross loss (>1.5 = acceptable, >2 = good)
  - Expectancy        avg $ earned per trade (must be positive)
  - Sharpe Ratio      risk-adjusted return (daily returns, >1.0 = go)
  - Sortino Ratio     downside-only risk (>1.5 = good)
  - Max Drawdown      largest peak-to-trough equity drop (< -15% = stop)
  - Avg Win / Loss    reward:risk ratio (must be > 1.5)
  - Consecutive Loss  worst losing streak (> 5 = concern)
  - Calmar Ratio      annualised return / max drawdown (> 1 = good)
  - Recovery Factor   total profit / max drawdown

Go/No-Go Verdict:
  GREEN  -- All key metrics pass. Consider small live allocation.
  YELLOW -- Marginal. More paper trading needed.
  RED    -- System not ready. Do not trade real money.

CLI:
  python performance_analytics.py           # full report + verdict
  python performance_analytics.py --json    # dump perf_state.json
  python performance_analytics.py --watch   # rerun every 60s
"""

import os, sys, math, time
from datetime import datetime, timezone
from collections import defaultdict
from state_manager import load_json, save_json

CHALLENGE_START   = "2026-05-07"
STARTING_CAPITAL  = 100000.0   # 100k EUR paper trading fund
CHALLENGE_DAYS    = 90
RISK_FREE_RATE    = 0.05   # 5% annual (approx. EUR savings rate)

# ── Go/No-Go thresholds ────────────────────────────────────────────────────
THRESHOLDS = {
    "win_rate":          {"green": 0.52, "yellow": 0.45,  "label": "Win Rate"},
    "profit_factor":     {"green": 1.50, "yellow": 1.10,  "label": "Profit Factor"},
    "expectancy":        {"green": 0.10, "yellow": 0.0,   "label": "Expectancy ($/trade)"},
    "sharpe":            {"green": 1.00, "yellow": 0.50,  "label": "Sharpe Ratio"},
    "sortino":           {"green": 1.50, "yellow": 0.75,  "label": "Sortino Ratio"},
    "max_drawdown_pct":  {"green":-10.0, "yellow":-20.0,  "label": "Max Drawdown"},   # more negative = worse
    "reward_risk":       {"green": 1.50, "yellow": 1.10,  "label": "Reward:Risk"},
    "min_trades":        {"green":  30,  "yellow":  15,   "label": "Min Trades"},
}

# ── Load trade data ────────────────────────────────────────────────────────

def load_closed_trades() -> list:
    """
    Load closed trades from portfolio_state.json (preferred — has P&L).
    Falls back to inferring from multi-trade-log.json directly.
    """
    state = load_json("portfolio_state.json", default={})
    ct = state.get("closed_trades", [])
    if ct:
        return ct

    # Fallback: infer from log (BUY followed by SELL on same symbol)
    log = load_json("multi-trade-log.json", default={"trades": []})

    open_pos = {}
    closed   = []
    for entry in log.get("trades", []):
        if not entry.get("orderPlaced"):
            continue
        sym    = entry["symbol"]
        action = entry.get("signal", {}).get("action", "HOLD")
        price  = entry.get("price", 0)
        size   = entry.get("tradeSize", 0)
        ts     = entry.get("timestamp", "")
        if price <= 0 or size <= 0:
            continue
        if action == "BUY" and sym not in open_pos:
            open_pos[sym] = {"entry_price": price, "size_usd": size, "ts": ts,
                             "ml_conf": entry.get("mlConfidence", 0),
                             "regime":   entry.get("regime", "")}
        elif action == "SELL" and sym in open_pos:
            pos = open_pos.pop(sym)
            qty = pos["size_usd"] / pos["entry_price"]
            pnl = qty * price - pos["size_usd"]
            closed.append({
                "symbol":      sym,
                "entry_price": pos["entry_price"],
                "exit_price":  price,
                "qty":         qty,
                "size_usd":    pos["size_usd"],
                "pnl_usd":     round(pnl, 4),
                "pnl_pct":     round(pnl / pos["size_usd"] * 100, 3),
                "entry_date":  pos["ts"][:10],
                "exit_date":   ts[:10],
                "ml_conf":     pos["ml_conf"],
                "regime":      pos["regime"],
            })
    return closed

def load_daily_pnl() -> dict:
    """Load daily P&L dict from portfolio_state.json."""
    return load_json("portfolio_state.json", default={}).get("daily_pnl", {})

# ── Core metrics ──────────────────────────────────────────────────────────

def compute_metrics(trades: list, daily_pnl: dict) -> dict:
    if not trades:
        return _empty_metrics()

    wins   = [t for t in trades if t["pnl_usd"] > 0]
    losses = [t for t in trades if t["pnl_usd"] <= 0]
    n      = len(trades)

    win_rate      = len(wins)  / n
    gross_profit  = sum(t["pnl_usd"] for t in wins)
    gross_loss    = abs(sum(t["pnl_usd"] for t in losses)) or 1e-9
    profit_factor = gross_profit / gross_loss

    avg_win  = gross_profit / len(wins)   if wins   else 0.0
    avg_loss = gross_loss   / len(losses) if losses else 1e-9
    reward_risk  = avg_win / avg_loss
    expectancy   = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)

    # ── Equity curve from daily P&L ──
    sorted_days = sorted(daily_pnl.items()) if daily_pnl else []
    if sorted_days:
        equity = [STARTING_CAPITAL]
        for _, pnl in sorted_days:
            equity.append(equity[-1] + pnl)
    else:
        # Build from trades if daily_pnl missing
        equity = [STARTING_CAPITAL]
        cumulative = 0
        for t in sorted(trades, key=lambda x: x.get("exit_date", "")):
            cumulative += t["pnl_usd"]
            equity.append(STARTING_CAPITAL + cumulative)

    # Max drawdown
    peak = equity[0]
    max_dd_abs = 0.0
    for v in equity:
        if v > peak:
            peak = v
        dd = v - peak
        if dd < max_dd_abs:
            max_dd_abs = dd
    max_dd_pct = (max_dd_abs / STARTING_CAPITAL) * 100  # negative number

    # Daily returns for Sharpe/Sortino
    if len(equity) > 1:
        daily_returns = [(equity[i] - equity[i-1]) / equity[i-1]
                         for i in range(1, len(equity))]
    else:
        daily_returns = [t["pnl_pct"] / 100 for t in trades]

    n_days   = len(daily_returns) or 1
    mean_ret = sum(daily_returns) / n_days
    rfr_daily = RISK_FREE_RATE / 252
    excess_returns = [r - rfr_daily for r in daily_returns]
    mean_excess = sum(excess_returns) / n_days

    variance  = sum((r - mean_ret) ** 2 for r in daily_returns) / max(n_days - 1, 1)
    std_dev   = math.sqrt(variance) or 1e-9
    sharpe    = (mean_excess / std_dev) * math.sqrt(252)

    # Sortino (downside std only)
    down_returns  = [r for r in daily_returns if r < rfr_daily]
    down_variance = sum((r - rfr_daily) ** 2 for r in down_returns) / max(len(down_returns) - 1, 1) if down_returns else 1e-9
    down_std      = math.sqrt(down_variance) or 1e-9
    sortino       = (mean_excess / down_std) * math.sqrt(252)

    # Calmar & Recovery
    days_run     = max(1, (datetime.now(timezone.utc) - datetime.strptime(CHALLENGE_START, "%Y-%m-%d").replace(tzinfo=timezone.utc)).days)
    total_pnl    = sum(t["pnl_usd"] for t in trades)
    annual_ret   = (total_pnl / STARTING_CAPITAL) * (365 / days_run) * 100
    calmar       = abs(annual_ret / max(abs(max_dd_pct), 0.01))
    recovery     = abs(gross_profit / max(abs(max_dd_abs), 0.01))

    # Consecutive loss streak
    streak = max_streak = 0
    for t in sorted(trades, key=lambda x: x.get("exit_date", "")):
        if t["pnl_usd"] <= 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0

    # Per-asset breakdown
    by_asset = defaultdict(list)
    for t in trades:
        by_asset[t["symbol"]].append(t["pnl_usd"])
    asset_stats = {}
    for sym, pnls in by_asset.items():
        w = sum(1 for p in pnls if p > 0)
        asset_stats[sym] = {
            "trades":    len(pnls),
            "win_rate":  round(w / len(pnls), 3),
            "total_pnl": round(sum(pnls), 4),
            "avg_pnl":   round(sum(pnls) / len(pnls), 4),
        }

    # Per-regime breakdown
    by_regime = defaultdict(list)
    for t in trades:
        if t.get("regime"):
            by_regime[t["regime"]].append(t["pnl_usd"])
    regime_stats = {}
    for reg, pnls in by_regime.items():
        w = sum(1 for p in pnls if p > 0)
        regime_stats[reg] = {
            "trades":   len(pnls),
            "win_rate": round(w / len(pnls), 3),
            "total":    round(sum(pnls), 4),
        }

    return {
        "computed_at":    datetime.now(timezone.utc).isoformat(),
        "trade_count":    n,
        "win_count":      len(wins),
        "loss_count":     len(losses),
        "win_rate":       round(win_rate, 4),
        "profit_factor":  round(profit_factor, 3),
        "expectancy":     round(expectancy, 4),
        "avg_win":        round(avg_win, 4),
        "avg_loss":       round(avg_loss, 4),
        "reward_risk":    round(reward_risk, 3),
        "sharpe":         round(sharpe, 3),
        "sortino":        round(sortino, 3),
        "calmar":         round(calmar, 3),
        "recovery_factor":round(recovery, 3),
        "max_drawdown_pct":  round(max_dd_pct, 3),
        "max_drawdown_abs":  round(max_dd_abs, 4),
        "max_loss_streak":   max_streak,
        "total_pnl":         round(total_pnl, 4),
        "total_pnl_pct":     round(total_pnl / STARTING_CAPITAL * 100, 3),
        "annual_return_pct": round(annual_ret, 3),
        "days_running":      days_run,
        "equity_curve":      [round(v, 2) for v in equity],
        "asset_stats":       asset_stats,
        "regime_stats":      regime_stats,
    }

def _empty_metrics() -> dict:
    return {
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "trade_count": 0, "win_count": 0, "loss_count": 0,
        "win_rate": 0.0, "profit_factor": 0.0, "expectancy": 0.0,
        "avg_win": 0.0, "avg_loss": 0.0, "reward_risk": 0.0,
        "sharpe": 0.0, "sortino": 0.0, "calmar": 0.0, "recovery_factor": 0.0,
        "max_drawdown_pct": 0.0, "max_drawdown_abs": 0.0,
        "max_loss_streak": 0, "total_pnl": 0.0, "total_pnl_pct": 0.0,
        "annual_return_pct": 0.0, "days_running": 0,
        "equity_curve": [STARTING_CAPITAL],
        "asset_stats": {}, "regime_stats": {},
    }

# ── Go/No-Go Verdict ──────────────────────────────────────────────────────

def compute_verdict(m: dict) -> dict:
    checks = []
    score  = 0
    total  = 0

    def check(key, value, label, higher_is_better=True):
        nonlocal score, total
        t = THRESHOLDS[key]
        gv, yv = t["green"], t["yellow"]
        if higher_is_better:
            if value >= gv:   status, pts = "GREEN",  2
            elif value >= yv: status, pts = "YELLOW", 1
            else:             status, pts = "RED",     0
        else:
            # lower is better (drawdown: less negative = better)
            if value >= gv:   status, pts = "GREEN",  2
            elif value >= yv: status, pts = "YELLOW", 1
            else:             status, pts = "RED",     0
        score += pts
        total += 2
        checks.append({"key": key, "label": label, "value": value,
                       "green_threshold": gv, "yellow_threshold": yv,
                       "status": status, "higher_is_better": higher_is_better})

    n = m["trade_count"]
    check("min_trades",      n,                           "Trade Sample Size",  True)
    check("win_rate",        m["win_rate"],               "Win Rate",            True)
    check("profit_factor",   m["profit_factor"],          "Profit Factor",       True)
    check("expectancy",      m["expectancy"],             "Expectancy ($/trade)",True)
    check("sharpe",          m["sharpe"],                 "Sharpe Ratio",        True)
    check("sortino",         m["sortino"],                "Sortino Ratio",       True)
    check("max_drawdown_pct",m["max_drawdown_pct"],       "Max Drawdown",        False)
    check("reward_risk",     m["reward_risk"],            "Reward:Risk",         True)

    pct = score / total if total else 0
    if pct >= 0.80:   verdict = "GREEN"
    elif pct >= 0.55: verdict = "YELLOW"
    else:             verdict = "RED"

    messages = {
        "GREEN":  "System shows positive expectancy. Consider a small live allocation (EUR 50-100).",
        "YELLOW": "Marginal performance. Continue paper trading for at least 30 more trades.",
        "RED":    "System not ready. Do NOT trade real money. Review signals and thresholds.",
    }

    return {
        "verdict":    verdict,
        "score":      round(pct * 100),
        "message":    messages[verdict],
        "checks":     checks,
        "next_review": _next_review_date(n),
    }

def _next_review_date(n_trades: int) -> str:
    if n_trades < 15:  return f"After {15 - n_trades} more trades"
    if n_trades < 30:  return f"After {30 - n_trades} more trades"
    return "Ready for review now"

# ── Print Report ──────────────────────────────────────────────────────────

COLORS = {"GREEN": "\033[92m", "YELLOW": "\033[93m", "RED": "\033[91m", "RESET": "\033[0m"}

def print_full_report(m: dict, v: dict):
    G, Y, R, RST = COLORS["GREEN"], COLORS["YELLOW"], COLORS["RED"], COLORS["RESET"]
    vc = {"GREEN": G, "YELLOW": Y, "RED": R}

    sep  = "=" * 62
    sep2 = "-" * 62
    print(f"\n{sep}")
    print(f"  QUANT ALPHA -- Performance Analytics")
    print(f"  {m['computed_at'][:19]} UTC  |  Day {m['days_running']}/{CHALLENGE_DAYS}")
    print(sep)

    pnl_col = G if m["total_pnl"] >= 0 else R
    print(f"  Total P&L:        {pnl_col}EUR{m['total_pnl']:>+10.4f}  ({m['total_pnl_pct']:+.2f}%){RST}")
    print(f"  Annualised Return: {m['annual_return_pct']:>+.1f}%")
    print(f"  Max Drawdown:     {R if m['max_drawdown_pct'] < -10 else Y}{m['max_drawdown_pct']:>+.2f}%  (EUR{m['max_drawdown_abs']:>+.2f}){RST}")
    print(sep2)

    print(f"  TRADE STATISTICS  ({m['trade_count']} closed trades)")
    wr_col = G if m["win_rate"] >= 0.52 else (Y if m["win_rate"] >= 0.45 else R)
    print(f"  Win Rate:         {wr_col}{m['win_rate']*100:.1f}%{RST}  ({m['win_count']}W / {m['loss_count']}L)")
    pf_col = G if m["profit_factor"] >= 1.5 else (Y if m["profit_factor"] >= 1.1 else R)
    print(f"  Profit Factor:    {pf_col}{m['profit_factor']:.3f}x{RST}  (>1.5 = good)")
    exp_col = G if m["expectancy"] > 0.1 else (Y if m["expectancy"] > 0 else R)
    print(f"  Expectancy:       {exp_col}EUR{m['expectancy']:>+.4f}{RST} per trade")
    rr_col  = G if m["reward_risk"] >= 1.5 else (Y if m["reward_risk"] >= 1.1 else R)
    print(f"  Avg Win:         +EUR{m['avg_win']:.4f}")
    print(f"  Avg Loss:         EUR{m['avg_loss']:.4f}")
    print(f"  Reward:Risk:      {rr_col}{m['reward_risk']:.2f}:1{RST}")
    print(f"  Max Loss Streak:  {R if m['max_loss_streak'] >= 5 else Y}{m['max_loss_streak']}{RST} consecutive losses")
    print(sep2)

    print(f"  RISK-ADJUSTED RETURNS")
    sh_col = G if m["sharpe"] >= 1.0 else (Y if m["sharpe"] >= 0.5 else R)
    so_col = G if m["sortino"] >= 1.5 else (Y if m["sortino"] >= 0.75 else R)
    ca_col = G if m["calmar"] >= 1.0 else (Y if m["calmar"] >= 0.5 else R)
    print(f"  Sharpe Ratio:     {sh_col}{m['sharpe']:.3f}{RST}  (>1.0 = acceptable)")
    print(f"  Sortino Ratio:    {so_col}{m['sortino']:.3f}{RST}  (>1.5 = good)")
    print(f"  Calmar Ratio:     {ca_col}{m['calmar']:.3f}{RST}  (>1.0 = good)")
    print(f"  Recovery Factor:  {m['recovery_factor']:.3f}x")
    print(sep2)

    if m["asset_stats"]:
        print(f"  ASSET BREAKDOWN")
        print(f"  {'Symbol':<12} {'N':>3} {'Win%':>5} {'P&L':>9} {'Avg':>7}")
        print("  " + "-" * 40)
        sorted_assets = sorted(m["asset_stats"].items(), key=lambda x: -x[1]["total_pnl"])
        for sym, s in sorted_assets:
            col = G if s["total_pnl"] > 0 else R
            print(f"  {sym:<12} {s['trades']:>3} {s['win_rate']*100:>4.0f}% {col}{s['total_pnl']:>+9.4f}{RST} {s['avg_pnl']:>+7.4f}")
        print(sep2)

    if m["regime_stats"]:
        print(f"  REGIME BREAKDOWN")
        for reg, s in m["regime_stats"].items():
            col = G if s["total"] > 0 else R
            print(f"  {reg:<12} {s['trades']}t  {s['win_rate']*100:.0f}% win  {col}{s['total']:>+.4f}{RST}")
        print(sep2)

    # Go/No-Go
    vd = v["verdict"]
    print(f"\n  GO / NO-GO SCORECARD  ({v['score']}/100)")
    print(sep2)
    for c in v["checks"]:
        status = c["status"]
        col    = vc[status]
        sym    = {"GREEN": "PASS", "YELLOW": "WARN", "RED": "FAIL"}[status]
        val_str = f"{c['value']*100:.1f}%" if "rate" in c["key"] else (
                  f"{c['value']:.3f}" if isinstance(c["value"], float) else str(c["value"]))
        print(f"  {col}[{sym}]{RST}  {c['label']:<26}  {val_str}")
    print(sep2)
    print(f"\n  VERDICT: {vc[vd]}{'#' * 5} {vd} {'#' * 5}{RST}")
    print(f"  {v['message']}")
    print(f"  {v['next_review']}")
    print(f"\n{sep}\n")

# ── Write perf_state.json ─────────────────────────────────────────────────

def write_perf_state(m: dict, v: dict):
    save_json("perf_state.json", {"metrics": m, "verdict": v})
    print(f"  [OK] perf_state.json written")

# ── CLI ───────────────────────────────────────────────────────────────────

def run_once(output_json=False, silent=False):
    trades    = load_closed_trades()
    daily_pnl = load_daily_pnl()
    m = compute_metrics(trades, daily_pnl)
    v = compute_verdict(m)
    if not silent:
        print_full_report(m, v)
    write_perf_state(m, v)
    return m, v

if __name__ == "__main__":
    args = sys.argv[1:]

    if "--watch" in args:
        print("Watching trade log — refreshing every 60s. Ctrl+C to stop.\n")
        while True:
            try:
                os.system("cls" if os.name == "nt" else "clear")
                run_once()
                time.sleep(60)
            except KeyboardInterrupt:
                break
    elif "--json" in args:
        trades    = load_closed_trades()
        daily_pnl = load_daily_pnl()
        m = compute_metrics(trades, daily_pnl)
        v = compute_verdict(m)
        write_perf_state(m, v)
        print(json.dumps({"metrics": m, "verdict": v}, indent=2))
    else:
        run_once()
