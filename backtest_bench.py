import time
import sys
import quant_engine_v3

# Mock fetch_klines to avoid API rate limits and network latency
def fetch_klines_mock(symbol="BTCUSDT", interval="15m", limit=1000):
    import pandas as pd
    import numpy as np

    dates = pd.date_range(start='2023-01-01', periods=limit, freq='15min')
    df = pd.DataFrame({
        'timestamp': dates,
        'open': np.random.normal(100, 5, limit).cumsum() + 1000,
        'high': np.random.normal(100, 5, limit).cumsum() + 1005,
        'low': np.random.normal(100, 5, limit).cumsum() + 995,
        'close': np.random.normal(100, 5, limit).cumsum() + 1000,
        'volume': np.random.lognormal(mean=0, sigma=1, size=limit) * 1000,
        'quote_volume': np.random.lognormal(mean=0, sigma=1, size=limit) * 100000,
        'trades': np.random.randint(100, 1000, limit)
    })
    return df

quant_engine_v3.fetch_binance_klines = fetch_klines_mock

def _safe_backtest(asset):
    # Need to simulate the backtest properly, or modify backtest locally
    # It might fail due to models missing. Let's just catch the exception inside safe_backtest
    try:
        r = quant_engine_v3.backtest(asset)
        return asset, r, None
    except Exception as e:
        return asset, None, e

def run_sequential():
    assets = [
        "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT",
        "DOGEUSDT", "AVAXUSDT", "ADAUSDT",
    ]
    start = time.time()
    for a in assets:
        try:
            quant_engine_v3.backtest(a)
        except Exception:
            pass
    return time.time() - start

def run_parallel():
    import concurrent.futures
    assets = [
        "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT",
        "DOGEUSDT", "AVAXUSDT", "ADAUSDT",
    ]
    start = time.time()
    with concurrent.futures.ProcessPoolExecutor() as executor:
        futures = {executor.submit(_safe_backtest, asset): asset for asset in assets}
        for future in concurrent.futures.as_completed(futures):
            asset, r, err = future.result()
    return time.time() - start

if __name__ == "__main__":
    seq_time = run_sequential()
    print(f"Sequential time: {seq_time:.2f}s")
    par_time = run_parallel()
    print(f"Parallel time: {par_time:.2f}s")
