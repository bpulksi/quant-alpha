import unittest
import pandas as pd
import numpy as np
import sys
import os

# Add parent directory to sys.path to import quant_engine_v3
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from quant_engine_v3 import calc_sma

class TestQuantEngineV3(unittest.TestCase):
    def test_calc_sma(self):
        s = pd.Series([1, 2, 3, 4, 5])
        result = calc_sma(s, p=3)
        expected = pd.Series([np.nan, np.nan, 2.0, 3.0, 4.0])
        pd.testing.assert_series_equal(result, expected)

if __name__ == '__main__':
    unittest.main()
