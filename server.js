/**
 * Quant Alpha — Server Entry Point
 * ================================
 * 1. Serves dashboard.html + JSON state files via Express (PORT env var or 3000)
 * 2. Spawns multi_trader.js on a 15-minute loop
 *
 * Railway / cloud: this is the single process that runs everything.
 * Local:           node server.js  →  open http://localhost:3000
 */

import express    from "express";
import basicAuth  from "express-basic-auth";
import { spawn }  from "child_process";
import path       from "path";
import { fileURLToPath } from "url";
import fs         from "fs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// ─── Config ──────────────────────────────────────────────────────────────────

const PORT         = parseInt(process.env.PORT || "3000");
const BOT_INTERVAL = parseInt(process.env.BOT_INTERVAL_MIN || "15") * 60 * 1000;
const BOT_SCRIPT   = path.join(__dirname, "multi_trader.js");

// DATA_DIR: Railway persistent volume path (set DATA_DIR=/data in Railway env vars)
// Locally: falls back to bot directory — same behaviour as before
const DATA_DIR = process.env.DATA_DIR || __dirname;

// ─── Express setup ────────────────────────────────────────────────────────────

const app = express();

// ── Public routes (Health check for Railway / uptime monitors) ────────────────
// These are placed BEFORE auth so monitors can hit them without credentials.
app.get("/health", (req, res) => {
  const stateFile = path.join(DATA_DIR, "multi-trade-log.json");
  const exists    = fs.existsSync(stateFile);
  res.json({
    status:    "ok",
    bot:       botRunning ? "running" : "idle",
    log:       exists,
    timestamp: new Date().toISOString(),
  });
});

// ── Basic auth (protects dashboard on cloud) ─────────────────────────────────
// Set DASH_USER and DASH_PASS in Railway environment variables.
// If not set: auth is disabled locally (safe for dev, required for cloud).
const DASH_USER = process.env.DASH_USER;
const DASH_PASS = process.env.DASH_PASS;
if (DASH_USER && DASH_PASS) {
  app.use(basicAuth({
    users:     { [DASH_USER]: DASH_PASS },
    challenge: true,
    realm:     "Quant Alpha",
  }));
  console.log(`  🔒 Dashboard protected — user: ${DASH_USER}`);
} else {
  console.log("  ⚠️  No DASH_USER/DASH_PASS set — dashboard is open (fine locally, set on Railway)");
}

// ── Static Asset Security Middleware ─────────────────────────────────────────
// Prevent access to sensitive source files even if they are in the static root.
app.use((req, res, next) => {
  const blockedFiles = [
    'server.js', 'package.json', 'package-lock.json', '.env',
    'multi_trader.js', 'requirements.txt', 'AGENTS.md', 'README.md',
    'nixpacks.toml', 'railway.json'
  ];
  const requestedFile = path.basename(req.path).toLowerCase();

  // Block specific sensitive files and all hidden files (starting with dot)
  if (blockedFiles.includes(requestedFile) ||
      requestedFile.startsWith('.') ||
      requestedFile.endsWith('.py') ||
      requestedFile.endsWith('.log')) {
    return res.status(403).send("Forbidden");
  }
  next();
});

// ── Serve JSON state files from DATA_DIR (persistent volume on Railway) ───────
// These are the live state files the dashboard reads (portfolio, research, etc.)
app.use("/state", express.static(DATA_DIR, {
  setHeaders(res, filePath) {
    if (filePath.endsWith(".json")) {
      res.setHeader("Cache-Control", "no-store");
    }
  },
}));

// ── Serve dashboard + static assets from bot dir ─────────────────────────────
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
  console.log(`  📊 State files served from: ${DATA_DIR}\n`);
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
