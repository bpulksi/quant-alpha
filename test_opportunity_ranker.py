import unittest
from opportunity_ranker import rank_opportunities

class TestOpportunityRanker(unittest.TestCase):
    def test_rank_opportunities_happy_path(self):
        opportunities = [
            {"name": "A", "opportunity_score": 0.5},
            {"name": "B", "opportunity_score": 0.9},
            {"name": "C", "opportunity_score": 0.2},
        ]
        ranked = rank_opportunities(opportunities)
        self.assertEqual(ranked[0]["name"], "B")
        self.assertEqual(ranked[1]["name"], "A")
        self.assertEqual(ranked[2]["name"], "C")

    def test_rank_opportunities_missing_score(self):
        opportunities = [
            {"name": "A", "opportunity_score": 0.5},
            {"name": "B"},  # Missing score, should default to 0
            {"name": "C", "opportunity_score": -0.1},
        ]
        ranked = rank_opportunities(opportunities)
        self.assertEqual(ranked[0]["name"], "A")
        self.assertEqual(ranked[1]["name"], "B")
        self.assertEqual(ranked[2]["name"], "C")

    def test_rank_opportunities_empty_list(self):
        opportunities = []
        ranked = rank_opportunities(opportunities)
        self.assertEqual(ranked, [])

    def test_rank_opportunities_equal_scores(self):
        opportunities = [
            {"name": "A", "opportunity_score": 0.5},
            {"name": "B", "opportunity_score": 0.5},
            {"name": "C", "opportunity_score": 0.8},
        ]
        ranked = rank_opportunities(opportunities)
        self.assertEqual(ranked[0]["name"], "C")
        # Python's sort is stable, so original order of equal elements is preserved
        self.assertEqual(ranked[1]["name"], "A")
        self.assertEqual(ranked[2]["name"], "B")

if __name__ == '__main__':
    unittest.main()
