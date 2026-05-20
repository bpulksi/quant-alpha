import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta
import news_fetcher

class TestNewsFetcher(unittest.TestCase):

    @patch('news_fetcher.datetime')
    def test_age_hours(self, mock_datetime):
        # Set the mocked 'now' to a known fixed time: 2023-01-02 12:00:00 UTC
        fixed_now = datetime(2023, 1, 2, 12, 0, 0, tzinfo=timezone.utc)
        mock_datetime.now.return_value = fixed_now
        # Also need to mock fromisoformat on the mocked datetime to pass through to the real one
        mock_datetime.fromisoformat.side_effect = datetime.fromisoformat

        # 1. Empty input -> defaults to 12.0
        self.assertEqual(news_fetcher._age_hours(""), 12.0)
        self.assertEqual(news_fetcher._age_hours(None), 12.0)

        # 2. ISO string ending with 'Z'
        # 2 hours before fixed_now
        self.assertEqual(news_fetcher._age_hours("2023-01-02T10:00:00Z"), 2.0)

        # 3. ISO string with explicit timezone offset (+00:00)
        # 3.5 hours before fixed_now
        self.assertEqual(news_fetcher._age_hours("2023-01-02T08:30:00+00:00"), 3.5)

        # 4. ISO string missing timezone (should default to UTC)
        # 1 hour before fixed_now
        self.assertEqual(news_fetcher._age_hours("2023-01-02T11:00:00"), 1.0)

        # 5. RFC 2822 string
        # "Mon, 02 Jan 2023 09:00:00 +0000" -> 3 hours before fixed_now
        self.assertEqual(news_fetcher._age_hours("Mon, 02 Jan 2023 09:00:00 +0000"), 3.0)

        # 6. Invalid format -> defaults to 12.0
        self.assertEqual(news_fetcher._age_hours("Not a valid date"), 12.0)

if __name__ == '__main__':
    unittest.main()
