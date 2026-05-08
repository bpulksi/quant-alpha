/**
 * SIP Dip Alert — Buy Only at the Right Time
 * ============================================
 * Sends a Telegram message ONLY when BOTH conditions are true:
 *   Stocks: price dipped 5%+ from 120d high  AND  RSI < 40
 *   Crypto: price dipped 8%+ from 120d high  AND  RSI < 38
 *
 * Run manually:    node --env-file=.env sip_dip_alert.js
 * Run on schedule: node --env-file=.env sip_dip_alert.js --schedule
 * Preview only:    node --env-file=.env sip_dip_alert.js --dry-run
 */

import { fmt, loadPlan, loadState, saveState, sendTelegram } from "./sip_shared.js";

// Buy conditions — BOTH must be true to fire an alert
const CONDITIONS = {
  stock:  { minDipPct: 5,  maxRsi: 40 },
  crypto: { minDipPct: 8,  maxRsi: 38 },
};

// Alert tiers — triggered once conditions are met
const TIERS = [
  { pct: 20, emoji: "🔴", label: "SCREAMING BUY", multiplier: 2.0 },
  { pct: 10, emoji: "🟠", label: "STRONG DIP",    multiplier: 1.5 },
  { pct:  5, emoji: "🟡", label: "GOOD ENTRY",    multiplier: 1.0 },
];

const COOLDOWN_HOURS = 48;

const CRYPTO_SYMS = new Set([
  "BTC","ETH","SOL","BNB","XRP","ADA","DOT","LINK",
  "LTC","DOGE","AVAX","UNI","MATIC","ATOM","FIL",
]);

const COINGECKO_IDS = {
  BTC:"bitcoin", ETH:"ethereum", SOL:"solana", BNB:"binancecoin",
  XRP:"ripple", ADA:"cardano", DOT:"polkadot", LINK:"chainlink",
  LTC:"litecoin", DOGE:"dogecoin", AVAX:"avalanche-2", UNI:"uniswap",
  MATIC:"matic-network", ATOM:"cosmos", FIL:"filecoin",
};

// ─── RSI (Wilder smoothing, last 30 closes is sufficient) ────────────────────
function calcRSI(closes, period = 14) {
  const c = closes.slice(-30); // last 30 days enough for RSI accuracy
  if (c.length < period + 1) return null;
  let gains = 0, losses = 0;
  for (let i = 1; i <= period; i++) {
    const d = c[i] - c[i - 1];
    if (d >= 0) gains += d; else losses -= d;
  }
  let ag = gains / period, al = losses / period;
  for (let i = period + 1; i < c.length; i++) {
    const d = c[i] - c[i - 1];
    ag = (ag * (period - 1) + Math.max(d,  0)) / period;
    al = (al * (period - 1) + Math.max(-d, 0)) / period;
  }
  if (al === 0) return 100;
  return 100 - 100 / (1 + ag / al);
}

function maxOf(arr) { let m = arr[0]; for (const v of arr) if (v > m) m = v; return m; }
function minOf(arr) { let m = arr[0]; for (const v of arr) if (v < m) m = v; return m; }

// ─── Price fetchers ───────────────────────────────────────────────────────────
async function fetchStockData(sym) {
  try {
    const url  = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(sym)}?interval=1d&range=120d`;
    const res  = await fetch(url, { headers: { "User-Agent": "Mozilla/5.0" } });
    if (!res.ok) return null;
    const data   = await res.json();
    const closes = data?.chart?.result?.[0]?.indicators?.quote?.[0]?.close;
    if (!closes || closes.length < 16) return null;
    const valid = closes.filter(c => c != null);
    return { current: valid[valid.length-1], prev: valid[valid.length-2],
             high120d: maxOf(valid), rsi: calcRSI(valid) };
  } catch { return null; }
}

async function fetchCryptoData(sym) {
  const id = COINGECKO_IDS[sym];
  if (!id) return null;
  try {
    const url  = `https://api.coingecko.com/api/v3/coins/${id}/market_chart?vs_currency=usd&days=120&interval=daily`;
    const res  = await fetch(url, { headers: { "User-Agent": "Mozilla/5.0" } });
    if (!res.ok) return null;
    const data   = await res.json();
    const prices = (data.prices || []).map(p => p[1]).filter(Boolean);
    if (prices.length < 16) return null;
    return { current: prices[prices.length-1], prev: prices[prices.length-2],
             high120d: maxOf(prices), rsi: calcRSI(prices) };
  } catch { return null; }
}

function fetchData(sym) {
  return CRYPTO_SYMS.has(sym.toUpperCase())
    ? fetchCryptoData(sym.toUpperCase())
    : fetchStockData(sym);
}

