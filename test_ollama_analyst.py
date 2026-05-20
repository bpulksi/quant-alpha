import unittest
from unittest.mock import patch, MagicMock
import sys
import json
import io

from ollama_analyst import (
    check_ollama_running,
    score_with_ollama,
    score_with_vader,
    score_news
)

class TestOllamaAnalyst(unittest.TestCase):

    @patch('urllib.request.urlopen')
    def test_check_ollama_running_success(self, mock_urlopen):
        # mock_urlopen returns a MagicMock, which evaluates to True
        self.assertTrue(check_ollama_running())
        mock_urlopen.assert_called_once()

    @patch('urllib.request.urlopen')
    def test_check_ollama_running_failure(self, mock_urlopen):
        mock_urlopen.side_effect = Exception("Connection error")
        self.assertFalse(check_ollama_running())
        mock_urlopen.assert_called_once()

    @patch('urllib.request.urlopen')
    def test_score_with_ollama_success(self, mock_urlopen):
        mock_response = MagicMock()
        mock_json_response = {
            "response": '{"score": 0.8, "reasoning": "Very bullish news.", "key_events": ["ETF approval"]}'
        }
        mock_response.read.return_value = json.dumps(mock_json_response).encode()
        mock_urlopen.return_value = mock_response

        result = score_with_ollama("BTC", ["BTC up 10% today"])

        self.assertIsNotNone(result)
        self.assertEqual(result["score"], 0.8)
        self.assertEqual(result["reasoning"], "Very bullish news.")
        self.assertEqual(result["key_events"], ["ETF approval"])
        self.assertEqual(result["source"], "ollama")
        mock_urlopen.assert_called_once()

    @patch('urllib.request.urlopen')
    def test_score_with_ollama_clamp_score(self, mock_urlopen):
        mock_response = MagicMock()
        mock_json_response = {
            "response": '{"score": 1.5, "reasoning": "Extremely bullish", "key_events": []}'
        }
        mock_response.read.return_value = json.dumps(mock_json_response).encode()
        mock_urlopen.return_value = mock_response

        result = score_with_ollama("BTC", ["BTC hitting moon"])

        self.assertIsNotNone(result)
        self.assertEqual(result["score"], 1.0) # Clamped from 1.5
        mock_urlopen.assert_called_once()

    @patch('urllib.request.urlopen')
    def test_score_with_ollama_failure(self, mock_urlopen):
        mock_urlopen.side_effect = Exception("Ollama down")

        # Suppress print statement from exception handler
        with patch('sys.stdout', new_callable=io.StringIO):
            result = score_with_ollama("BTC", ["News 1"])

        self.assertIsNone(result)
        mock_urlopen.assert_called_once()

    @patch('urllib.request.urlopen')
    def test_score_with_ollama_no_json(self, mock_urlopen):
        mock_response = MagicMock()
        mock_json_response = {
            "response": 'Just some text, no json.'
        }
        mock_response.read.return_value = json.dumps(mock_json_response).encode()
        mock_urlopen.return_value = mock_response

        # Suppress print statement from exception handler, though this doesn't raise exception
        # it just returns None
        result = score_with_ollama("BTC", ["News 1"])

        self.assertIsNone(result)
        mock_urlopen.assert_called_once()

    def test_score_with_vader_success(self):
        # Create a mock SentimentIntensityAnalyzer class
        mock_sia_instance = MagicMock()
        # Return a compound score of 0.5 for any headline
        mock_sia_instance.polarity_scores.return_value = {"compound": 0.5}

        mock_sia_class = MagicMock(return_value=mock_sia_instance)

        mock_vader_module = MagicMock()
        mock_vader_module.SentimentIntensityAnalyzer = mock_sia_class

        with patch.dict('sys.modules', {'vaderSentiment.vaderSentiment': mock_vader_module}):
            result = score_with_vader(["Good news", "Great news"])

            self.assertEqual(result["score"], 0.5) # Average of two 0.5s is 0.5
            self.assertTrue(result["reasoning"].startswith("VADER average"))
            self.assertEqual(result["source"], "vader")

    def test_score_with_vader_failure(self):
        # If vaderSentiment is not installed, it raises ModuleNotFoundError
        # We can simulate this without patching, as it's not installed in the environment
        # Wait, if it IS installed, we should ensure it fails to test the exception handler.
        # So we force the import to raise an exception.

        # We patch __import__ but it's tricky, instead let's patch the vaderSentiment module to raise Error
        # Actually easier to use patch.dict on sys.modules to remove it, but import inside function might fail
        # Or just patch the sys.modules to make it None which raises ModuleNotFoundError
        with patch.dict('sys.modules', {'vaderSentiment.vaderSentiment': None}):
            result = score_with_vader(["Some news"])

            self.assertEqual(result["score"], 0.0)
            self.assertTrue(result["reasoning"].startswith("VADER failed"))
            self.assertEqual(result["source"], "error")

    def test_score_news_empty(self):
        result = score_news("BTC", [])
        self.assertEqual(result["score"], 0.0)
        self.assertEqual(result["reasoning"], "No headlines")
        self.assertEqual(result["source"], "none")

    @patch('ollama_analyst.score_with_ollama')
    @patch('ollama_analyst.check_ollama_running')
    def test_score_news_ollama(self, mock_check, mock_score_ollama):
        mock_check.return_value = True
        mock_score_ollama.return_value = {
            "score": 0.8,
            "reasoning": "Bullish",
            "key_events": [],
            "source": "ollama",
            "model": "llama3.2:3b"
        }

        result = score_news("BTC", ["Some news"])

        self.assertEqual(result["source"], "ollama")
        self.assertEqual(result["score"], 0.8)
        mock_check.assert_called_once()
        mock_score_ollama.assert_called_once_with("BTC", ["Some news"])

    @patch('ollama_analyst.score_with_vader')
    @patch('ollama_analyst.score_with_ollama')
    @patch('ollama_analyst.check_ollama_running')
    def test_score_news_ollama_fallback(self, mock_check, mock_score_ollama, mock_score_vader):
        mock_check.return_value = True
        # score_with_ollama fails and returns None
        mock_score_ollama.return_value = None
        mock_score_vader.return_value = {
            "score": 0.2,
            "reasoning": "VADER average...",
            "key_events": [],
            "source": "vader"
        }

        with patch('sys.stdout', new_callable=io.StringIO):
            result = score_news("BTC", ["Some news"])

        self.assertEqual(result["source"], "vader")
        self.assertEqual(result["score"], 0.2)
        mock_check.assert_called_once()
        mock_score_ollama.assert_called_once_with("BTC", ["Some news"])
        mock_score_vader.assert_called_once_with(["Some news"])

    @patch('ollama_analyst.score_with_vader')
    @patch('ollama_analyst.check_ollama_running')
    def test_score_news_vader_fallback(self, mock_check, mock_score_vader):
        mock_check.return_value = False
        mock_score_vader.return_value = {
            "score": -0.1,
            "reasoning": "VADER average...",
            "key_events": [],
            "source": "vader"
        }

        with patch('sys.stdout', new_callable=io.StringIO):
            result = score_news("BTC", ["Some news"])

        self.assertEqual(result["source"], "vader")
        self.assertEqual(result["score"], -0.1)
        mock_check.assert_called_once()
        mock_score_vader.assert_called_once_with(["Some news"])

if __name__ == '__main__':
    unittest.main()
