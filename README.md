# Quant Alpha — Dual Wealth System

> **Two systems. One goal: financial freedom.**
> A retirement SIP engine + an active scalping bot, built on Scott Galloway's Algebra of Wealth.

---

## The Philosophy

Scott Galloway's formula: **Wealth = Focus × Stoicism × Time × Diversification**

Applied here as an 80/20 split on a €300/month budget:

| System | Monthly | Role | Time Horizon |
|--------|---------|------|-------------|
| 🌱 **SIP Retirement Engine** | €240 (80%) | Compounding machine | 20–30 years |
| ⚡ **Alpaca Scalping Bot** | €60 (20%) | Short-term income generator | Daily |

The bot doesn't beat the SIP long-term. It **feeds** it — profits flow back into the SIP contributions, accelerating the compounding engine.

---

## ⚔️ SIP vs Bot — The Wealth Battle

At 10.5% annual compounding (historical US market average):

| Horizon | SIP (€240/mo) | Bot (5%/mo reinvested on €180) |
|---------|--------------|-------------------------------|
| 5 years | €19,000 | €3,600 |
| 10 years | **€50,000** | €12,000 |
| 20 years | **€195,000** | €45,000 |
| 30 years | **€580,000** | €130,000 |

The SIP wins every time horizon past 3 years. The bot is the capital engine. The SIP is the wealth machine.

---

## System 1 — SIP Retirement Engine

Sends Telegram alerts when it's the right time to manually invest on Revolut / Trade Republic.

### How It Works

Two separate alert types:

| Script | Trigger | What It Sends |
|--------|---------|--------------|
| `sip_dip_alert.js` | Price dip **AND** RSI oversold | "Buy now — optimal entry confirmed" |
| `sip_notifier.js` | 1st of every month | "Here's your monthly SIP checklist" |

### The Buy Signal Logic

A single condition (dip alone, or RSI alone) is not enough:
- **Dip only** = could be a falling knife — price keeps dropping
- **RSI only** = could stay oversold for months in a bear market
- **Both together** = historically high-probability recovery entry

```
Stocks: dip ≥ 5% from 120-day high  AND  RSI < 40
Crypto: dip ≥ 8% from 120-day high  AND  RSI < 38
```

### Alert Tiers

| Tier | Dip | Emoji | Buy Amount |
|------|-----|-------|-----------|
| Good Entry | ≥ 5% | 🟡 | 1× your monthly SIP |
| Strong Dip | ≥ 10% | 🟠 | 1.5× your monthly SIP |
| Screaming Buy | ≥ 20% | 🔴 | 2× your monthly SIP |

### Your Current SIP Plan (Galloway 80/20)

| Asset | Monthly | Category | Goal |
|-------|---------|----------|------|
| VTI | €100 | Core Index | Retirement |
| SCHD | €60 | Dividend | Passive Income |
| VXUS | €50 | International | Diversification |
| BTC | €30 | Crypto | Digital Gold |
| **Total** | **€240** | | |

### Setup

```bash
# Install Node.js 18+ first

# Clone
git clone https://github.com/bpulksi/quant-alpha.git
cd quant-alpha

# Configure
cp .env.example .env
# Add: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID

# Get your Telegram credentials:
# 1. Message @BotFather → /newbot → copy token
# 2. Message @userinfobot → copy your chat ID
```

### Run

```bash
# Preview what would fire today (no message sent)
node --env-file=.env sip_dip_alert.js --dry-run

# Run once (sends Telegram if conditions met)
node --env-file=.env sip_dip_alert.js

# Run on schedule (scans twice daily: 9am + 6pm)
node --env-file=.env sip_dip_alert.js --schedule

# Send this month's SIP checklist now
node --env-file=.env sip_notifier.js

# Auto-send on 1st of every month at 9am
node --env-file=.env sip_notifier.js --schedule
```

### SIP Dashboard

Open `sip_dashboard.html` in a browser to:
- Plan your monthly allocations
- Visualise 20-year compound growth
- Export `sip_plan.json` (read by both scripts)

---

## System 2 — Alpaca Scalping Bot

A 5-layer quantitative trading system scanning 20 crypto + 36 stock assets every 15 minutes on Alpaca paper/live.

### Architecture

```
market data → quant_engine_v3.py → ML signal → multi_trader.js → Alpaca order
                     ↑                               ↓
              5 technical layers              stop-loss + take-profit
              GBM + RF classifiers           Telegram notification
              HTF regime filter              trades.csv (tax log)
```

### The 5 Signal Layers

