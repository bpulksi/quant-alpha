import { describe, it } from 'node:test';
import assert from 'node:assert';
import { fmt, monthlyAmount } from './sip_shared.js';

describe('sip_shared utility functions', () => {
  describe('fmt', () => {
    it('formats values greater than or equal to 1,000,000 in millions (M)', () => {
      assert.strictEqual(fmt(1500000), '$1.50M');
      assert.strictEqual(fmt(1000000), '$1.00M');
      assert.strictEqual(fmt(2345000), '$2.35M'); // toFixed(2) rounds 2.345 to 2.35
    });

    it('formats values greater than or equal to 1,000 in thousands (K)', () => {
      assert.strictEqual(fmt(1500), '$1.5K');
      assert.strictEqual(fmt(1000), '$1.0K');
      assert.strictEqual(fmt(999999), '$1000.0K');
    });

    it('formats values less than 1 with 4 decimal places', () => {
      assert.strictEqual(fmt(0.5), '$0.5000');
      assert.strictEqual(fmt(0.12345), '$0.1235'); // toFixed rounds up
      assert.strictEqual(fmt(0), '$0.0000');
      assert.strictEqual(fmt(-0.5), '$-0.5000');
    });

    it('formats normal values (1 to 999) with 2 decimal places', () => {
      assert.strictEqual(fmt(1), '$1.00');
      assert.strictEqual(fmt(500), '$500.00');
      assert.strictEqual(fmt(999.99), '$999.99');
    });
  });

  describe('monthlyAmount', () => {
    it('multiplies amount by 4.33 for weekly frequency', () => {
      assert.strictEqual(monthlyAmount({ freq: 'weekly', amount: 100 }), 433);
      assert.strictEqual(monthlyAmount({ freq: 'weekly', amount: 50 }), 216.5);
    });

    it('returns original amount for quarterly frequency', () => {
      assert.strictEqual(monthlyAmount({ freq: 'quarterly', amount: 500 }), 500);
      assert.strictEqual(monthlyAmount({ freq: 'quarterly', amount: 1000 }), 1000);
    });

    it('returns original amount for monthly or any other frequency', () => {
      assert.strictEqual(monthlyAmount({ freq: 'monthly', amount: 300 }), 300);
      assert.strictEqual(monthlyAmount({ freq: 'daily', amount: 10 }), 10);
      assert.strictEqual(monthlyAmount({ amount: 150 }), 150);
    });
  });
});