// ─── Main scan ────────────────────────────────────────────────────────────────
async function scan(dryRun = false) {
  const plan  = loadPlan();
  const state = loadState();
  const now   = Date.now();
  const { sips = [] } = plan;

  if (sips.length === 0) {
    console.log("⚠️  No SIPs found. Add some in the dashboard first.");
    return;
  }

  console.log(`\n🔍  Scanning ${sips.length} assets — checking dip + RSI conditions...\n`);

  const alerts  = [];
  const results = await Promise.all(sips.map(async s => ({ sip: s, data: await fetchData(s.sym) })));

  for (const { sip, data } of results) {
    if (!data) { console.log(`  ⚠️  ${sip.sym.padEnd(6)} — price fetch failed`); continue; }

    const { current, prev, high120d, rsi } = data;
    const dipPct   = ((high120d - current) / high120d) * 100;
    const dayChg   = ((current - prev) / prev) * 100;
    const isCrypto = CRYPTO_SYMS.has(sip.sym.toUpperCase());
    const cond     = isCrypto ? CONDITIONS.crypto : CONDITIONS.stock;
    const dipOk    = dipPct >= cond.minDipPct;
    const rsiOk    = rsi !== null && rsi < cond.maxRsi;
    const ready    = dipOk && rsiOk;

    console.log(
      `  ${sip.sym.padEnd(6)} ${fmt(current).padStart(12)}` +
      `  dip: -${dipPct.toFixed(1).padStart(5)}% from 120d high` +
      `  RSI: ${rsi !== null ? rsi.toFixed(1).padStart(5) : "  n/a"}` +
      `  ${ready ? "✅ BUY SIGNAL" : `❌ (need dip>${cond.minDipPct}% ${dipOk?"✓":"✗"} + RSI<${cond.maxRsi} ${rsiOk?"✓":"✗"})`}`
    );

    if (!ready) continue;

    const last = state.lastAlert[sip.sym];
    if (last && (now - last.ts) / 3600000 < COOLDOWN_HOURS) {
      console.log(`     (cooldown — alerted ${((now - last.ts)/3600000).toFixed(0)}h ago)`);
      continue;
    }

    const tier = TIERS.find(t => dipPct >= t.pct);
    if (!tier) continue;

    const monthlyAmt   = sip.freq === "weekly" ? sip.amount * 4.33 : sip.amount;
    const suggestedAmt = Math.round(monthlyAmt * tier.multiplier);
    alerts.push({ sip, tier, dipPct, dayChg, current, high120d, rsi, suggestedAmt });
    state.lastAlert[sip.sym] = { ts: now, pct: tier.pct };
  }

  saveState(state);

  if (alerts.length === 0) {
    console.log("\n  Conditions not met yet — holding cash. Will check again later.\n");
    return;
  }

  console.log(`\n🔔  ${alerts.length} asset(s) ready — sending Telegram...\n`);
  alerts.sort((a, b) => b.dipPct - a.dipPct);

  const lines = [
    `💹 BUY SIGNAL — ${new Date().toLocaleDateString("en-GB", { day:"numeric", month:"long", year:"numeric" })}`,
    `Dip + RSI oversold confirmed on ${alerts.length} of your SIP asset(s):`,
    "",
  ];

  for (const { sip, tier, dipPct, dayChg, current, high120d, rsi, suggestedAmt } of alerts) {
    lines.push(
      `${tier.emoji} ${tier.label} — ${sip.sym}`,
      `   ${sip.name}`,
      `   Price:     ${fmt(current)}  (was ${fmt(high120d)} 120d ago)`,
      `   Dip:       -${dipPct.toFixed(1)}% from recent high`,
      `   RSI:       ${rsi.toFixed(1)} — oversold territory`,
      `   Today:     ${dayChg >= 0 ? "+" : ""}${dayChg.toFixed(2)}%`,
      `   👉 Buy:    €${suggestedAmt}${tier.multiplier > 1 ? " (boosted — bigger dip = bigger buy)" : ""}`,
      ...(sip.goal ? [`   🎯 Goal:   ${sip.goal}`] : []),
      "",
    );
  }

  lines.push(
    "─────────────────────────",
    "Open Revolut → search symbol → buy now.",
    "",
    "Why now? Price dipped AND RSI is oversold.",
    "This combination historically leads to recoveries.",
    "💡 You will not get a perfect bottom. This is close enough.",
  );

  const msg = lines.join("\n");

  if (dryRun) {
    console.log("DRY RUN preview:\n" + "─".repeat(50));
    console.log(msg);
    console.log("─".repeat(50) + "\n(Not sent — remove --dry-run to send for real)\n");
    return;
  }

  await sendTelegram(msg);
}

// ─── Scheduler — twice daily (9am & 6pm) ─────────────────────────────────────
function scheduleLoop() {
  console.log("⏰  SIP Dip Alert — scanning twice daily (9am & 6pm)");
  console.log("    Only alerts when dip + RSI conditions are both met.");
  console.log("    Ctrl+C to stop.\n");

  function msUntilNext() {
    const now  = new Date();
    const nowH = now.getHours() + now.getMinutes() / 60;
    const nextH = [9, 18].find(t => t > nowH) ?? 33; // 33 = next day 9am
    const next  = new Date(now);
    next.setHours(nextH % 24, 0, 0, 0);
    if (nextH >= 24) next.setDate(next.getDate() + 1);
    return next - now;
  }

  let timer;
  function tick() {
    scan(false).then(() => {
      const ms = msUntilNext();
      console.log(`\n  Next scan in ${(ms / 3600000).toFixed(1)}h\n`);
      timer = setTimeout(tick, ms);
    });
  }

  console.log(`  First scan in ${(msUntilNext() / 3600000).toFixed(1)}h`);
  timer = setTimeout(tick, msUntilNext());
  process.on("SIGINT", () => { clearTimeout(timer); process.exit(0); });
}

// ─── Entry ────────────────────────────────────────────────────────────────────
const args = process.argv.slice(2);
if      (args.includes("--schedule")) scheduleLoop();
else if (args.includes("--dry-run"))  scan(true);
else                                   scan(false).then(() => process.exit(0));
