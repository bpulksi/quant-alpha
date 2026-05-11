import unittest
from news_fetcher import _to_ticker, SYMBOL_MAP

class TestNewsFetcher(unittest.TestCase):
    def test_to_ticker_mapped_symbols(self):
        """Test symbols that exist in the SYMBOL_MAP."""
        # Test a few known ones
        self.assertEqual(_to_ticker("BTCUSDT"), "BTC")
        self.assertEqual(_to_ticker("ETHUSDT"), "ETH")
        self.assertEqual(_to_ticker("SOLUSDT"), "SOL")

    def test_to_ticker_unmapped_with_usdt(self):
        """Test symbols not in SYMBOL_MAP but with USDT suffix."""
        self.assertEqual(_to_ticker("PEPEUSDT"), "PEPE")
        self.assertEqual(_to_ticker("SHIBUSDT"), "SHIB")

    def test_to_ticker_lowercase(self):
        """Test that lowercase inputs are handled correctly."""
        self.assertEqual(_to_ticker("btcusdt"), "BTC")
        self.assertEqual(_to_ticker("pepeusdt"), "PEPE")
        self.assertEqual(_to_ticker("aapl"), "AAPL")

    def test_to_ticker_stock_tickers(self):
        """Test standard stock tickers (no USDT)."""
        self.assertEqual(_to_ticker("AAPL"), "AAPL")
        self.assertEqual(_to_ticker("MSFT"), "MSFT")
        self.assertEqual(_to_ticker("NVDA"), "NVDA")

    def test_to_ticker_already_clean_crypto(self):
        """Test crypto tickers that don't have USDT suffix."""
        self.assertEqual(_to_ticker("BTC"), "BTC")
        self.assertEqual(_to_ticker("ETH"), "ETH")

if __name__ == '__main__':
    unittest.main()
