import time
import sys
import os
import concurrent.futures

def backtest_mock(asset):
    time.sleep(0.1)
    return {
        'total_trades': 10,
        'win_rate': 50.0,
        'total_pnl': 100.0,
        'total_pnl_pct': 10.0,
        'profit_factor': 1.5,
        'sharpe_ratio': 1.2,
        'sortino_ratio': 1.5,
        'max_drawdown_pct': 5.0,
        'total_fees_paid': 10.0
    }

def run_bench():
    assets = [
        "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT",
        "DOGEUSDT", "AVAXUSDT", "ADAUSDT",
        "DOTUSDT", "LINKUSDT", "MATICUSDT", "NEARUSDT",
        "APTUSDT", "SUIUSDT", "ARBUSDT", "OPUSDT",
        "TRUMPUSDT", "PEPEUSDT", "SHIBUSDT", "LTCUSDT",
    ]

    start_time = time.time()

    all_results = {}
    with concurrent.futures.ProcessPoolExecutor() as executor:
        future_to_asset = {executor.submit(backtest_mock, asset): asset for asset in assets}
        for future in concurrent.futures.as_completed(future_to_asset):
            asset = future_to_asset[future]
            try:
                r = future.result()
                all_results[asset] = r
            except Exception as e:
                print(f"  ERROR backtesting {asset}: {e}")

    end_time = time.time()
    return end_time - start_time

print(f"Time taken (ProcessPoolExecutor): {run_bench():.2f}s")