| Layer | What It Does |
|-------|-------------|
| **Regime Detection** | ADX + EMA — identifies TRENDING vs RANGING vs VOLATILE |
| **Technical Indicators** | RSI, MACD, Bollinger Bands, Stochastic, CCI |
| **ML Ensemble** | Gradient Boosted Machine + Random Forest (walk-forward trained) |
| **HTF Filter** | 1h EMA21 + RSI — blocks counter-trend entries on 15m signals |
| **Risk Management** | 3% stop-loss + 2.5% take-profit on every BUY |

### Assets Traded

**Crypto (20):** BTC, ETH, SOL, XRP, AVAX, ADA, DOT, LINK, LTC, DOGE, BNB, SUI, UNI, XLM, ATOM, TRX, INJ, RENDER, TAO, FIL

**Stocks (36):** AAPL, MSFT, NVDA, GOOGL, META, AMZN, TSLA, AMD, PLTR, CRM, ORCL, SNOW, COIN, MSTR, SOFI, JPM, V, MA, GS, LLY, UNH, JNJ, MRNA, XOM, CVX, WMT, COST, MCD, SPY, QQQ, IWM, GLD, TLT, XLE, XLF, XLV

### Setup

```bash
# Python dependencies
pip install pandas numpy scikit-learn ta requests

# Node dependencies
npm install

# Train ML models (takes ~10 minutes first time)
python quant_engine_v3.py train-all
```

### Configure `.env`

```env
ALPACA_API_KEY=your_key
ALPACA_SECRET_KEY=your_secret
PAPER_TRADING=true          # flip to false when ready to go live
PORTFOLIO_VALUE_USD=100000  # paper; set to your real balance for live
MAX_TRADE_SIZE_USD=8000     # paper; use 25 for live with €180
MAX_TRADES_PER_DAY=10
TELEGRAM_BOT_TOKEN=your_token
TELEGRAM_CHAT_ID=your_chat_id
```

### Run

```bash
# Start bot (scans every 15 minutes)
node --env-file=.env server.js

# Or run multi_trader directly
node --env-file=.env multi_trader.js

# Dashboard at http://localhost:3000
```

### Go-Live Checklist

Before flipping `PAPER_TRADING=false`:

- [ ] 4 weeks of profitable paper trading
- [ ] €180+ saved in Alpaca live account (3 months of €60 deposits)
- [ ] Set `PAPER_TRADING=false`
- [ ] Set `MAX_TRADE_SIZE_USD=25`
- [ ] Set `PORTFOLIO_VALUE_USD=180`

---

## Files

### SIP System
| File | Purpose |
|------|---------|
| `sip_dashboard.html` | Retirement planner UI — open in browser |
| `sip_dip_alert.js` | Dip + RSI buy signal alerts (Telegram) |
| `sip_notifier.js` | Monthly investment checklist (Telegram) |
| `sip_shared.js` | Shared utilities for both SIP scripts |
| `sip_plan.json` | Your active SIP plan (edit via dashboard) |
| `sip_dip_state.json` | Alert cooldown tracker (auto-managed) |

### Trading Bot
| File | Purpose |
|------|---------|
| `server.js` | Express server + bot scheduler |
| `multi_trader.js` | 56-asset trading logic with stop/TP |
| `quant_engine_v3.py` | ML + technical signal engine |
| `dashboard.html` | Live trading dashboard |
| `trades.csv` | Tax-ready trade log (auto-written) |
| `portfolio_state.json` | Current positions + P&L |

---

## The Wealth Formula in Practice

```
Month 1–3:   Save €60/month → €180 live trading capital
Month 4+:    Bot runs live → profits extracted monthly
             ↓
             Add bot profits to SIP contributions
             €240 SIP → €280 → €320 → grows over time
             ↓
Year 10:     SIP at €50,000+ | Bot still generating monthly cash
Year 20:     SIP at €195,000 | Real financial freedom
```

---

## Safety

- Paper mode on by default — no real money until you flip the flag
- Stop-loss on every trade (3% below entry)
- Take-profit locks gains (2.5% above entry)
- Max trade size and daily trade count hard-capped in `.env`
- `.env` is gitignored — your API keys never commit

**Not financial advice.** Paper trade first. Never put in more than you can afford to lose.

---

## Resources

- [Alpaca Markets](https://alpaca.markets) — free paper + live trading API
- [Revolut](https://revolut.com) — buy SIP assets manually (VTI, SCHD, VXUS, BTC)
- [CoinGecko API](https://coingecko.com/api) — free crypto price data (no key needed)
- [Yahoo Finance API](https://finance.yahoo.com) — free stock price data (no key needed)
- [Scott Galloway — Algebra of Wealth](https://www.profgalloway.com/the-algebra-of-wealth/)
