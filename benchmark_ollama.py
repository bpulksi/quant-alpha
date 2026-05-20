import time
import json
import urllib.request
import re
from unittest.mock import patch

from ollama_analyst import score_with_ollama

def mock_urlopen(req, timeout=45):
    time.sleep(0.5) # Simulate Ollama response time
    class MockResponse:
        def read(self):
            return json.dumps({
                "response": '{"score": 0.5, "reasoning": "Looks okay", "key_events": ["Event 1"]}'
            }).encode()
    return MockResponse()

@patch('urllib.request.urlopen', side_effect=mock_urlopen)
def run_benchmark(mock_url):
    test_headlines = [
        "Bitcoin ETF sees $500M inflow as institutional demand surges",
        "Crypto market rallies amid positive macro data",
        "BTC breaks resistance at $90K on heavy volume",
    ]

    print("Running baseline...")
    start_time = time.time()
    for _ in range(5):
        score_with_ollama("BTC", test_headlines)
    end_time = time.time()
    print(f"Baseline Time: {end_time - start_time:.4f} seconds")

if __name__ == '__main__':
    run_benchmark()
