import unittest
from unittest.mock import patch
from arbitrage_scanner import calculate_spread

class TestArbitrageScannerCalculateSpread(unittest.TestCase):
    def setUp(self):
        # We will patch the FEES dict to have known, simple values for testing
        self.mock_fees = {
            "bybit": 0.10,
            "kraken": 0.20,
            "coinbase": 0.15
        }
        self.patcher = patch.dict("arbitrage_scanner.FEES", self.mock_fees, clear=True)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    def test_calculate_spread_empty_input(self):
        result = calculate_spread({})
        # Note: In arbitrage_scanner.py, if len(valid) < 2, it returns this specific dict
        expected_result = {
            "spread_pct": 0.0,
            "net_spread": 0.0,
            "is_profitable": False,
            "is_actionable": False,
            "valid": False
        }
        self.assertEqual(result, expected_result)

    def test_calculate_spread_insufficient_valid_prices(self):
        # Only one valid price
        prices = {"bybit": 100.0, "kraken": None, "coinbase": None}
        result = calculate_spread(prices)
        self.assertFalse(result["is_profitable"])
        self.assertFalse(result["is_actionable"])
        self.assertFalse(result["valid"])
        self.assertEqual(result["spread_pct"], 0.0)

    def test_calculate_spread_profitable_and_actionable(self):
        # Buy on bybit (min_p = 100), sell on kraken (max_p = 101)
        # spread_pct = (101 - 100) / 100 * 100 = 1.0%
        # fee_buy = 0.10 (bybit), fee_sell = 0.20 (kraken)
        # net_spread = 1.0 - 0.10 - 0.20 = 0.70% (> 0.30%, so actionable)
        prices = {"bybit": 100.0, "kraken": 101.0, "coinbase": 100.5}
        result = calculate_spread(prices)

        self.assertTrue(result["valid"])
        self.assertEqual(result["buy_exchange"], "bybit")
        self.assertEqual(result["sell_exchange"], "kraken")
        self.assertEqual(result["buy_price"], 100.0)
        self.assertEqual(result["sell_price"], 101.0)
        self.assertAlmostEqual(result["spread_pct"], 1.0)
        self.assertAlmostEqual(result["net_spread"], 0.70)
        self.assertTrue(result["is_profitable"])
        self.assertTrue(result["is_actionable"])

    def test_calculate_spread_profitable_but_not_actionable(self):
        # Buy on bybit (min_p = 100), sell on coinbase (max_p = 100.4)
        # spread_pct = (100.4 - 100) / 100 * 100 = 0.4%
        # fee_buy = 0.10 (bybit), fee_sell = 0.15 (coinbase)
        # net_spread = 0.4 - 0.10 - 0.15 = 0.15% (<= 0.30%, so not actionable but profitable)
        prices = {"bybit": 100.0, "kraken": None, "coinbase": 100.4}
        result = calculate_spread(prices)

        self.assertTrue(result["valid"])
        self.assertAlmostEqual(result["spread_pct"], 0.4)
        self.assertAlmostEqual(result["net_spread"], 0.15)
        self.assertTrue(result["is_profitable"])
        self.assertFalse(result["is_actionable"])

    def test_calculate_spread_unprofitable(self):
        # Buy on bybit (min_p = 100), sell on coinbase (max_p = 100.1)
        # spread_pct = (100.1 - 100) / 100 * 100 = 0.1%
        # fee_buy = 0.10 (bybit), fee_sell = 0.15 (coinbase)
        # net_spread = 0.1 - 0.10 - 0.15 = -0.15% (unprofitable)
        prices = {"bybit": 100.0, "kraken": 100.0, "coinbase": 100.1}
        result = calculate_spread(prices)

        self.assertTrue(result["valid"])
        self.assertAlmostEqual(result["spread_pct"], 0.1)
        self.assertAlmostEqual(result["net_spread"], -0.15)
        self.assertFalse(result["is_profitable"])
        self.assertFalse(result["is_actionable"])

    def test_calculate_spread_default_fees(self):
        # Test fallback to default fee of 0.20 if exchange not in FEES
        # Buy on unknown_ex1 (min_p=100), sell on unknown_ex2 (max_p=101)
        # spread_pct = 1.0%
        # fee_buy = 0.20, fee_sell = 0.20
        # net_spread = 1.0 - 0.20 - 0.20 = 0.60%
        prices = {"unknown_ex1": 100.0, "unknown_ex2": 101.0}
        result = calculate_spread(prices)

        self.assertTrue(result["valid"])
        self.assertAlmostEqual(result["net_spread"], 0.60)


if __name__ == "__main__":
    unittest.main()
