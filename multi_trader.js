/**
 * Multi-Asset Quant Trading Bot — Alpaca Edition
 *
 * Trades crypto via Alpaca (paper or live).
 * Uses Bybit public API for market data (no geo-restrictions).
 * Runs every 2 hours via cron loop.
 * Paper mode by default — change PAPER_TRADING=false in .env to go live.
 */

import "dotenv/config";
import { readFileSync, writeFileSync, existsSync, appendFileSync } from "fs";
import { fileURLToPath } from "url";
import { execSync } from "child_process";
import crypto from "crypto";

// ─── Config ────────────────────────────────────────────────────────────────

const CRYPTO_SYMBOLS = (process.env.SYMBOL || "BTCUSDT").split(",").map(s => s.trim());
const STOCK_SYMBOLS  = (process.env.STOCK_SYMBOLS || "").split(",").map(s => s.trim()).filter(Boolean);
const SYMBOLS = [...CRYPTO_SYMBOLS, ...STOCK_SYMBOLS];

// Map internal BTCUSDT format -> Alpaca BTC/USD format (crypto only)
const SYMBOL_TO_ALPACA = {
  // ── Alpaca-tradeable crypto ────────────────────────────────────────────
  BTCUSDT:    "BTC/USD",   ETHUSDT:    "ETH/USD",   SOLUSDT:    "SOL/USD",
  XRPUSDT:    "XRP/USD",   DOGEUSDT:   "DOGE/USD",  AVAXUSDT:   "AVAX/USD",
  ADAUSDT:    "ADA/USD",   DOTUSDT:    "DOT/USD",   LINKUSDT:   "LINK/USD",
  LTCUSDT:    "LTC/USD",   UNIUSDT:    "UNI/USD",   XLMUSDT:    "XLM/USD",
  // ── Data-only crypto (monitored for research, no live orders placed) ───
  BNBUSDT:    "BNB/USD",   SUIUSDT:    "SUI/USD",   ATOMUSDT:   "ATOM/USD",
  TRXUSDT:    "TRX/USD",   INJUSDT:    "INJ/USD",   RENDERUSDT: "RENDER/USD",
  TAOUSDT:    "TAO/USD",   FILUSDT:    "FIL/USD",
  // ── Legacy mappings (removed from SYMBOL list but kept for log compat) ─
  MATICUSDT:  "MATIC/USD", NEARUSDT:   "NEAR/USD",  APTUSDT:    "APT/USD",
  ARBUSDT:    "ARB/USD",   OPUSDT:     "OP/USD",
};

// Data-only crypto: scanned for signals but no Alpaca orders placed
const DATA_ONLY_CRYPTO = new Set([
  "BNB/USD","SUI/USD","ATOM/USD","TRX/USD","INJ/USD","RENDER/USD","TAO/USD","FIL/USD",
]);

// Alpaca-supported crypto symbols
const ALPACA_CRYPTO_SUPPORTED = new Set([
  // Alpaca crypto pairs — fully tradeable
  "BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD", "DOGE/USD",
  "AVAX/USD", "ADA/USD", "DOT/USD", "LINK/USD", "LTC/USD",
  "UNI/USD", "XLM/USD",
  // Data-only (monitored but orders skipped at execution): BNB, SUI, ATOM, TRX, INJ, RENDER, TAO, FIL
]);

// Alpaca-supported stock symbols (all standard US equities and ETFs are supported)
export const ALPACA_STOCK_SYMBOLS = new Set([
  // Tech / AI
  "AAPL","MSFT","NVDA","GOOGL","META","AMZN","TSLA","AMD","PLTR","CRM","ORCL","SNOW",
  // Crypto proxies
  "COIN","MSTR","SOFI",
  // Financials
  "JPM","V","MA","GS",
  // Healthcare
  "LLY","UNH","JNJ","MRNA",
  // Energy
  "XOM","CVX",
  // Consumer
  "WMT","COST","MCD",
  // Broad ETFs (lower vol, higher sizing)
  "SPY","QQQ","IWM","GLD","TLT","XLE","XLF","XLV",
]);

// Combined support check
const ALPACA_SUPPORTED = new Set([
  ...ALPACA_CRYPTO_SUPPORTED,
  ...ALPACA_STOCK_SYMBOLS,
]);

/** Returns true if symbol is a plain stock ticker (no USDT suffix, exists in env stock list) */
export function isStock(symbol) {
  const s = symbol.toUpperCase();
  // Match env list OR known Alpaca stock set — handles new .env additions automatically
  return ALPACA_STOCK_SYMBOLS.has(s) || STOCK_SYMBOLS.includes(s);
}

/** Get Alpaca symbol string for a given internal symbol */
function toAlpacaSymbol(symbol) {
  if (isStock(symbol)) return symbol.toUpperCase();       // AAPL -> AAPL
  return SYMBOL_TO_ALPACA[symbol] || null;                 // BTCUSDT -> BTC/USD
}

