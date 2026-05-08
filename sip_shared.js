/**
 * SIP Shared Utilities
 * Shared config, formatting, plan loading, and Telegram for both SIP scripts.
 */

import fs   from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export const BOT_TOKEN  = process.env.TELEGRAM_BOT_TOKEN || "";
export const CHAT_ID    = process.env.TELEGRAM_CHAT_ID   || "";
export const PLAN_FILE  = path.join(__dirname, "sip_plan.json");
export const STATE_FILE = path.join(__dirname, "sip_dip_state.json");

export function fmt(n) {
  if (n >= 1e6) return "$" + (n / 1e6).toFixed(2) + "M";
  if (n >= 1e3) return "$" + (n / 1e3).toFixed(1)  + "K";
  if (n < 1)    return "$" + n.toFixed(4);
  return "$" + n.toFixed(2);
}

export function monthlyAmount(sip) {
  if (sip.freq === "weekly")     return sip.amount * 4.33;
  if (sip.freq === "quarterly")  return sip.amount;
  return sip.amount;
}

export function loadPlan() {
  try {
    return JSON.parse(fs.readFileSync(PLAN_FILE, "utf8"));
  } catch {
    console.error("❌  sip_plan.json not found. Open SIP dashboard → Save to Bot first.");
    process.exit(1);
  }
}

export function loadState() {
  try {
    return JSON.parse(fs.readFileSync(STATE_FILE, "utf8"));
  } catch {
    return { lastAlert: {} };
  }
}

export function saveState(s) {
  fs.writeFileSync(STATE_FILE, JSON.stringify(s, null, 2));
}

export async function sendTelegram(text) {
  if (!BOT_TOKEN || !CHAT_ID) {
    console.error("❌  TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set in .env");
    return false;
  }
  const res  = await fetch(`https://api.telegram.org/bot${BOT_TOKEN}/sendMessage`, {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify({ chat_id: CHAT_ID, text }),
  });
  const data = await res.json();
  if (!res.ok || !data.ok) {
    console.error("❌  Telegram error:", data.description || JSON.stringify(data));
    return false;
  }
  console.log("✅  Telegram message sent!");
  return true;
}
