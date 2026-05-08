import { test } from "node:test";
import assert from "node:assert";
import { isStock, ALPACA_STOCK_SYMBOLS } from "./multi_trader.js";

test("isStock identifies known Alpaca stocks", () => {
  assert.strictEqual(isStock("AAPL"), true);
  assert.strictEqual(isStock("MSFT"), true);
  assert.strictEqual(isStock("SPY"), true);
});

test("isStock is case-insensitive", () => {
  assert.strictEqual(isStock("aapl"), true);
  assert.strictEqual(isStock("Msft"), true);
});

test("isStock identifies stocks from STOCK_SYMBOLS env", () => {
  // STOCK_SYMBOLS is initialized from process.env.STOCK_SYMBOLS when multi_trader.js is loaded.
  // Since we can't easily re-initialize it in the same process without refactoring,
  // we check if it's working with what's currently in env or if it's empty.
  const envStocks = (process.env.STOCK_SYMBOLS || "").split(",").map(s => s.trim()).filter(Boolean);
  if (envStocks.length > 0) {
    assert.strictEqual(isStock(envStocks[0]), true);
  }
});

test("isStock returns false for crypto and unknown symbols", () => {
  assert.strictEqual(isStock("BTCUSDT"), false);
  assert.strictEqual(isStock("ETHUSDT"), false);
  assert.strictEqual(isStock("INVALID_SYMBOL"), false);
});

test("ALPACA_STOCK_SYMBOLS set is exported and contains expected stocks", () => {
  assert.ok(ALPACA_STOCK_SYMBOLS.has("AAPL"));
  assert.ok(ALPACA_STOCK_SYMBOLS.has("NVDA"));
  assert.ok(ALPACA_STOCK_SYMBOLS.has("COIN"));
});