const CONFIG = {
  symbols: SYMBOLS,
  timeframe: process.env.TIMEFRAME || "15",
  portfolioValue: parseFloat(process.env.PORTFOLIO_VALUE_USD || "1000"),
  maxTradeSizeUSD: parseFloat(process.env.MAX_TRADE_SIZE_USD || "10"),
  maxTradesPerDay: parseInt(process.env.MAX_TRADES_PER_DAY || "5"),
  paperTrading: process.env.PAPER_TRADING !== "false",
  alpaca: {
    apiKey: process.env.ALPACA_API_KEY,
    secretKey: process.env.ALPACA_SECRET_KEY,
    baseUrl: process.env.PAPER_TRADING !== "false"
      ? "https://paper-api.alpaca.markets"
      : "https://api.alpaca.markets",
  },
  pythonPath: "C:/Users/Ripple Nova/anaconda3/python.exe",
  quantEngine: "C:/Users/Ripple Nova/claude-tradingview-bot/quant_engine_v3.py",
  botDir: "C:/Users/Ripple Nova/claude-tradingview-bot",
};

const LOG_FILE = "multi-trade-log.json";
const CSV_FILE = "trades.csv";

// ─── Logging ───────────────────────────────────────────────────────────────

function loadLog() {
  if (!existsSync(LOG_FILE)) return { trades: [] };
  return JSON.parse(readFileSync(LOG_FILE, "utf8"));
}

function saveLog(log) {
  writeFileSync(LOG_FILE, JSON.stringify(log, null, 2));
}

function getSymbolCooldown(log, symbol, cooldownHours = 4) {
  // Returns {onCooldown: bool, reason: str} — blocks retrades after a loss
  const now = Date.now();
  const cutoff = now - cooldownHours * 60 * 60 * 1000;
  // Find last closed trade on this symbol
  const trades = log.trades
    .filter(t => t.symbol === symbol && t.orderPlaced && new Date(t.timestamp).getTime() > cutoff)
    .sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));
  if (trades.length === 0) return { onCooldown: false };
  const last = trades[0];
  // Check if the position was a loss (only relevant for closed pairs)
  // Simpler heuristic: if 2+ losing trades in last cooldownHours → cooldown
  const losses = trades.filter(t => {
    const sig = t.signal?.action;
    // Can't know PnL in real-time from log alone, so use confidence < 0.62 as proxy for bad trade
    return sig !== "HOLD" && (t.signal?.confidence || 0) < 0.55;
  });
  if (losses.length >= 2) {
    return { onCooldown: true, reason: `${losses.length} low-confidence trades in last ${cooldownHours}h` };
  }
  return { onCooldown: false };
}

function countTodaysTrades(log) {
  const today = new Date().toISOString().slice(0, 10);
  return log.trades.filter(
    (t) => t.timestamp?.startsWith(today) && t.orderPlaced
  ).length;
}

// ─── CSV Logging ───────────────────────────────────────────────────────────

const CSV_HEADERS = "Date,Time (UTC),Exchange,Symbol,Side,Quantity,Price,Total USD,Fee (est.),Net Amount,Order ID,Mode,Regime,ML Confidence,Notes";

function initCsv() {
  if (!existsSync(CSV_FILE)) {
    writeFileSync(CSV_FILE, CSV_HEADERS + "\n");
  }
}

function writeTradeCsv(entry) {
  const now = new Date(entry.timestamp);
  const date = now.toISOString().slice(0, 10);
  const time = now.toISOString().slice(11, 19);

  let side = "", qty = "", total = "", fee = "", net = "", orderId = "", mode = "", notes = "";

  if (!entry.shouldTrade) {
    mode = "BLOCKED";
    orderId = "BLOCKED";
    notes = `Signal: ${entry.signal?.action || 'HOLD'} | ${entry.signal?.reason || 'No signal'}`;
  } else if (entry.paperTrading) {
    side = entry.signal?.action || "BUY";
    qty = (entry.tradeSize / entry.price).toFixed(6);
    total = entry.tradeSize.toFixed(2);
    fee = (entry.tradeSize * 0.001).toFixed(4);
    net = (entry.tradeSize - parseFloat(fee)).toFixed(2);
    orderId = entry.orderId || "";
    mode = "PAPER";
    notes = entry.signal?.reason || "All conditions met";
  } else {
    side = entry.signal?.action || "BUY";
    qty = (entry.tradeSize / entry.price).toFixed(6);
    total = entry.tradeSize.toFixed(2);
    fee = (entry.tradeSize * 0.001).toFixed(4);
    net = (entry.tradeSize - parseFloat(fee)).toFixed(2);
    orderId = entry.orderId || "";
    mode = "LIVE";
    notes = entry.error ? `Error: ${entry.error}` : (entry.signal?.reason || "All conditions met");
  }

  const row = [
    date, time, "Alpaca", entry.symbol, side, qty,
    entry.price?.toFixed(2) || "", total, fee, net, orderId, mode,
    entry.regime || "", entry.mlConfidence || "",
    `"${notes}"`,
  ].join(",");

  appendFileSync(CSV_FILE, row + "\n");
}

