import unittest
from unittest.mock import patch
import arbitrage_scanner

class TestCalculateSpread(unittest.TestCase):

    @patch.dict('arbitrage_scanner.FEES', {"bybit": 0.10, "kraken": 0.20, "coinbase": 0.15})
    def test_calculate_spread_insufficient_prices(self):
        # 0 valid prices
        result = arbitrage_scanner.calculate_spread({"bybit": None, "kraken": None, "coinbase": None})
        self.assertEqual(result, {"spread_pct": 0.0, "net_spread": 0.0, "is_profitable": False, "is_actionable": False, "valid": False})

        # 1 valid price
        result = arbitrage_scanner.calculate_spread({"bybit": 50000.0, "kraken": None, "coinbase": None})
        self.assertEqual(result, {"spread_pct": 0.0, "net_spread": 0.0, "is_profitable": False, "is_actionable": False, "valid": False})

    @patch.dict('arbitrage_scanner.FEES', {"bybit": 0.10, "kraken": 0.20, "coinbase": 0.15})
    def test_calculate_spread_two_exchanges(self):
        prices = {"bybit": 50000.0, "kraken": 51000.0, "coinbase": None}
        result = arbitrage_scanner.calculate_spread(prices)

        self.assertTrue(result["valid"])
        self.assertEqual(result["buy_exchange"], "bybit")
        self.assertEqual(result["sell_exchange"], "kraken")
        self.assertEqual(result["buy_price"], 50000.0)
        self.assertEqual(result["sell_price"], 51000.0)

        # Spread pct: (51000 - 50000) / 50000 * 100 = 2.0%
        self.assertAlmostEqual(result["spread_pct"], 2.0)

        # Net spread: 2.0 - fee_buy(bybit: 0.1) - fee_sell(kraken: 0.2) = 1.7%
        self.assertAlmostEqual(result["net_spread"], 1.7)
        self.assertTrue(result["is_profitable"])
        self.assertTrue(result["is_actionable"]) # 1.7 > 0.30

    @patch.dict('arbitrage_scanner.FEES', {"bybit": 0.10, "kraken": 0.20, "coinbase": 0.15})
    def test_calculate_spread_three_exchanges(self):
        prices = {"bybit": 50000.0, "kraken": 51000.0, "coinbase": 49000.0}
        result = arbitrage_scanner.calculate_spread(prices)

        self.assertTrue(result["valid"])
        self.assertEqual(result["buy_exchange"], "coinbase")
        self.assertEqual(result["sell_exchange"], "kraken")
        self.assertEqual(result["buy_price"], 49000.0)
        self.assertEqual(result["sell_price"], 51000.0)

        # Spread pct: (51000 - 49000) / 49000 * 100 = 4.081632...
        self.assertAlmostEqual(result["spread_pct"], 4.0816, places=4)

        # Net spread: 4.0816... - fee_buy(coinbase: 0.15) - fee_sell(kraken: 0.20) = 3.7316...
        self.assertAlmostEqual(result["net_spread"], 3.7316, places=4)

    @patch.dict('arbitrage_scanner.FEES', {"bybit": 0.10, "kraken": 0.20, "coinbase": 0.15})
    def test_calculate_spread_not_actionable_but_profitable(self):
        # 50100 - 50000 = 100. 100/50000 * 100 = 0.2% spread.
        # Net spread: 0.2 - 0.1(bybit) - 0.2(kraken) = -0.1 (not profitable)
        # Let's adjust prices to make it profitable but not actionable (> 0 but <= 0.3)
        prices = {"bybit": 50000.0, "kraken": 50250.0}
        # Spread pct: 250/50000 * 100 = 0.5%
        # Net spread: 0.5 - 0.1 - 0.2 = 0.2%
        result = arbitrage_scanner.calculate_spread(prices)

        self.assertTrue(result["valid"])
        self.assertTrue(result["is_profitable"])
        self.assertFalse(result["is_actionable"])
        self.assertAlmostEqual(result["net_spread"], 0.2)

    @patch.dict('arbitrage_scanner.FEES', {"bybit": 0.10, "kraken": 0.20, "coinbase": 0.15})
    def test_calculate_spread_not_profitable(self):
        prices = {"bybit": 50000.0, "kraken": 50050.0}
        # Spread pct: 50/50000 * 100 = 0.1%
        # Net spread: 0.1 - 0.1 - 0.2 = -0.2%
        result = arbitrage_scanner.calculate_spread(prices)

        self.assertTrue(result["valid"])
        self.assertFalse(result["is_profitable"])
        self.assertFalse(result["is_actionable"])
        self.assertAlmostEqual(result["net_spread"], -0.2)

if __name__ == '__main__':
    unittest.main()