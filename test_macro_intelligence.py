import unittest
from datetime import datetime, timezone, timedelta
from macro_intelligence import get_macro_score

class TestMacroIntelligence(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(timezone.utc)

    def test_get_macro_score_empty(self):
        # When no signals are provided, score should be 0.0
        data = {"signals": []}
        result = get_macro_score("BTCUSDT", data)
        self.assertEqual(result["macro_score"], 0.0)
        self.assertEqual(result["signal_count"], 0)

    def test_get_macro_score_target_match(self):
        # Test exact target matching
        data = {
            "signals": [
                {
                    "title": "Bullish BTC",
                    "direction": 0.8,
                    "targets": ["BTC"],
                    "added_at": self.now.isoformat(),
                    "expires": (self.now + timedelta(days=10)).isoformat(),
                    "weight": 1.0
                }
            ]
        }
        # BTCUSDT should match BTC
        result = get_macro_score("BTCUSDT", data)
        self.assertAlmostEqual(result["macro_score"], 0.8)
        self.assertEqual(result["signal_count"], 1)

    def test_get_macro_score_category_match(self):
        # Test broad category matching
        data = {
            "signals": [
                {
                    "title": "US Market Bullish",
                    "direction": 0.5,
                    "categories": ["US_MARKET"],
                    "added_at": self.now.isoformat(),
                    "expires": (self.now + timedelta(days=10)).isoformat(),
                    "weight": 1.0
                }
            ]
        }
        # AAPL falls under Consumer/US Market, so it matches US_MARKET
        result = get_macro_score("AAPL", data)
        self.assertAlmostEqual(result["macro_score"], 0.5)

    def test_get_macro_score_expired_signal(self):
        # Test that expired signals are ignored
        data = {
            "signals": [
                {
                    "title": "Old Signal",
                    "direction": 1.0,
                    "targets": ["BTC"],
                    "added_at": (self.now - timedelta(days=20)).isoformat(),
                    "expires": (self.now - timedelta(days=1)).isoformat(), # Expired yesterday
                    "weight": 1.0
                }
            ]
        }
        result = get_macro_score("BTC", data)
        self.assertEqual(result["macro_score"], 0.0)
        self.assertEqual(result["signal_count"], 0)

    def test_get_macro_score_age_decay(self):
        # Test that older signals have less weight
        # decay = max(0.1, 1.0 - (age_days / 30) * 0.7)
        old_time = self.now - timedelta(days=15)

        data = {
            "signals": [
                {
                    "title": "Aging Signal",
                    "direction": 1.0,
                    "targets": ["BTC"],
                    "added_at": old_time.isoformat(),
                    "expires": (self.now + timedelta(days=10)).isoformat(),
                    "weight": 1.0
                }
            ]
        }
        result = get_macro_score("BTC", data)

        # Age is 15 days, decay should be 1.0 - (15/30)*0.7 = 1.0 - 0.35 = 0.65
        # Score = (direction * weight) / weight = (1.0 * 0.65) / 0.65 = 1.0
        # Wait, if there's only one signal, the score_sum / weight_sum will cancel out the decay!
        # final_score = score_sum / weight_sum
        self.assertAlmostEqual(result["macro_score"], 1.0)

        # To truly test decay, we need a fresh signal and an old signal to see weight difference
        data2 = {
            "signals": [
                {
                    "title": "Fresh Signal",
                    "direction": -1.0,
                    "targets": ["BTC"],
                    "added_at": self.now.isoformat(),
                    "expires": (self.now + timedelta(days=10)).isoformat(),
                    "weight": 1.0
                },
                {
                    "title": "Aging Signal",
                    "direction": 1.0,
                    "targets": ["BTC"],
                    "added_at": old_time.isoformat(),
                    "expires": (self.now + timedelta(days=10)).isoformat(),
                    "weight": 1.0
                }
            ]
        }
        # Fresh signal weight = 1.0, score = -1.0
        # Aging signal weight = 0.65, score = 1.0
        # Total score = (-1.0*1.0 + 1.0*0.65) / (1.0 + 0.65) = -0.35 / 1.65 = -0.2121
        result2 = get_macro_score("BTC", data2)
        self.assertTrue(result2["macro_score"] < 0) # Fresh signal dominates

    def test_get_macro_score_bounds(self):
        # Test that score is capped at -1.0 and 1.0
        # If signals have direction > 1.0 (though nominally restricted, test bounds enforcement)
        data = {
            "signals": [
                {
                    "title": "Extreme Bullish",
                    "direction": 2.5,
                    "targets": ["BTC"],
                    "added_at": self.now.isoformat(),
                    "expires": (self.now + timedelta(days=10)).isoformat(),
                    "weight": 1.0
                }
            ]
        }
        result = get_macro_score("BTC", data)
        self.assertEqual(result["macro_score"], 1.0) # Capped at 1.0

        data = {
            "signals": [
                {
                    "title": "Extreme Bearish",
                    "direction": -5.0,
                    "targets": ["BTC"],
                    "added_at": self.now.isoformat(),
                    "expires": (self.now + timedelta(days=10)).isoformat(),
                    "weight": 1.0
                }
            ]
        }
        result = get_macro_score("BTC", data)
        self.assertEqual(result["macro_score"], -1.0) # Capped at -1.0

if __name__ == "__main__":
    unittest.main()
