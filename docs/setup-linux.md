# Linux Setup Guide

## Prerequisites

```bash
# Node.js 18+
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt-get install -y nodejs

# Python 3.9+
sudo apt-get install python3 python3-pip

# Git
sudo apt-get install git
```

---

## 1. Clone and install

```bash
git clone https://github.com/bpulksi/quant-alpha.git
cd quant-alpha
npm install
pip3 install pandas numpy scikit-learn ta requests
```

## 2. Configure environment

```bash
cp .env.example .env
nano .env
```

Fill in:
- `ALPACA_API_KEY` + `ALPACA_SECRET_KEY` — from [alpaca.markets](https://alpaca.markets) → Paper Trading → API Keys
- `TELEGRAM_BOT_TOKEN` — message [@BotFather](https://t.me/BotFather) → `/newbot`
- `TELEGRAM_CHAT_ID` — message [@userinfobot](https://t.me/userinfobot)

## 3. Train ML models (first time only, ~10 min)

```bash
python3 quant_engine_v3.py train-all
```

## 4. Run

```bash
# Trading bot + dashboard at http://localhost:3000
node --env-file=.env server.js

# SIP dip alert — preview only
node --env-file=.env sip_dip_alert.js --dry-run

# SIP monthly reminder — test message
node --env-file=.env sip_notifier.js --test
```

## 5. Run as a background service (optional)

```bash
# Install pm2
npm install -g pm2

# Start the trading bot
pm2 start "node --env-file=.env server.js" --name quant-alpha

# Auto-start on reboot
pm2 startup
pm2 save
```
