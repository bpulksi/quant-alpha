import test from "node:test";
import assert from "node:assert";
import { fmt, monthlyAmount } from "./sip_shared.js";

test("fmt formats numbers correctly", (t) => {
  assert.strictEqual(fmt(1500000), "$1.50M");
  assert.strictEqual(fmt(1000000), "$1.00M");
  assert.strictEqual(fmt(1500), "$1.5K");
  assert.strictEqual(fmt(1000), "$1.0K");
  assert.strictEqual(fmt(500.5), "$500.50");
  assert.strictEqual(fmt(10), "$10.00");
  assert.strictEqual(fmt(0.5555), "$0.5555");
  assert.strictEqual(fmt(0.1), "$0.1000");
});

test("monthlyAmount calculates monthly SIP correctly", (t) => {
  assert.strictEqual(monthlyAmount({ freq: "weekly", amount: 100 }), 433);
  assert.strictEqual(monthlyAmount({ freq: "quarterly", amount: 100 }), 100);
  assert.strictEqual(monthlyAmount({ freq: "monthly", amount: 100 }), 100);
  assert.strictEqual(monthlyAmount({ amount: 100 }), 100);
});
