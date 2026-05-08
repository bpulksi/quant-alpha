# Windows Setup Guide

## Prerequisites

| Tool | Version | Check |
|------|---------|-------|
| Node.js | 18+ | `node --version` |
| Python | 3.9+ | `python --version` |
| Git | any | `git --version` |

---

## 1. Clone and install

```powershell
git clone https://github.com/bpulksi/quant-alpha.git
cd quant-alpha
npm install
pip install pandas numpy scikit-learn ta requests
```

## 2. Configure environment

```powershell
Copy-Item .env.example .env
notepad .env
```

Fill in:
- `ALPACA_API_KEY` + `ALPACA_SECRET_KEY` — from [alpaca.markets](https://alpaca.markets) → Paper Trading → API Keys
- `TELEGRAM_BOT_TOKEN` — message [@BotFather](https://t.me/BotFather) → `/newbot`
- `TELEGRAM_CHAT_ID` — message [@userinfobot](https://t.me/userinfobot)

## 3. Train ML models (first time only, ~10 min)

```powershell
python quant_engine_v3.py train-all
```

## 4. Run

```powershell
# Trading bot + dashboard at http://localhost:3000
node --env-file=.env server.js

# SIP dip alert — preview only
node --env-file=.env sip_dip_alert.js --dry-run

# SIP monthly reminder — test message
node --env-file=.env sip_notifier.js --test
```
