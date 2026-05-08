/**
 * SIP Notifier — Monthly Telegram Investment Reminder
 * ====================================================
 * Reads sip_plan.json (exported from SIP dashboard) and sends a
 * beautifully formatted Telegram message telling you exactly what
 * to buy this month on Revolut / Trade Republic / any broker.
 *
 * Run manually:    node --env-file=.env sip_notifier.js
 * Run on schedule: node --env-file=.env sip_notifier.js --schedule
 * Test message:    node --env-file=.env sip_notifier.js --test
 */

import { fmt, monthlyAmount, loadPlan, sendTelegram } from "./sip_shared.js";

// ─── Build Telegram message ───────────────────────────────────────────────────
function buildMessage(plan, isTest = false) {
  const now       = new Date();
  const monthName = now.toLocaleString("en-US", { month: "long" });
  const year      = now.getFullYear();

  const catOrder  = ["core", "dividend", "moat", "growth", "hedge", "intl", "crypto"];
  const catLabels = {
    core:     "📊 Core Index",
    dividend: "💰 Dividend",
    moat:     "🏰 Wide Moat",
    growth:   "🚀 Growth",
    hedge:    "🛡️ Hedges",
    intl:     "🌍 International",
    crypto:   "₿ Crypto",
  };

  const { sips = [], holdings = [], totalInvested = 0 } = plan;

  // Filter to due-this-month SIPs
  const due = sips.filter(s => {
    if (s.freq === "monthly" || s.freq === "weekly") return true;
    if (s.freq === "quarterly") {
      const start      = new Date(s.startDate);
      const monthsDiff = (now.getFullYear() - start.getFullYear()) * 12
                       + (now.getMonth() - start.getMonth());
      return monthsDiff % 3 === 0;
    }
    return false;
  });

  if (due.length === 0) {
    return `📅 SIP REMINDER — ${monthName} ${year}\n\nNo SIPs due this month. Add some in the dashboard!`;
  }

  // Build holding lookup
  const holdingMap = {};
  holdings.forEach(h => { holdingMap[h.sym] = h; });

  // Group by category
  const byCategory = {};
  due.forEach(s => {
    const cat = holdingMap[s.sym]?.cat || "other";
    if (!byCategory[cat]) byCategory[cat] = [];
    byCategory[cat].push(s);
  });

  // Totals
  const totalMonthly  = due.reduce((sum, s) => sum + monthlyAmount(s), 0);
  const afterThisMonth = totalInvested + totalMonthly;

  // 20-year compound projection at 10.5% annual
  const r     = 0.105 / 12;
  const n20   = 240;
  const proj20 = afterThisMonth * Math.pow(1 + r, n20)
               + totalMonthly   * (Math.pow(1 + r, n20) - 1) / r;

  // Build message
  const lines = [];
  lines.push(`📅 SIP REMINDER — ${monthName} ${year}`);
  if (isTest) lines.push("(This is a test message)");
  lines.push("", "Here's what to buy this month:", "");

  catOrder.forEach(cat => {
    if (!byCategory[cat]) return;
    lines.push(catLabels[cat] || cat.toUpperCase());
    byCategory[cat].forEach(s => {
      const name    = holdingMap[s.sym]?.name || s.name || s.sym;
      const amt     = monthlyAmount(s);
      const freqTag = s.freq === "weekly"    ? " (weekly)"
                    : s.freq === "quarterly" ? " (quarterly)" : "";
      lines.push(`  • ${s.sym} — €${amt.toFixed(0)}${freqTag}`, `    ${name}`);
      if (s.goal) lines.push(`    🎯 Goal: ${s.goal}`);
    });
    lines.push("");
  });

  lines.push(
    "─────────────────────────",
    `💸 This month: €${totalMonthly.toFixed(0)}`,
    `📦 Total invested after today: ${fmt(afterThisMonth)}`,
    `📈 20yr projection: ${fmt(proj20)} (at 10.5% avg)`,
    "",
    "👆 Open Revolut / Trade Republic and tap buy for each one!",
    "💡 Not financial advice — DCA is your edge.",
  );

  return lines.join("\n");
}

// ─── Monthly scheduler ────────────────────────────────────────────────────────
function msUntilNextFirst() {
  const now  = new Date();
  const next = new Date(now.getFullYear(), now.getMonth() + 1, 1, 9, 0, 0);
  return next - now;
}

function scheduleLoop() {
  const days = (msUntilNextFirst() / 86400000).toFixed(1);
  console.log(`⏰  Next SIP reminder fires in ${days} days (1st of next month, 9am)`);
  console.log("    Ctrl+C to stop\n");

  let timer;
  function tick() {
    console.log("\n🔔  Firing monthly SIP reminder...");
    const plan = loadPlan();
    sendTelegram(buildMessage(plan)).then(() => {
      const ms = msUntilNextFirst();
      console.log(`    Next reminder in ${(ms / 86400000).toFixed(1)} days`);
      timer = setTimeout(tick, ms);
    });
  }

  timer = setTimeout(tick, msUntilNextFirst());
  process.on("SIGINT", () => { clearTimeout(timer); process.exit(0); });
}

// ─── Main ─────────────────────────────────────────────────────────────────────
const args = process.argv.slice(2);

if (args.includes("--schedule")) {
  scheduleLoop();
} else {
  const isTest = args.includes("--test");
  if (isTest) console.log("🧪  Sending test SIP reminder to Telegram...\n");
  else        console.log("📤  Sending SIP reminder now...\n");

  const plan = loadPlan();
  const msg  = buildMessage(plan, isTest);
  console.log("Preview:\n" + "─".repeat(50));
  console.log(msg);
  console.log("─".repeat(50) + "\n");
  sendTelegram(msg).then(() => process.exit(0));
}