// ─── Quant Engine Integration ──────────────────────────────────────────────

function getQuantSignal(symbol) {
  try {
    const output = execSync(
      `"${CONFIG.pythonPath}" "${CONFIG.quantEngine}" signal ${symbol}`,
      { timeout: 60000, encoding: "utf8" }
    );
    return JSON.parse(output);
  } catch (e) {
    console.log(`  ⚠️  Quant engine error for ${symbol}: ${e.message.slice(0, 120)}`);
    return null;
  }
}

// ─── Research Subagent Integration ────────────────────────────────────────

function getResearchSignal(symbol, quant) {
  if (process.env.ENABLE_RESEARCH !== "true") return null;
  try {
    const quantData = JSON.stringify({
      confidence:   quant.final_signal.confidence,
      action:       quant.final_signal.action,
      volume_ratio: quant.indicators.volume_ratio || 1.0,
    }).replace(/"/g, '\\"');
    const researchPath = `${CONFIG.botDir || "."}/research_agent.py`;
    const output = execSync(
      `"${CONFIG.pythonPath}" "${researchPath}" signal ${symbol} --quant-data "${quantData}"`,
      { timeout: 45000, encoding: "utf8" }
    );
    // Parse only last JSON line (stdout may contain info prints)
    const lines = output.trim().split("\n");
    const jsonLine = lines.reverse().find(l => l.trim().startsWith("{"));
    return jsonLine ? JSON.parse(jsonLine) : null;
  } catch (e) {
    console.log(`  ⚠️  Research signal error for ${symbol}: ${e.message.slice(0, 100)}`);
    return null;
  }
}

// ─── Stock Signal Builder (research-only, no quant engine) ────────────────
// For stocks the quant engine (trained on crypto OHLCV) is not applicable.
// We build a signal purely from TradingAgents + news via research_agent.py.
// The result is shaped identically to quant engine output so the rest of
// the loop logic (confidence gates, sizing, stop/TP) is reused unchanged.

function getStockSignal(symbol) {
  try {
    // Fetch live price from Alpaca market data
    const priceOut = execSync(
      `"${CONFIG.pythonPath}" "${CONFIG.botDir}/stock_price_fetcher.py" ${symbol}`,
      { timeout: 10000, encoding: "utf8" }
    );
    const priceData = JSON.parse(priceOut.trim().split("\n").pop());
    const price = priceData.price || 0;

    if (!price || price <= 0) {
      console.log(`  [STOCK] Could not fetch price for ${symbol}`);
      return null;
    }

    // Run research agent to get TA + news score
    const researchOut = execSync(
      `"${CONFIG.pythonPath}" "${CONFIG.botDir}/research_agent.py" signal ${symbol}`,
      { timeout: 90000, encoding: "utf8" }  // TA can take ~3 min for stocks
    );
    const lines = researchOut.trim().split("\n");
    const jsonLine = lines.reverse().find(l => l.trim().startsWith("{"));
    if (!jsonLine) return null;
    const research = JSON.parse(jsonLine);

    // Map research opportunity_score + TA decision -> quant-compatible signal
    const oppScore = research.opportunity_score || 0.5;
    const taDecision = (research.ta_decision || "hold").toLowerCase();

    let action = "HOLD";
    let confidence = oppScore;
    if (taDecision.includes("buy")  && oppScore > 0.55) action = "BUY";
    if (taDecision.includes("sell") && oppScore > 0.55) action = "SELL";

    console.log(`  [STOCK] ${symbol} price=$${price.toFixed(2)} ta=${taDecision} opp=${oppScore.toFixed(3)} -> ${action}`);

    // Return quant-engine-shaped object
    return {
      regime:       { regime: "STOCK", direction: action === "BUY" ? "up" : action === "SELL" ? "down" : "flat", adx: 0 },
      indicators:   { price, volume_ratio: 1.0, rsi_14: 50, z_score: 0, macd_hist: 0, bb_pct_b: 0.5, buy_pressure: 0.5 },
      final_signal: { action, confidence, reason: `TA:${taDecision} news:${research.news_score?.toFixed(2)} opp:${oppScore.toFixed(3)}` },
      rule_signal:  { action, confidence, reason: "" },
      ml_signal:    { prediction: action, probability: confidence, predicted_return_pct: 0 },
      strategy:     "STOCK_RESEARCH",
      _research:    research,  // carry forward so research blend block can use it
    };
  } catch (e) {
    console.log(`  [STOCK] Signal error for ${symbol}: ${e.message.slice(0, 120)}`);
    return null;
  }
}

// ─── Alpaca Order Execution ────────────────────────────────────────────────

async function placeAlpacaOrder(symbol, side, sizeUSD, alpacaSymbol) {
  if (!CONFIG.alpaca.apiKey || !CONFIG.alpaca.secretKey) {
    throw new Error("Alpaca API keys not configured in .env (ALPACA_API_KEY / ALPACA_SECRET_KEY)");
  }

  if (!ALPACA_SUPPORTED.has(alpacaSymbol)) {
    throw new Error(`${alpacaSymbol} not supported on Alpaca`);
  }

  // Stocks use "day" TIF (market hours only); crypto uses "gtc" (24/7)
  const tif = isStock(symbol) ? "day" : "gtc";

  const body = JSON.stringify({
    symbol: alpacaSymbol,
    notional: sizeUSD.toFixed(2),    // USD amount (fractional order)
    side: side.toLowerCase(),          // "buy" or "sell"
    type: "market",
    time_in_force: tif,
  });

  const res = await fetch(`${CONFIG.alpaca.baseUrl}/v2/orders`, {
    method: "POST",
    headers: {
      "APCA-API-KEY-ID": CONFIG.alpaca.apiKey,
      "APCA-API-SECRET-KEY": CONFIG.alpaca.secretKey,
      "Content-Type": "application/json",
    },
    body,
  });

  const data = await res.json();
  if (!res.ok) {
    throw new Error(`Alpaca order failed: ${data.message || JSON.stringify(data)}`);
  }
  return { orderId: data.id, alpacaOrder: data };
}

// ─── Trailing Stop Order (replaces fixed stop — locks in gains as price rises) ─

async function placeAlpacaTrailingStop(alpacaSymbol, qty, trailPercent = 1.5) {
  if (!CONFIG.alpaca.apiKey || !CONFIG.alpaca.secretKey) return null;
  if (!ALPACA_SUPPORTED.has(alpacaSymbol)) return null;
  const tif = isStock(alpacaSymbol) ? "day" : "gtc";
  const body = JSON.stringify({
    symbol: alpacaSymbol, qty: qty.toFixed(8), side: "sell",
    type: "trailing_stop", time_in_force: tif,
    trail_percent: trailPercent.toFixed(2),
  });
  const res = await fetch(`${CONFIG.alpaca.baseUrl}/v2/orders`, {
    method: "POST",
    headers: {
      "APCA-API-KEY-ID": CONFIG.alpaca.apiKey,
      "APCA-API-SECRET-KEY": CONFIG.alpaca.secretKey,
      "Content-Type": "application/json",
    }, body,
  });
  const data = await res.json();
  if (!res.ok) { console.log(`  ⚠️  Trailing stop failed: ${data.message}`); return null; }
  console.log(`  🔄 TRAILING STOP @ ${trailPercent}% trail placed`);
  return { trailingStopId: data.id };
}

// ─── Stop-Loss Order ───────────────────────────────────────────────────────

async function placeAlpacaStopOrder(alpacaSymbol, qty, stopPrice) {
  if (!CONFIG.alpaca.apiKey || !CONFIG.alpaca.secretKey) return null;
  if (!ALPACA_SUPPORTED.has(alpacaSymbol)) return null;
  const tif = isStock(alpacaSymbol) ? "day" : "gtc";
  const body = JSON.stringify({
    symbol: alpacaSymbol,
    qty: qty.toFixed(8),
    side: "sell",
    type: "stop",
    time_in_force: tif,
    stop_price: stopPrice.toFixed(6),
  });
  const res = await fetch(`${CONFIG.alpaca.baseUrl}/v2/orders`, {
    method: "POST",
    headers: {
      "APCA-API-KEY-ID": CONFIG.alpaca.apiKey,
      "APCA-API-SECRET-KEY": CONFIG.alpaca.secretKey,
      "Content-Type": "application/json",
    },
    body,
  });
  const data = await res.json();
  if (!res.ok) { console.log(`  ⚠️  Stop order failed: ${data.message || JSON.stringify(data)}`); return null; }
  console.log(`  🛑 STOP ORDER PLACED @ $${stopPrice.toFixed(6)} (id: ${data.id})`);
  return { stopOrderId: data.id };
}

// ─── Take-Profit Order ─────────────────────────────────────────────────────

async function placeAlpacaTakeProfitOrder(alpacaSymbol, qty, limitPrice) {
  if (!CONFIG.alpaca.apiKey || !CONFIG.alpaca.secretKey) return null;
  if (!ALPACA_SUPPORTED.has(alpacaSymbol)) return null;
  const tif = isStock(alpacaSymbol) ? "day" : "gtc";
  const body = JSON.stringify({
    symbol: alpacaSymbol,
    qty: qty.toFixed(8),
    side: "sell",
    type: "limit",
    time_in_force: tif,
    limit_price: limitPrice.toFixed(6),
  });
  const res = await fetch(`${CONFIG.alpaca.baseUrl}/v2/orders`, {
    method: "POST",
    headers: {
      "APCA-API-KEY-ID": CONFIG.alpaca.apiKey,
      "APCA-API-SECRET-KEY": CONFIG.alpaca.secretKey,
      "Content-Type": "application/json",
    },
    body,
  });
  const data = await res.json();
  if (!res.ok) { console.log(`  ⚠️  TP order failed: ${data.message || JSON.stringify(data)}`); return null; }
  console.log(`  🎯 TAKE-PROFIT ORDER PLACED @ $${limitPrice.toFixed(6)} (id: ${data.id})`);
  return { tpOrderId: data.id };
}

// ─── Telegram Notification ─────────────────────────────────────────────────

function sendTelegram(message) {
  try {
    // Write message to a temp file to avoid shell quoting issues
    const tmpFile = "telegram_msg_tmp.txt";
    writeFileSync(tmpFile, message, "utf8");
    const out = execSync(
      `"${CONFIG.pythonPath}" "${CONFIG.quantEngine.replace('quant_engine_v3.py','telegram_notify.py')}" send_file ${tmpFile}`,
      { timeout: 15000, encoding: "utf8" }
    );
    console.log(`  [Telegram] ${out.trim()}`);
  } catch (e) {
    console.log(`  [Telegram] Error: ${e.message.slice(0, 60)}`);
  }
}

// ─── Main ──────────────────────────────────────────────────────────────────

function getDailyPnL(log) {
  // Estimate today's realised P&L from closed pairs in log
  // Simple proxy: sum of (tradeSize * mlPredictedReturn%) for completed trades today
  const today = new Date().toISOString().slice(0, 10);
  return log.trades
    .filter(t => t.timestamp?.startsWith(today) && t.orderPlaced)
    .reduce((sum, t) => sum + (t.signal?.pnl_realised || 0), 0);
}

function getConsecutiveLosses(log) {
  // Count recent ordered trades in reverse — how many losses in a row?
  const ordered = log.trades.filter(t => t.orderPlaced).slice(-10).reverse();
  let streak = 0;
  for (const t of ordered) {
    if ((t.pnl_realised || 0) < 0) streak++;
    else break;
  }
  return streak;
}

async function run() {
  initCsv();
  const log = loadLog();
  const todaysTrades = countTodaysTrades(log);

  // ── Market hours check (for stock gating) ────────────────────────────────
  let marketOpen = false;
  try {
    const clockOut = execSync(
      `"${CONFIG.pythonPath}" "${CONFIG.botDir}/stock_price_fetcher.py" --is-market-open`,
      { timeout: 8000, encoding: "utf8" }
    );
    const clock = JSON.parse(clockOut.trim().split("\n").pop());
    marketOpen = !!clock.is_open;
  } catch (e) {
    // Fallback: estimate from UTC time (NYSE 9:30-16:00 ET = 14:30-21:00 UTC)
    const h = new Date().getUTCHours();
    const d = new Date().getUTCDay();
    marketOpen = d >= 1 && d <= 5 && h >= 14 && h < 21;
  }

  const mode = CONFIG.paperTrading ? "PAPER (Alpaca $100K)" : "LIVE (Alpaca)";
  console.log("===================================================================");
  console.log("  Multi-Asset Quant Trading Bot -- Alpaca Edition");
  console.log(`  ${new Date().toISOString()}`);
  console.log(`  Mode: ${mode}`);
  console.log(`  Crypto: ${CRYPTO_SYMBOLS.length} assets | Stocks: ${STOCK_SYMBOLS.length} assets | Market: ${marketOpen ? "OPEN" : "CLOSED"}`);
  console.log(`  Trades today: ${todaysTrades}/${CONFIG.maxTradesPerDay}`);
  console.log("===================================================================");

  if (todaysTrades >= CONFIG.maxTradesPerDay) {
    console.log("\n⚠️  Daily trade limit reached. Stopping.");
    return;
  }

  // ── Daily Drawdown Circuit Breaker ────────────────────────────────────────
  // If portfolio drops >3% today, stop all trading for the rest of the day
  const MAX_DAILY_DRAWDOWN_PCT = 3.0;
  const portfolioValue = CONFIG.portfolioValue;
  const dailyLossLimit = portfolioValue * (MAX_DAILY_DRAWDOWN_PCT / 100);
  const todayLosses = log.trades
    .filter(t => t.timestamp?.startsWith(new Date().toISOString().slice(0, 10)) && t.orderPlaced)
    .reduce((sum, t) => sum + Math.min(t.pnl_realised || 0, 0), 0);
  if (Math.abs(todayLosses) > dailyLossLimit) {
    console.log(`\n🛑 DAILY DRAWDOWN LIMIT HIT — EUR${Math.abs(todayLosses).toFixed(2)} lost today (limit: EUR${dailyLossLimit.toFixed(2)}). Stopping.`);
    sendTelegram(`🛑 *Circuit Breaker Triggered*\nDaily loss EUR${Math.abs(todayLosses).toFixed(2)} exceeded limit EUR${dailyLossLimit.toFixed(2)}.\nTrading paused for today.`);
    return;
  }

  // ── Consecutive Loss Tilt Guard ────────────────────────────────────────────
  const consecLosses = getConsecutiveLosses(log);
  if (consecLosses >= 4) {
    console.log(`\n⚠️  TILT GUARD — ${consecLosses} consecutive losses detected. Position sizes halved.`);
  }

  const scanSummary = [];

  for (const symbol of CONFIG.symbols) {
    console.log(`\n-- ${symbol} -------------------------------------------------------`);

    // Gate stocks behind market hours
    if (isStock(symbol) && !marketOpen) {
      console.log(`  [STOCK] Market closed -- skipping ${symbol}`);
      continue;
    }

    const alpacaSymbol = toAlpacaSymbol(symbol);
    if (!alpacaSymbol) {
      console.log(`  Skipping -- no Alpaca mapping for ${symbol}`);
      continue;
    }

    // Per-symbol cooldown check — don't retry a symbol after repeated bad trades
    const cooldown = getSymbolCooldown(log, symbol);
    if (cooldown.onCooldown) {
      console.log(`  ⏸️  COOLDOWN — ${symbol} paused: ${cooldown.reason}`);
      continue;
    }

    // Get signal — quant engine for crypto, research-only signal for stocks
    let quant = null;
    if (isStock(symbol)) {
      quant = getStockSignal(symbol);
    } else {
      quant = getQuantSignal(symbol);
    }
    if (!quant) {
      console.log("  Skipping -- no signal data");
      continue;
    }

    const { regime, indicators, final_signal, rule_signal, ml_signal, strategy } = quant;

    // Display
    console.log(`  Alpaca:    ${alpacaSymbol}`);
    console.log(`  Price:     $${indicators.price?.toLocaleString()}`);
    console.log(`  Regime:    ${regime.regime} (${regime.direction}) | ADX: ${regime.adx}`);
    console.log(`  Strategy:  ${strategy}`);
    if (!isStock(symbol)) {
      console.log(`  RSI(14):   ${indicators.rsi_14} | Z-score: ${indicators.z_score}`);
      console.log(`  MACD Hist: ${indicators.macd_hist} | BB%B: ${indicators.bb_pct_b}`);
      console.log(`  Volume:    ${indicators.volume_ratio}x avg | Buy pressure: ${(indicators.buy_pressure * 100).toFixed(0)}%`);
      console.log(`  Rule:      ${rule_signal.action} (${(rule_signal.confidence * 100).toFixed(0)}%) ${rule_signal.reason ? '-- ' + rule_signal.reason : ''}`);
      console.log(`  ML:        ${ml_signal.prediction} (${(ml_signal.probability * 100).toFixed(0)}%)`);
    }
    console.log(`  >> SIGNAL: ${final_signal.action} (${(final_signal.confidence * 100).toFixed(0)}% confidence)`);

    // Research subagent blending:
    //   Stocks: research already baked into signal via getStockSignal()
    //   Crypto: call research agent separately (opt-in via ENABLE_RESEARCH=true)
    const research = isStock(symbol) ? (quant._research || null) : getResearchSignal(symbol, quant);
    let effectiveConfidence = final_signal.confidence;
    if (research) {
      const boost = (research.opportunity_score - 0.5) * 0.20;  // max ±0.10
      effectiveConfidence = Math.max(0, Math.min(0.95, effectiveConfidence + boost));
      console.log(`  Research:  score=${research.opportunity_score.toFixed(3)} news=${research.news_score >= 0 ? '+' : ''}${research.news_score.toFixed(2)} arb=${research.arbitrage_net_pct.toFixed(3)}% → conf ${(effectiveConfidence * 100).toFixed(0)}%`);
    }

    // Price floor -- crypto only (coins under $1 have spread/rounding issues)
    const MIN_PRICE = 1.0;
    if (!isStock(symbol) && indicators.price < MIN_PRICE) {
      console.log(`\n  SKIPPED -- price $${indicators.price} below minimum $${MIN_PRICE} (spread risk)`);
      continue;
    }

    // ML sanity gate -- crypto only (stocks use research score gate instead)
    if (!isStock(symbol) && ml_signal.probability < 0.60 && final_signal.action !== "HOLD") {
      console.log(`\n  SKIPPED -- ML probability ${(ml_signal.probability * 100).toFixed(0)}% < 60% (noise zone)`);
      continue;
    }

    const shouldTrade = final_signal.action !== "HOLD" && effectiveConfidence > 0.62;

    // Dynamic position sizing — Kelly-inspired tiers scaled to 100k portfolio
    // Tier 1 (highest conf): 6% = $6,000  — very high conviction signal
    // Tier 2 (good conf):    4% = $4,000  — solid signal
    // Tier 3 (base):         3% = $3,000  — minimum qualifying signal
    // ETF/sector positions get +1% size boost (lower volatility)
    const ETF_SET = new Set(["SPY","QQQ","IWM","GLD","TLT","XLE","XLF","XLV"]);
    let tradeSizePct = 0.03;   // 3% base = $3,000
    if (effectiveConfidence > 0.82 && ml_signal.probability > 0.72) tradeSizePct = 0.06;  // $6,000
    else if (effectiveConfidence > 0.74 && ml_signal.probability > 0.66) tradeSizePct = 0.04;  // $4,000
    // ETF boost: more size on lower-vol broad market instruments
    if (ETF_SET.has(alpacaSymbol)) tradeSizePct = Math.min(tradeSizePct + 0.01, 0.07);
    // Research boost: high opportunity score → +0.5% size
    if (research && research.opportunity_score > 0.70) tradeSizePct = Math.min(tradeSizePct + 0.005, 0.07);
    // Tilt guard: halve size after 4+ consecutive losses
    if (consecLosses >= 4) tradeSizePct *= 0.5;
    const tradeSize = Math.max(Math.min(CONFIG.portfolioValue * tradeSizePct, CONFIG.maxTradeSizeUSD), 10.0);
    console.log(`  Size:      $${tradeSize.toFixed(0)} (${(tradeSizePct*100).toFixed(0)}% — conf=${(effectiveConfidence*100).toFixed(0)}% mlProb=${(ml_signal.probability*100).toFixed(0)}%)`);

    scanSummary.push({
      symbol, alpacaSymbol,
      price: indicators.price,
      action: final_signal.action,
      confidence: final_signal.confidence,
      regime: regime.regime,
      ml_pred: ml_signal.predicted_return_pct,
      reason: rule_signal.reason || "",
      traded: false,
    });

    const logEntry = {
      timestamp: new Date().toISOString(),
      symbol,
      alpacaSymbol,
      price: indicators.price,
      regime: regime.regime,
      direction: regime.direction,
      strategy,
      signal: final_signal,
      ruleSignal: rule_signal,
      mlSignal: ml_signal,
      mlConfidence: ml_signal.probability,
      indicators,
      shouldTrade,
      tradeSize,
      orderPlaced: false,
      orderId: null,
      paperTrading: CONFIG.paperTrading,
      researchScore:    research ? research.opportunity_score : null,
      newsScore:        research ? research.news_score : null,
      effectiveConfidence: research ? effectiveConfidence : null,
    };

    if (!shouldTrade) {
      console.log(`\n  🚫 NO TRADE — ${final_signal.action === 'HOLD' ? 'No clear signal' : 'Low confidence'}`);
    } else if (countTodaysTrades(log) >= CONFIG.maxTradesPerDay) {
      console.log(`\n  ⚠️  SKIPPED — daily limit reached`);
    } else {
      console.log(`\n  ✅ TRADE SIGNAL CONFIRMED — ${final_signal.action} $${tradeSize.toFixed(2)} of ${alpacaSymbol}`);

      if (CONFIG.paperTrading) {
        console.log(`  📋 PAPER TRADE — would ${final_signal.action} ${alpacaSymbol} ~$${tradeSize.toFixed(2)} at $${indicators.price}`);
        logEntry.orderPlaced = true;
        logEntry.orderId = `PAPER-${Date.now()}`;
        if (final_signal.action === "BUY") {
          logEntry.stopPrice = indicators.price * 0.97;
          logEntry.tpPrice   = indicators.price * 1.025;
          console.log(`  🛑 Paper stop: $${logEntry.stopPrice.toFixed(4)} | 🎯 Paper TP: $${logEntry.tpPrice.toFixed(4)}`);
        }
        scanSummary[scanSummary.length - 1].traded = true;
      } else {
        if (DATA_ONLY_CRYPTO.has(alpacaSymbol)) {
          console.log(`  📊 DATA-ONLY — ${alpacaSymbol} monitored for research signals only (no live order)`);
        } else if (!ALPACA_SUPPORTED.has(alpacaSymbol)) {
          console.log(`  ⚠️  SKIPPED — ${alpacaSymbol} not in Alpaca supported list`);
        } else {
          const side = final_signal.action === "BUY" ? "BUY" : "SELL";
          console.log(`  🔴 PLACING LIVE ${side} ORDER — $${tradeSize.toFixed(2)} ${alpacaSymbol}`);
          try {
            const order = await placeAlpacaOrder(symbol, side, tradeSize, alpacaSymbol);
            logEntry.orderPlaced = true;
            logEntry.orderId = order.orderId;
            console.log(`  ✅ ORDER PLACED — ${order.orderId}`);
            scanSummary[scanSummary.length - 1].traded = true;

            // Trailing stop (1.5% trail) + take-profit (2.5% above entry)
            if (side === "BUY") {
              const tpPrice = indicators.price * 1.025;
              const qty = tradeSize / indicators.price;
              logEntry.tpPrice = tpPrice;
              // Trailing stop: locks in gains as price rises (beats fixed -3% stop)
              const trailResult = await placeAlpacaTrailingStop(alpacaSymbol, qty, 1.5);
              if (trailResult) logEntry.trailingStopId = trailResult.trailingStopId;
              // Fixed stop fallback at -3% in case trailing not supported
              const stopPrice = indicators.price * 0.97;
              logEntry.stopPrice = stopPrice;
              if (!trailResult) {
                const stopResult = await placeAlpacaStopOrder(alpacaSymbol, qty, stopPrice);
                if (stopResult) logEntry.stopOrderId = stopResult.stopOrderId;
              }
              const tpResult = await placeAlpacaTakeProfitOrder(alpacaSymbol, qty, tpPrice);
              if (tpResult) logEntry.tpOrderId = tpResult.tpOrderId;
            }
          } catch (err) {
            console.log(`  ❌ ORDER FAILED — ${err.message}`);
            logEntry.error = err.message;
          }
        }
      }
    }

    log.trades.push(logEntry);
    writeTradeCsv(logEntry);
  }

  // ─── Telegram Summary ──────────────────────────────────────────────────
  const buys = scanSummary.filter(s => s.action === "BUY" && s.confidence > 0.62);
  const sells = scanSummary.filter(s => s.action === "SELL" && s.confidence > 0.62);

  let tgMsg = `*Quant Bot Scan — ${new Date().toISOString().slice(0, 16)} UTC*\n`;
  tgMsg += `Mode: ${CONFIG.paperTrading ? "PAPER" : "LIVE"} | Assets: ${CONFIG.symbols.length}\n\n`;

  if (buys.length > 0) {
    tgMsg += `*🟢 BUY Signals:*\n`;
    for (const s of buys) {
      tgMsg += `  \`${s.alpacaSymbol}\` @ $${s.price?.toLocaleString()} (${(s.confidence * 100).toFixed(0)}% conf, ${s.ml_pred > 0 ? "+" : ""}${s.ml_pred?.toFixed(2)}%)\n`;
      if (s.reason) tgMsg += `    _${s.reason}_\n`;
    }
  }

  if (sells.length > 0) {
    tgMsg += `\n*🔴 SELL Signals:*\n`;
    for (const s of sells) {
      tgMsg += `  \`${s.alpacaSymbol}\` @ $${s.price?.toLocaleString()} (${(s.confidence * 100).toFixed(0)}% conf, ${s.ml_pred > 0 ? "+" : ""}${s.ml_pred?.toFixed(2)}%)\n`;
      if (s.reason) tgMsg += `    _${s.reason}_\n`;
    }
  }

  if (buys.length === 0 && sells.length === 0) {
    tgMsg += `No actionable signals this cycle.\n`;
    // Show top movers
    const movers = [...scanSummary].filter(s => s.price).sort((a, b) => Math.abs(b.ml_pred || 0) - Math.abs(a.ml_pred || 0)).slice(0, 5);
    if (movers.length > 0) {
      tgMsg += `\n*Top predicted movers:*\n`;
      for (const s of movers) {
        tgMsg += `  \`${s.alpacaSymbol}\` ${s.ml_pred > 0 ? "+" : ""}${s.ml_pred?.toFixed(2)}% | ${s.regime}\n`;
      }
    }
  }

  tgMsg += `\nTrades today: ${countTodaysTrades(log)}/${CONFIG.maxTradesPerDay}`;

  sendTelegram(tgMsg);

  // ─── Sync portfolio tracker ────────────────────────────────────────────
  try {
    execSync(
      `"${CONFIG.pythonPath}" "${CONFIG.quantEngine.replace('quant_engine_v3.py','portfolio_tracker.py')}" report`,
      { timeout: 15000, encoding: "utf8", stdio: "pipe" }
    );
  } catch (e) {
    // non-fatal
  }

  saveLog(log);
  writeFileSync("scan_results.json", JSON.stringify(scanSummary, null, 2));
  console.log("\n═══════════════════════════════════════════════════════════");
  console.log(`  Log saved → ${LOG_FILE}`);
  console.log(`  CSV saved → ${CSV_FILE}`);
  console.log("═══════════════════════════════════════════════════════════\n");
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  run().catch(console.error);
}
