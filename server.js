/**
 * Quant Alpha — Server Entry Point
 * ================================
 * 1. Serves dashboard.html + JSON state files via Express (PORT env var or 3000)
 * 2. Spawns multi_trader.js on a 15-minute loop
 *
 * Railway / cloud: this is the single process that runs everything.
 * Local:           node server.js  →  open http://localhost:3000
 */

import express from "express";
import { spawn } from "child_process";
import { createRequire } from "module";
import path from "path";
import { fileURLToPath } from "url";
import fs from "fs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const require   = createRequire(import.meta.url);

// ─── Config ──────────────────────────────────────────────────────────────────

const PORT         = parseInt(process.env.PORT || "3000");
const BOT_INTERVAL = parseInt(process.env.BOT_INTERVAL_MIN || "15") * 60 * 1000;
const BOT_SCRIPT   = path.join(__dirname, "multi_trader.js");

// ─── Express — serve dashboard + state JSON files ────────────────────────────

const app = express();

// Serve all static files (dashboard.html, *.json state files) from bot dir
app.use(express.static(__dirname, {
  setHeaders(res, filePath) {
    // No-cache for JSON state files so dashboard always gets fresh data
    if (filePath.endsWith(".json")) {
      res.setHeader("Cache-Control", "no-store");
    }
  },
}));

// Root → dashboard
app.get("/", (req, res) => {
  res.sendFile(path.join(__dirname, "dashboard.html"));
});

// Health check for Railway / uptime monitors
app.get("/health", (req, res) => {
  const stateFile = path.join(__dirname, "multi-trade-log.json");
  const exists    = fs.existsSync(stateFile);
  res.json({
    status:    "ok",
    bot:       botRunning ? "running" : "idle",
    log:       exists,
    timestamp: new Date().toISOString(),
  });
});

// Live status endpoint — last N lines of bot output
app.get("/status", (req, res) => {
  res.json({
    lastBotRun:   lastBotRun,
    nextBotRun:   nextBotRun,
    botRunning:   botRunning,
    runCount:     runCount,
    lastExitCode: lastExitCode,
    uptime:       Math.round(process.uptime()) + "s",
  });
});

app.listen(PORT, () => {
  console.log(`\n  ✅ Dashboard live → http://localhost:${PORT}`);
  console.log(`  📊 State files served from: ${__dirname}\n`);
});

// ─── Bot runner — spawns multi_trader.js every BOT_INTERVAL ms ───────────────

let botRunning   = false;
let lastBotRun   = null;
let nextBotRun   = null;
let lastExitCode = null;
let runCount     = 0;

function runBot() {
  if (botRunning) {
    console.log("  [server] Bot already running — skipping this tick");
    return;
  }

  runCount++;
  botRunning = true;
  lastBotRun = new Date().toISOString();
  nextBotRun = new Date(Date.now() + BOT_INTERVAL).toISOString();

  console.log(`\n${"=".repeat(65)}`);
  console.log(`  [server] Bot run #${runCount} — ${lastBotRun}`);
  console.log(`  [server] Next run: ${nextBotRun}`);
  console.log(`${"=".repeat(65)}\n`);

  const bot = spawn("node", [BOT_SCRIPT], {
    stdio: "inherit",   // pipe bot stdout/stderr straight to server stdout
    env:   process.env, // pass all env vars (Railway injects secrets here)
  });

  bot.on("close", (code) => {
    botRunning   = false;
    lastExitCode = code;
    console.log(`\n  [server] Bot run #${runCount} finished (exit ${code})`);
    console.log(`  [server] Next run in ${BOT_INTERVAL / 60000} min\n`);
  });

  bot.on("error", (err) => {
    botRunning = false;
    console.error(`  [server] Failed to spawn bot: ${err.message}`);
  });
}

// Run immediately on startup, then every BOT_INTERVAL
runBot();
setInterval(runBot, BOT_INTERVAL);

// ─── Graceful shutdown ────────────────────────────────────────────────────────

process.on("SIGTERM", () => {
  console.log("\n  [server] SIGTERM received — shutting down gracefully");
  process.exit(0);
});
process.on("SIGINT", () => {
  console.log("\n  [server] Stopped");
  process.exit(0);
});
