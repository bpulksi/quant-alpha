"""
Ensemble Models & Advanced CNN Trading Extensions
==================================================
Production-ready extensions for the CNN trading system:
  - EnsembleSignalPredictor  -- combine CNN + technical indicator signals
  - RiskManager              -- ATR-based position sizing and stop levels
  - RealTimeSignalGenerator  -- single-call signal from latest OHLCV data
  - ModelManager             -- save/load trained Keras models and scalers
  - PerformanceAnalyzer      -- detailed trade statistics and JSON report

CLI:
  python ensemble_models.py --demo    # run with synthetic data
"""

import json
import pickle
from datetime import datetime
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

# ============================================================================
# 1. ENSEMBLE MODELS
# ============================================================================

class EnsembleSignalPredictor:
    """Combine CNN predictions with traditional technical indicator signals."""

    def __init__(self, cnn_weight: float = 0.6):
        """
        Args:
            cnn_weight: Weight for CNN predictions (0-1).
                        Remaining weight goes to technical rules.
        """
        self.cnn_weight = cnn_weight
        self.technical_weight = 1 - cnn_weight

    def get_technical_signal(self, df: pd.DataFrame) -> np.ndarray:
        """
        Rule-based signals derived from RSI, SMA-50, and MACD.

        BUY  -- RSI < 30 AND Close > SMA50 AND MACD > Signal line
        SELL -- RSI > 70 AND Close < SMA50 AND MACD < Signal line
        HOLD -- otherwise

        Returns:
            Integer array where 0=HOLD, 1=BUY, 2=SELL.
        """
        signals = []
        for _, row in df.iterrows():
            rsi = row.get('rsi', 50)
            close = row['close']
            sma50 = row.get('sma_50', close)
            macd = row.get('macd', 0)
            macd_signal = row.get('macd_signal', 0)

            if rsi < 30 and close > sma50 and macd > macd_signal:
                signals.append(1)
            elif rsi > 70 and close < sma50 and macd < macd_signal:
                signals.append(2)
            else:
                signals.append(0)

        return np.array(signals)

    def ensemble_predict(
        self,
        cnn_predictions: np.ndarray,
        technical_signals: np.ndarray,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Weighted combination of CNN class probabilities and rule-based signals.

        Args:
            cnn_predictions:   CNN output probabilities, shape (N, 3).
            technical_signals: Integer signals from get_technical_signal, shape (N,).

        Returns:
            (final_signals, confidence_scores) -- both shape (N,).
        """
        tech_probs = np.zeros_like(cnn_predictions)
        for i, signal in enumerate(technical_signals):
            tech_probs[i, int(signal)] = 1.0

        ensemble_probs = (
            self.cnn_weight * cnn_predictions
            + self.technical_weight * tech_probs
        )

        final_signals = np.argmax(ensemble_probs, axis=1)
        confidence = np.max(ensemble_probs, axis=1)
        return final_signals, confidence


# ============================================================================
# 2. RISK MANAGEMENT
# ============================================================================

class RiskManager:
    """ATR-based position sizing and stop/target calculation."""

    def __init__(self, account_balance: float, max_risk_per_trade: float = 0.02):
        """
        Args:
            account_balance:    Total trading capital in account currency.
            max_risk_per_trade: Maximum fraction of capital to risk per trade.
        """
        self.account_balance = account_balance
        self.max_risk_per_trade = max_risk_per_trade

    def calculate_position_size(
        self,
        entry_price: float,
        stop_loss_price: float,
        signal_confidence: float,
    ) -> float:
        """
        Fixed-fractional position size scaled by signal confidence.

        Returns:
            Number of units to trade.
        """
        risk_amount = self.account_balance * self.max_risk_per_trade
        risk_per_unit = abs(entry_price - stop_loss_price)
        if risk_per_unit == 0:
            return 0.0
        return (risk_amount / risk_per_unit) * signal_confidence

    def calculate_stops_and_targets(
        self,
        entry_price: float,
        atr: float,
        direction: str = 'long',
    ) -> Dict[str, float]:
        """
        ATR-based stop-loss and three take-profit levels (2×, 3×, 5× ATR).

        Args:
            entry_price: Trade entry price.
            atr:         Average True Range at entry.
            direction:   'long' or 'short'.

        Returns:
            Dict with keys: entry, stop_loss, take_profit_1/2/3.
        """
        if direction == 'long':
            return {
                'entry': entry_price,
                'stop_loss': entry_price - 2 * atr,
                'take_profit_1': entry_price + 2 * atr,
                'take_profit_2': entry_price + 3 * atr,
                'take_profit_3': entry_price + 5 * atr,
            }
        return {
            'entry': entry_price,
            'stop_loss': entry_price + 2 * atr,
            'take_profit_1': entry_price - 2 * atr,
            'take_profit_2': entry_price - 3 * atr,
            'take_profit_3': entry_price - 5 * atr,
        }


# ============================================================================
# 3. REAL-TIME SIGNAL GENERATOR
# ============================================================================

class RealTimeSignalGenerator:
    """Wrap a trained CNN to produce actionable signals from latest OHLCV data."""

    SIGNAL_NAMES = {0: 'HOLD', 1: 'BUY', 2: 'SELL'}

    def __init__(self, model, lookback: int = 50, image_size: Tuple[int, int] = (224, 224)):
        """
        Args:
            model:      Trained Keras CNN model.
            lookback:   Candles used when generating the chart image.
            image_size: (width, height) passed to the chart renderer.
        """
        self.model = model
        self.lookback = lookback
        self.image_size = image_size

    def generate_signal(
        self,
        df: pd.DataFrame,
        ensemble_predictor: EnsembleSignalPredictor = None,
        confidence_threshold: float = 0.6,
    ) -> Dict:
        """
        Produce a trading signal from the latest rows in *df*.

        Args:
            df:                   DataFrame with OHLCV + indicator columns.
            ensemble_predictor:   If provided, blend CNN with technical rules.
            confidence_threshold: Minimum ensemble confidence to act on.

        Returns:
            Dict containing signal, confidence, entry price, indicator snapshot.
        """
        img = self._create_chart_image(df)

        import numpy as _np
        img_array = _np.array(img) / 255.0
        img_array = _np.expand_dims(img_array, axis=0)

        cnn_pred = self.model.predict(img_array, verbose=0)[0]
        cnn_signal = int(_np.argmax(cnn_pred))
        cnn_confidence = float(_np.max(cnn_pred))

        if ensemble_predictor is not None:
            tech_signal = ensemble_predictor.get_technical_signal(df.iloc[-1:])
            final_signal_arr, final_conf_arr = ensemble_predictor.ensemble_predict(
                cnn_pred.reshape(1, -1), tech_signal
            )
            final_signal = int(final_signal_arr[0])
            final_confidence = float(final_conf_arr[0])
        else:
            final_signal = cnn_signal
            final_confidence = cnn_confidence

        latest = df.iloc[-1]
        entry_price = float(latest['close'])
        atr = float(latest.get('atr', 0))

        return {
            'timestamp': latest.get('timestamp', datetime.now()),
            'signal': self.SIGNAL_NAMES[final_signal],
            'signal_code': final_signal,
            'confidence': final_confidence,
            'passes_threshold': final_confidence >= confidence_threshold,
            'entry_price': entry_price,
            'atr': atr,
            'cnn_pred_probs': {
                'hold': float(cnn_pred[0]),
                'buy': float(cnn_pred[1]),
                'sell': float(cnn_pred[2]),
            },
            'indicators': {
                'rsi': float(latest.get('rsi', float('nan'))),
                'macd': float(latest.get('macd', float('nan'))),
                'close': entry_price,
                'sma20': float(latest.get('sma_20', float('nan'))),
                'sma50': float(latest.get('sma_50', float('nan'))),
            },
        }

    def _create_chart_image(self, df: pd.DataFrame):
        """
        Render the last *lookback* candles as a PIL Image.
        Override or replace with ChartGenerator.generate_chart_image from the
        main CNN module when integrating into the full pipeline.
        """
        from PIL import Image as _Image
        # Placeholder: returns a blank image; replace with real chart renderer.
        return _Image.new('RGB', self.image_size, color=(255, 255, 255))


# ============================================================================
# 4. MODEL PERSISTENCE
# ============================================================================

class ModelManager:
    """Thin wrappers around Keras save/load and pickle for scalers."""

    @staticmethod
    def save_model(model, filepath: str) -> None:
        model.save(filepath)
        print(f"Model saved to {filepath}")

    @staticmethod
    def load_model(filepath: str):
        from tensorflow import keras
        model = keras.models.load_model(filepath)
        print(f"Model loaded from {filepath}")
        return model

    @staticmethod
    def save_scaler(scaler, filepath: str) -> None:
        with open(filepath, 'wb') as f:
            pickle.dump(scaler, f)
        print(f"Scaler saved to {filepath}")

    @staticmethod
    def load_scaler(filepath: str):
        with open(filepath, 'rb') as f:
            scaler = pickle.load(f)
        print(f"Scaler loaded from {filepath}")
        return scaler


# ============================================================================
# 5. PERFORMANCE ANALYSIS
# ============================================================================

class PerformanceAnalyzer:
    """Compute trade-level statistics and emit a JSON report."""

    @staticmethod
    def analyze_trades(trades: List[Dict], df: pd.DataFrame) -> Dict:
        """
        Args:
            trades: List of trade dicts; each must contain a 'profit' key.
            df:     Price DataFrame (reserved for future equity-curve metrics).

        Returns:
            Dict of aggregate statistics, or {'error': 'No trades'} if empty.
        """
        if not trades:
            return {'error': 'No trades'}

        returns = np.array([t['profit'] for t in trades if 'profit' in t])
        if returns.size == 0:
            return {'error': 'No profit data in trades'}

        gross_profit = returns[returns > 0].sum()
        gross_loss = abs(returns[returns < 0].sum())

        return {
            'num_trades': len(trades),
            'winning_trades': int((returns > 0).sum()),
            'losing_trades': int((returns < 0).sum()),
            'win_rate': float((returns > 0).sum() / len(returns)),
            'avg_return': float(returns.mean()),
            'median_return': float(np.median(returns)),
            'std_return': float(returns.std()),
            'best_trade': float(returns.max()),
            'worst_trade': float(returns.min()),
            'profit_factor': float(gross_profit / gross_loss) if gross_loss > 0 else float('inf'),
        }

    @staticmethod
    def generate_report(
        backtest_results: Dict,
        trade_analysis: Dict,
        output_file: str = 'trading_report.json',
    ) -> str:
        """
        Write a combined backtest + trade-analysis report to *output_file*.

        Returns:
            Path of the written file.
        """
        report = {
            'timestamp': datetime.now().isoformat(),
            'backtest_results': backtest_results,
            'trade_analysis': trade_analysis,
            'summary': {
                'total_return': backtest_results.get('total_return', 0),
                'sharpe_ratio': backtest_results.get('sharpe_ratio', 0),
                'win_rate': trade_analysis.get('win_rate', 0),
                'profit_factor': trade_analysis.get('profit_factor', 0),
            },
        }
        with open(output_file, 'w') as f:
            json.dump(report, f, indent=2, default=str)
        return output_file


# ============================================================================
# 6. DEMO (python ensemble_models.py --demo)
# ============================================================================

def _run_demo():
    """Smoke-test all components with synthetic data (no trained model needed)."""
    print("=== Ensemble Models Demo ===\n")

    # Synthetic OHLCV + indicator data
    rng = np.random.default_rng(42)
    n = 60
    close = 100 + rng.standard_normal(n).cumsum()
    df = pd.DataFrame({
        'close': close,
        'rsi': rng.uniform(20, 80, n),
        'sma_50': close - rng.uniform(-2, 2, n),
        'macd': rng.standard_normal(n) * 0.5,
        'macd_signal': rng.standard_normal(n) * 0.4,
        'atr': rng.uniform(0.5, 2.0, n),
    })

    # 1. Technical signals
    ep = EnsembleSignalPredictor(cnn_weight=0.7)
    tech = ep.get_technical_signal(df)
    print(f"Technical signals (last 10): {tech[-10:]}")

    # 2. Ensemble with fake CNN probs
    fake_cnn = rng.dirichlet(np.ones(3), size=n)
    signals, conf = ep.ensemble_predict(fake_cnn, tech)
    print(f"Ensemble signals  (last 10): {signals[-10:]}")
    print(f"Confidence        (last 10): {np.round(conf[-10:], 3)}\n")

    # 3. Risk manager
    rm = RiskManager(account_balance=10_000, max_risk_per_trade=0.02)
    entry, atr = float(close[-1]), float(df['atr'].iloc[-1])
    stop = entry - 2 * atr
    size = rm.calculate_position_size(entry, stop, float(conf[-1]))
    stops = rm.calculate_stops_and_targets(entry, atr, direction='long')
    print(f"Entry:         ${entry:.2f}")
    print(f"Position size: {size:.4f} units")
    print(f"Stop/targets:  {stops}\n")

    # 4. Performance analyzer
    trades = [{'profit': rng.normal(0.5, 1.0)} for _ in range(30)]
    analysis = PerformanceAnalyzer.analyze_trades(trades, df)
    print("Trade analysis:")
    for k, v in analysis.items():
        print(f"  {k}: {v}")

    report_path = PerformanceAnalyzer.generate_report(
        backtest_results={'total_return': 0.12, 'sharpe_ratio': 1.4},
        trade_analysis=analysis,
        output_file='/tmp/demo_trading_report.json',
    )
    print(f"\nReport written to {report_path}")


if __name__ == '__main__':
    import sys
    if '--demo' in sys.argv:
        _run_demo()
    else:
        print("Usage: python ensemble_models.py --demo")
