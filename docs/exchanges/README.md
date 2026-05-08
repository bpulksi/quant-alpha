# Alpaca API Setup

This system uses [Alpaca Markets](https://alpaca.markets) — a single API for US stocks, ETFs, and crypto.

---

## Create an Account

1. Sign up at [alpaca.markets](https://alpaca.markets) (free, no deposit to paper trade)
2. Complete identity verification (~5 minutes)
3. Paper trading account is available immediately

---

## Get API Keys

### Paper Trading (start here — no real money)
1. Log in → **Paper Trading** → **API Keys** → **Generate New Key**
2. Copy **Key ID** and **Secret Key** (secret shown once only)

### Live Trading (after 4 weeks profitable paper trading)
1. Fund your account
2. **Live Trading** → **API Keys** → **Generate New Key**
3. Flip `.env`: `PAPER_TRADING=false`, `MAX_TRADE_SIZE_USD=25`

---

## Add to `.env`

```env
ALPACA_API_KEY=your_key_here
ALPACA_SECRET_KEY=your_secret_here
PAPER_TRADING=true
```

The bot auto-selects the right endpoint:
- `PAPER_TRADING=true`  → `https://paper-api.alpaca.markets`
- `PAPER_TRADING=false` → `https://api.alpaca.markets`

---

## What You Can Trade

| Asset Class | Examples |
|------------|---------|
| US Stocks | AAPL, MSFT, NVDA, TSLA, AMD |
| US ETFs | SPY, QQQ, VTI, GLD, TLT |
| Crypto | BTC, ETH, SOL, XRP, DOGE, AVAX |

---

## Safety

- Always start on paper — `PAPER_TRADING=true` for at least 4 weeks
- `.env` is gitignored — your keys never commit to GitHub
- Keep `MAX_TRADE_SIZE_USD=25` when first going live
