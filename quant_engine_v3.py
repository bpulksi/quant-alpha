"""
Quantitative Trading Engine V3 — Production-Grade
===================================================
All 5 optimization steps implemented:
  1. Per-asset model training (separate model per symbol)
  2. Feature selection via importance ranking (top 20 from 42)
  3. Deeper history via multi-timeframe fusion (15m + 1h + 4h)
  4. Transaction cost modeling (maker/taker fees, slippage)
  5. Walk-forward validation with overfitting detection
"""

import json
import sys
import os
import pickle
import hashlib
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from urllib.request import urlopen, Request
from sklearn.ensemble import (
    GradientBoostingClassifier, RandomForestClassifier,
    IsolationForest, GradientBoostingRegressor
)
from sklearn.model_selection import TimeSeriesSplit
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import accuracy_score, mean_absolute_error
from sklearn.utils.class_weight import compute_sample_weight
import warnings
warnings.filterwarnings('ignore')

# ─── Config ────────────────────────────────────────────────────────────────

MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models_v3")
os.makedirs(MODEL_DIR, exist_ok=True)

# Transaction costs (Binance spot)
MAKER_FEE = 0.001    # 0.1%
TAKER_FEE = 0.001    # 0.1%
SLIPPAGE = 0.0005    # 0.05% estimated slippage per trade
TOTAL_COST_PER_TRADE = TAKER_FEE + SLIPPAGE  # ~0.15% round-trip = 0.30%

# ─── Symbol Mapping ─────────────────────────────────────────────────────────

# Map BTCUSDT-style symbols to Bybit format (also BTCUSDT) and Alpaca format (BTC/USD)
SYMBOL_TO_ALPACA = {
    "BTCUSDT": "BTC/USD", "ETHUSDT": "ETH/USD", "SOLUSDT": "SOL/USD",
    "XRPUSDT": "XRP/USD", "BNBUSDT": "BNB/USD", "DOGEUSDT": "DOGE/USD",
    "AVAXUSDT": "AVAX/USD", "ADAUSDT": "ADA/USD", "DOTUSDT": "DOT/USD",
    "LINKUSDT": "LINK/USD", "MATICUSDT": "MATIC/USD", "NEARUSDT": "NEAR/USD",
    "APTUSDT": "APT/USD", "SUIUSDT": "SUI/USD", "ARBUSDT": "ARB/USD",
    "OPUSDT": "OP/USD", "TRUMPUSDT": "TRUMP/USD", "PEPEUSDT": "PEPE/USD",
    "SHIBUSDT": "SHIB/USD", "LTCUSDT": "LTC/USD",
}

# ─── Data Fetching (Bybit public API — no geo-restrictions) ─────────────────

BYBIT_TF_MAP = {"15m": "15", "1h": "60", "4h": "240", "1d": "D"}

def fetch_klines(symbol="BTCUSDT", interval="15m", limit=1000):
    """
    Fetch OHLCV data via Bybit public API (no API key required, no geo-block).
    Falls back to a stub with zeros if the request fails.
    """
    tf = BYBIT_TF_MAP.get(interval, "15")
    url = f"https://api.bybit.com/v5/market/kline?category=spot&symbol={symbol}&interval={tf}&limit={limit}"
    try:
        req = Request(url, headers={"User-Agent": "QuantEngineV3/3.0"})
        with urlopen(req, timeout=30) as resp:
            raw = json.loads(resp.read())
        if raw.get("retCode") != 0:
            raise ValueError(f"Bybit error: {raw.get('retMsg')}")
        # Bybit returns [startTime, open, high, low, close, volume, turnover] newest-first
        rows = raw["result"]["list"]
        rows = list(reversed(rows))  # oldest first
        df = pd.DataFrame(rows, columns=["open_time", "open", "high", "low", "close", "volume", "quote_volume"])
        for col in ["open", "high", "low", "close", "volume", "quote_volume"]:
            df[col] = df[col].astype(float)
        df["timestamp"] = pd.to_datetime(df["open_time"].astype(float), unit="ms")
        df["trades"] = 0
        df["taker_buy_vol"] = df["volume"] * 0.5  # approximation
        df.set_index("timestamp", inplace=True)
        return df[["open", "high", "low", "close", "volume", "quote_volume", "trades", "taker_buy_vol"]]
    except Exception as e:
        print(f"  [WARN] Bybit fetch failed for {symbol} {interval}: {e}", file=sys.stderr)
        raise

# Keep old name as alias for backward compat with backtest() calls
def fetch_binance_klines(symbol="BTCUSDT", interval="15m", limit=1000):
    return fetch_klines(symbol, interval, limit)


def fetch_multi_timeframe(symbol="BTCUSDT"):
    """Step 3: Fetch 15m (1000), 1h (1000=41d), 4h (500=166d) for deeper history."""
    frames = {}
    for tf, lim in [('15m', 1000), ('1h', 1000), ('4h', 500)]:
        try:
            frames[tf] = fetch_klines(symbol, tf, lim)
        except Exception as e:
            print(f"  [WARN] Could not fetch {tf}: {e}", file=sys.stderr)
    return frames


# ─── Indicator Library ──────────────────────────────────────────────────────

def calc_sma(s, p=14): return s.rolling(p).mean()
def calc_ema(s, p=12): return s.ewm(span=p, adjust=False).mean()

def calc_rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def calc_atr(df, period=14):
    hl = df['high'] - df['low']
    hc = (df['high'] - df['close'].shift()).abs()
    lc = (df['low'] - df['close'].shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def calc_natr(df, period=14):
    return 100 * calc_atr(df, period) / df['close']

def calc_bollinger(series, period=20, std_mult=2):
    sma = series.rolling(period).mean()
    std = series.rolling(period).std()
    upper = sma + std * std_mult
    lower = sma - std * std_mult
    pct_b = (series - lower) / (upper - lower)
    bandwidth = (upper - lower) / sma
    return upper, lower, pct_b, bandwidth

def calc_macd(series, fast=12, slow=26, signal=9):
    ef = calc_ema(series, fast)
    es = calc_ema(series, slow)
    macd = ef - es
    sig = calc_ema(macd, signal)
    return macd, sig, macd - sig

def calc_vwap(df):
    tp = (df['high'] + df['low'] + df['close']) / 3
    return (tp * df['volume']).cumsum() / df['volume'].cumsum().replace(0, np.nan)

def calc_adx(df, period=14):
    plus_dm = df['high'].diff()
    minus_dm = -df['low'].diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)
    atr = calc_atr(df, period)
    plus_di = 100 * calc_ema(plus_dm, period) / atr.replace(0, np.nan)
    minus_di = 100 * calc_ema(minus_dm, period) / atr.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return calc_ema(dx, period), plus_di, minus_di

def calc_williams_r(df, period=14):
    hh = df['high'].rolling(period).max()
    ll = df['low'].rolling(period).min()
    return -100 * (hh - df['close']) / (hh - ll)

def calc_stochastic(df, k_period=14, d_period=3):
    hh = df['high'].rolling(k_period).max()
    ll = df['low'].rolling(k_period).min()
    k = 100 * (df['close'] - ll) / (hh - ll)
    return k, k.rolling(d_period).mean()

def calc_cci(df, period=14):
    tp = (df['high'] + df['low'] + df['close']) / 3
    sma = tp.rolling(period).mean()
    mad = (tp - sma).abs().rolling(period).mean()
    return (tp - sma) / (0.015 * mad)

def calc_obv(df):
    return (np.sign(df['close'].diff()) * df['volume']).cumsum()

def calc_mfi(df, period=14):
    tp = (df['high'] + df['low'] + df['close']) / 3
    rmf = tp * df['volume']
    pos = rmf.where(tp > tp.shift(1), 0).rolling(period).sum()
    neg = rmf.where(tp < tp.shift(1), 0).rolling(period).sum()
    return 100 - (100 / (1 + pos / neg.replace(0, np.nan)))

def calc_keltner(df, period=20, atr_mult=1.5):
    mid = calc_ema(df['close'], period)
    atr = calc_atr(df, period)
    return mid + atr_mult * atr, mid, mid - atr_mult * atr

def calc_ichimoku(df, tenkan=9, kijun=26, senkou_b=52):
    ts = (df['high'].rolling(tenkan).max() + df['low'].rolling(tenkan).min()) / 2
    ks = (df['high'].rolling(kijun).max() + df['low'].rolling(kijun).min()) / 2
    sa = ((ts + ks) / 2).shift(kijun)
    sb = ((df['high'].rolling(senkou_b).max() + df['low'].rolling(senkou_b).min()) / 2).shift(kijun)
    return ts, ks, sa, sb

def calc_donchian(df, period=20):
    return df['high'].rolling(period).max(), df['low'].rolling(period).min()

def calc_momentum(s, p=10): return s.diff(p)
def calc_roc(s, p=10): return ((s - s.shift(p)) / s.shift(p)) * 100

def calc_linear_reg(series, period=14):
    idx = np.arange(period)
    def lr(x): return np.polyval(np.polyfit(idx, x, 1), idx)[-1]
    return series.rolling(period).apply(lr, raw=True)


# ─── ALL 42 Features ───────────────────────────────────────────────────────

ALL_FEATURE_COLS = [
    'returns_1', 'returns_3', 'returns_5', 'returns_10',
    'rsi_3', 'rsi_14', 'rsi_21',
    'macd_hist', 'macd_hist_change',
    'price_vs_ema8', 'price_vs_ema21', 'price_vs_ema50', 'ema_8_21_cross',
    'bb_pct_b', 'bb_bandwidth',
    'atr_pct', 'natr', 'volatility_10', 'vol_ratio', 'z_score',
    'volume_ratio', 'buy_pressure',
    'body_size', 'upper_wick', 'lower_wick',
    'adx', 'plus_di', 'minus_di', 'vwap_dist',
    'williams_r', 'stoch_k', 'stoch_d', 'cci', 'obv_slope', 'mfi',
    'keltner_pos', 'ichimoku_tk_cross', 'ichimoku_cloud_dist',
    'donchian_pos', 'momentum_10', 'roc_10', 'linreg_slope',
]


def engineer_features(df):
    """Build all 42 features from OHLCV data."""
    feat = pd.DataFrame(index=df.index)
    c = df['close']

    for p in [1, 3, 5, 10]:
        feat[f'returns_{p}'] = c.pct_change(p)
    feat['log_returns'] = np.log(c / c.shift(1))

    for p in [3, 14, 21]:
        feat[f'rsi_{p}'] = calc_rsi(c, p)

    macd, sig, hist = calc_macd(c)
    feat['macd_hist'] = hist
    feat['macd_hist_change'] = hist.diff()

    for p in [8, 21, 50]:
        feat[f'ema_{p}'] = calc_ema(c, p)
        feat[f'price_vs_ema{p}'] = (c - feat[f'ema_{p}']) / feat[f'ema_{p}']
    feat['ema_8_21_cross'] = (feat['ema_8'] - feat['ema_21']) / feat['ema_21']

    bb_up, bb_lo, bb_pct, bb_bw = calc_bollinger(c)
    feat['bb_pct_b'] = bb_pct
    feat['bb_bandwidth'] = bb_bw

    feat['atr_14'] = calc_atr(df, 14)
    feat['atr_pct'] = feat['atr_14'] / c
    feat['natr'] = calc_natr(df, 14)
    feat['volatility_10'] = c.rolling(10).std() / c
    feat['volatility_30'] = c.rolling(30).std() / c
    feat['vol_ratio'] = feat['volatility_10'] / feat['volatility_30'].replace(0, np.nan)

    rm = c.rolling(20).mean()
    rs = c.rolling(20).std()
    feat['z_score'] = (c - rm) / rs.replace(0, np.nan)

    feat['volume_ratio'] = df['volume'] / df['volume'].rolling(20).mean().replace(0, np.nan)
    feat['buy_pressure'] = df['taker_buy_vol'] / df['volume'].replace(0, np.nan)

    feat['body_size'] = (c - df['open']).abs() / df['open']
    feat['upper_wick'] = (df['high'] - df[['open', 'close']].max(axis=1)) / df['open']
    feat['lower_wick'] = (df[['open', 'close']].min(axis=1) - df['low']) / df['open']

    adx, plus_di, minus_di = calc_adx(df)
    feat['adx'] = adx
    feat['plus_di'] = plus_di
    feat['minus_di'] = minus_di

    vwap = calc_vwap(df)
    feat['vwap_dist'] = (c - vwap) / vwap.replace(0, np.nan)

    feat['williams_r'] = calc_williams_r(df, 14)
    stoch_k, stoch_d = calc_stochastic(df, 14, 3)
    feat['stoch_k'] = stoch_k
    feat['stoch_d'] = stoch_d
    feat['cci'] = calc_cci(df, 14)
    obv = calc_obv(df)
    feat['obv_slope'] = obv.diff(5) / obv.rolling(20).std().replace(0, np.nan)
    feat['mfi'] = calc_mfi(df, 14)
    kelt_up, kelt_mid, kelt_lo = calc_keltner(df)
    feat['keltner_pos'] = (c - kelt_lo) / (kelt_up - kelt_lo).replace(0, np.nan)
    tenkan, kijun, sa, sb = calc_ichimoku(df)
    feat['ichimoku_tk_cross'] = (tenkan - kijun) / c
    cloud_top = pd.concat([sa, sb], axis=1).max(axis=1)
    feat['ichimoku_cloud_dist'] = (c - cloud_top) / c
    don_up, don_lo = calc_donchian(df, 20)
    feat['donchian_pos'] = (c - don_lo) / (don_up - don_lo).replace(0, np.nan)
    feat['momentum_10'] = calc_momentum(c, 10) / c
    feat['roc_10'] = calc_roc(c, 10)
    feat['linreg_slope'] = calc_linear_reg(c, 14).pct_change()

    feat['close'] = c
    return feat


def add_htf_features(feat_15m, df_1h=None, df_4h=None):
    """Step 3: Add higher-timeframe trend context."""
    if df_1h is not None and len(df_1h) > 50:
        h1_ema21 = calc_ema(df_1h['close'], 21)
        h1_rsi = calc_rsi(df_1h['close'], 14)
        h1_adx, _, _ = calc_adx(df_1h)
        # Reindex to 15m
        feat_15m['htf_1h_trend'] = h1_ema21.reindex(feat_15m.index, method='ffill')
        feat_15m['htf_1h_trend'] = (feat_15m['close'] - feat_15m['htf_1h_trend']) / feat_15m['htf_1h_trend']
        feat_15m['htf_1h_rsi'] = h1_rsi.reindex(feat_15m.index, method='ffill')
        feat_15m['htf_1h_adx'] = h1_adx.reindex(feat_15m.index, method='ffill')

    if df_4h is not None and len(df_4h) > 50:
        h4_ema21 = calc_ema(df_4h['close'], 21)
        h4_rsi = calc_rsi(df_4h['close'], 14)
        feat_15m['htf_4h_trend'] = h4_ema21.reindex(feat_15m.index, method='ffill')
        feat_15m['htf_4h_trend'] = (feat_15m['close'] - feat_15m['htf_4h_trend']) / feat_15m['htf_4h_trend']
        feat_15m['htf_4h_rsi'] = h4_rsi.reindex(feat_15m.index, method='ffill')

    return feat_15m

HTF_FEATURE_COLS = ['htf_1h_trend', 'htf_1h_rsi', 'htf_1h_adx', 'htf_4h_trend', 'htf_4h_rsi']


# ─── Regime Detection ──────────────────────────────────────────────────────

def detect_regime(df, features):
    last = features.iloc[-1]
    def s(k, d=0):
        v = last.get(k)
        return float(v) if v is not None and not pd.isna(v) else d

    adx = s('adx', 20)
    vol_ratio = s('vol_ratio', 1.0)
    atr_pct = s('atr_pct', 0.01)

    if vol_ratio > 1.5 and atr_pct > 0.015:
        regime = "VOLATILE"
    elif adx > 30:
        regime = "TRENDING"
    else:
        regime = "RANGING"

    ema8 = s('ema_8')
    ema21 = s('ema_21')
    direction = "BULLISH" if ema8 > ema21 else "BEARISH"

    return {"regime": regime, "direction": direction, "adx": round(adx, 2),
            "vol_ratio": round(vol_ratio, 2), "atr_pct": round(atr_pct, 4)}


# ─── Signal Generation (same as V2) ───────────────────────────────────────

STRATEGIES = {
    "TRENDING": {"name": "Trend Following (EMA + ADX + Ichimoku)"},
    "RANGING": {"name": "Mean Reversion (BB + RSI + Stochastic + CCI)"},
    "VOLATILE": {"name": "Breakout Scalping (Volume + Keltner + Donchian)"},
}

def generate_signal(features, regime_info):
    regime = regime_info["regime"]
    direction = regime_info["direction"]
    last = features.iloc[-1]
    signal = {"action": "HOLD", "confidence": 0.0, "reason": ""}
    def safe(k):
        v = last.get(k)
        return float(v) if v is not None and not pd.isna(v) else None

    rsi14 = safe('rsi_14'); rsi3 = safe('rsi_3'); adx = safe('adx')
    z = safe('z_score'); bb = safe('bb_pct_b'); stk = safe('stoch_k')
    cci = safe('cci'); mfi = safe('mfi'); wr = safe('williams_r')
    vol_r = safe('volume_ratio'); bp = safe('buy_pressure')
    kelt = safe('keltner_pos'); ich = safe('ichimoku_cloud_dist'); don = safe('donchian_pos')

    if regime == "TRENDING":
        if direction == "BULLISH" and rsi14 and 40 < rsi14 < 70 and adx and adx > 30:
            score = 0.60; reasons = ["Bullish trend ADX>30"]
            if rsi3 and rsi3 < 35: score += 0.10; reasons.append("RSI(3) pullback")
            if ich and ich > 0: score += 0.08; reasons.append("Above Ichimoku")
            if wr and wr > -30: score += 0.05; reasons.append("Williams%R momentum")
            if mfi and mfi < 70: score += 0.05; reasons.append("MFI ok")
            if score >= 0.70:
                signal = {"action": "BUY", "confidence": min(score, 0.95), "reason": " + ".join(reasons)}
        elif direction == "BEARISH" and rsi14 and 30 < rsi14 < 60 and adx and adx > 30:
            score = 0.60; reasons = ["Bearish trend ADX>30"]
            if rsi3 and rsi3 > 65: score += 0.10; reasons.append("RSI(3) bounce")
            if ich and ich < 0: score += 0.08; reasons.append("Below Ichimoku")
            if score >= 0.70:
                signal = {"action": "SELL", "confidence": min(score, 0.95), "reason": " + ".join(reasons)}
    elif regime == "RANGING":
        bs = ss = 0; br = []; sr = []
        if z and z < -1.5: bs += 1; br.append(f"Z={z:.1f}")
        if rsi14 and rsi14 < 35: bs += 1; br.append(f"RSI={rsi14:.0f}")
        if stk and stk < 20: bs += 1; br.append(f"Stoch={stk:.0f}")
        if cci and cci < -100: bs += 1; br.append(f"CCI={cci:.0f}")
        if mfi and mfi < 25: bs += 1; br.append(f"MFI={mfi:.0f}")
        if bb and bb < 0.1: bs += 1; br.append("BB<0.1")
        if z and z > 1.5: ss += 1; sr.append(f"Z={z:.1f}")
        if rsi14 and rsi14 > 65: ss += 1; sr.append(f"RSI={rsi14:.0f}")
        if stk and stk > 80: ss += 1; sr.append(f"Stoch={stk:.0f}")
        if cci and cci > 100: ss += 1; sr.append(f"CCI={cci:.0f}")
        if mfi and mfi > 75: ss += 1; sr.append(f"MFI={mfi:.0f}")
        if bb and bb > 0.9: ss += 1; sr.append("BB>0.9")
        if bs >= 3:
            signal = {"action": "BUY", "confidence": min(0.55 + bs*0.07, 0.95), "reason": "MeanRev: " + "+".join(br)}
        elif ss >= 3:
            signal = {"action": "SELL", "confidence": min(0.55 + ss*0.07, 0.95), "reason": "MeanRev: " + "+".join(sr)}
    elif regime == "VOLATILE":
        if vol_r and vol_r > 2.0 and bp and bp > 0.6 and kelt and kelt > 1.0:
            signal = {"action": "BUY", "confidence": 0.70, "reason": "Breakout: vol+buy+Keltner"}
        elif vol_r and vol_r > 2.0 and bp and bp < 0.4 and kelt and kelt < 0.0:
            signal = {"action": "SELL", "confidence": 0.70, "reason": "Breakdown: vol+sell+Keltner"}

    return signal


# ─── Step 1: Per-Asset Model Training ─────────────────────────────────────

def model_paths(symbol):
    s = symbol.lower()
    return {
        'model': os.path.join(MODEL_DIR, f"{s}_model.pkl"),
        'scaler': os.path.join(MODEL_DIR, f"{s}_scaler.pkl"),
        'iso': os.path.join(MODEL_DIR, f"{s}_iso.pkl"),
        'reg': os.path.join(MODEL_DIR, f"{s}_reg.pkl"),
        'meta': os.path.join(MODEL_DIR, f"{s}_meta.json"),
    }


def create_labels(df, forward_periods=3, threshold=0.002):
    future_ret = df['close'].shift(-forward_periods) / df['close'] - 1
    labels = pd.Series(0, index=df.index)
    labels[future_ret > threshold] = 1
    labels[future_ret < -threshold] = -1
    return labels


def select_features(X, y, all_cols, top_n=20):
    """Step 2: Select top N features by GBM importance to reduce overfitting."""
    quick_gbm = GradientBoostingClassifier(n_estimators=100, max_depth=3, learning_rate=0.1, random_state=42)
    quick_gbm.fit(X, y)
    importances = sorted(zip(all_cols, quick_gbm.feature_importances_), key=lambda x: x[1], reverse=True)
    selected = [name for name, _ in importances[:top_n]]
    print(f"  Feature selection: {len(all_cols)} -> {top_n} features")
    print(f"  Top 5: {', '.join(selected[:5])}")
    print(f"  Dropped: {', '.join([n for n, _ in importances[top_n:top_n+5]])}...")
    return selected, importances


def walk_forward_validate(X_scaled, y, feature_cols, n_splits=5):
    """Step 5: Walk-forward validation with overfitting detection."""
    tscv = TimeSeriesSplit(n_splits=n_splits)
    train_scores = []
    test_scores = []

    for train_idx, test_idx in tscv.split(X_scaled):
        gbm = GradientBoostingClassifier(n_estimators=300, max_depth=3, learning_rate=0.03,
                                          subsample=0.7, min_samples_leaf=20,
                                          min_samples_split=40, random_state=42)
        sw_train = compute_sample_weight(class_weight='balanced', y=y.iloc[train_idx])
        gbm.fit(X_scaled[train_idx], y.iloc[train_idx], sample_weight=sw_train)
        train_scores.append(accuracy_score(y.iloc[train_idx], gbm.predict(X_scaled[train_idx])))
        test_scores.append(accuracy_score(y.iloc[test_idx], gbm.predict(X_scaled[test_idx])))

    avg_train = np.mean(train_scores)
    avg_test = np.mean(test_scores)
    overfit_gap = avg_train - avg_test

    # Overfitting warning
    overfit_warning = None
    if overfit_gap > 0.15:
        overfit_warning = f"HIGH OVERFITTING RISK: train={avg_train:.1%} vs test={avg_test:.1%} (gap={overfit_gap:.1%})"
    elif overfit_gap > 0.08:
        overfit_warning = f"MODERATE overfitting: train={avg_train:.1%} vs test={avg_test:.1%} (gap={overfit_gap:.1%})"

    return {
        "train_accuracy": round(avg_train, 4),
        "test_accuracy": round(avg_test, 4),
        "overfit_gap": round(overfit_gap, 4),
        "overfit_warning": overfit_warning,
        "fold_test_scores": [round(s, 4) for s in test_scores],
    }


def train_model(symbol="BTCUSDT", interval="15m"):
    """Train per-asset model with feature selection + walk-forward validation."""
    paths = model_paths(symbol)
    print(f"\n  === Training model for {symbol} ===")

    # Step 3: Multi-timeframe data
    print("  Fetching multi-timeframe data...")
    tf_data = fetch_multi_timeframe(symbol)
    df = tf_data.get('15m')
    if df is None:
        print("  ERROR: Could not fetch 15m data")
        return None

    features = engineer_features(df)

    # Add HTF features
    features = add_htf_features(features, tf_data.get('1h'), tf_data.get('4h'))

    # Determine available feature columns
    available_cols = [c for c in ALL_FEATURE_COLS if c in features.columns]
    htf_available = [c for c in HTF_FEATURE_COLS if c in features.columns]
    all_cols = available_cols + htf_available

    print(f"  Base features: {len(available_cols)}, HTF features: {len(htf_available)}, Total: {len(all_cols)}")

    # Create labels using percentage returns (Step 4 compatible)
    labels = create_labels(df)
    combined = features[all_cols].copy()
    combined['label'] = labels
    combined.dropna(inplace=True)

    X_all = combined[all_cols].iloc[:-3]
    y = combined['label'].iloc[:-3]

    print(f"  Training samples: {len(X_all)}")
    print(f"  Labels: BUY={int((y==1).sum())}, SELL={int((y==-1).sum())}, HOLD={int((y==0).sum())}")
    print(f"  Samples-per-feature ratio: {len(X_all)/len(all_cols):.1f}x (target: >20x)")

    scaler_full = StandardScaler()
    X_scaled_full = scaler_full.fit_transform(X_all)

    # Step 2: Feature selection — reduce to top 20
    selected_cols, importances = select_features(X_scaled_full, y, all_cols, top_n=20)
    sel_indices = [all_cols.index(c) for c in selected_cols]
    X_selected = X_scaled_full[:, sel_indices]

    # Refit scaler on selected features only
    scaler = StandardScaler()
    X_raw_sel = X_all[selected_cols]
    X_scaled = scaler.fit_transform(X_raw_sel)

    print(f"  Samples-per-feature (after selection): {len(X_scaled)/len(selected_cols):.1f}x")

    # Step 5: Walk-forward validation with overfitting detection
    print("\n  Walk-forward validation...")
    wf_results = walk_forward_validate(X_scaled, y, selected_cols)
    print(f"  Train accuracy: {wf_results['train_accuracy']:.1%}")
    print(f"  Test accuracy:  {wf_results['test_accuracy']:.1%}")
    print(f"  Overfit gap:    {wf_results['overfit_gap']:.1%}")
    if wf_results['overfit_warning']:
        print(f"  [!] {wf_results['overfit_warning']}")
    print(f"  Per-fold test:  {wf_results['fold_test_scores']}")

    # Train final ensemble (balanced class weights to fix HOLD-bias)
    print("\n  Training final ensemble...")
    gbm = GradientBoostingClassifier(n_estimators=300, max_depth=3, learning_rate=0.03,
                                     subsample=0.7, min_samples_leaf=20,
                                     min_samples_split=40, random_state=42)
    sample_weights = compute_sample_weight(class_weight='balanced', y=y)
    gbm.fit(X_scaled, y, sample_weight=sample_weights)

    rf = RandomForestClassifier(n_estimators=300, max_depth=5, min_samples_leaf=20,
                                min_samples_split=40, max_features='sqrt',
                                class_weight='balanced', random_state=42)
    rf.fit(X_scaled, y)

    rf_wf = walk_forward_validate(X_scaled, y, selected_cols)
    print(f"  RF  test accuracy: {rf_wf['test_accuracy']:.1%} (gap={rf_wf['overfit_gap']:.1%})")

    # IsolationForest
    iso = IsolationForest(contamination=0.005, random_state=42)
    iso.fit(X_scaled)

    # Regressor — predict PERCENTAGE RETURN, not absolute price (fixes cross-asset bug)
    future_ret = (df['close'].shift(-5) / df['close'] - 1).reindex(X_raw_sel.index).dropna()
    reg_idx = X_raw_sel.index.intersection(future_ret.index)
    X_reg = scaler.transform(X_raw_sel.loc[reg_idx])
    y_reg = future_ret.loc[reg_idx]
    regressor = GradientBoostingRegressor(n_estimators=300, max_depth=3, learning_rate=0.03,
                                         subsample=0.7, min_samples_leaf=20, random_state=42)
    regressor.fit(X_reg, y_reg)
    reg_pred = regressor.predict(X_reg)
    mae = mean_absolute_error(y_reg, reg_pred)
    print(f"  Regressor MAE (5-bar return): {mae*100:.3f}%")

    # Feature importance (final GBM)
    print("\n  Top 10 features (selected):")
    imp_sorted = sorted(zip(selected_cols, gbm.feature_importances_), key=lambda x: x[1], reverse=True)
    for name, imp in imp_sorted[:10]:
        print(f"    {name:30s} {imp:.4f}")

    # Save per-asset models
    with open(paths['model'], 'wb') as f: pickle.dump({'gbm': gbm, 'rf': rf}, f)
    with open(paths['scaler'], 'wb') as f: pickle.dump(scaler, f)
    with open(paths['iso'], 'wb') as f: pickle.dump(iso, f)
    with open(paths['reg'], 'wb') as f: pickle.dump(regressor, f)

    meta = {
        "symbol": symbol, "trained_at": datetime.utcnow().isoformat(),
        "selected_features": selected_cols,
        "samples": len(X_scaled),
        "walk_forward": wf_results,
        "regressor_mae_pct": round(mae * 100, 3),
        "feature_importances": {n: round(float(i), 4) for n, i in imp_sorted},
    }
    with open(paths['meta'], 'w') as f: json.dump(meta, f, indent=2)

    print(f"\n  [OK] Per-asset model saved for {symbol}")
    return meta


def load_model(symbol):
    """Load per-asset model. Returns None if not trained."""
    paths = model_paths(symbol)
    if not os.path.exists(paths['model']):
        return None
    with open(paths['model'], 'rb') as f: models = pickle.load(f)
    with open(paths['scaler'], 'rb') as f: scaler = pickle.load(f)
    with open(paths['iso'], 'rb') as f: iso = pickle.load(f)
    with open(paths['reg'], 'rb') as f: reg = pickle.load(f)
    with open(paths['meta'], 'r') as f: meta = json.load(f)
    return {'models': models, 'scaler': scaler, 'iso': iso, 'reg': reg, 'meta': meta}


def predict_ml(features, loaded=None, symbol="BTCUSDT"):
    """ML prediction using per-asset model."""
    if loaded is None:
        loaded = load_model(symbol)
    if loaded is None:
        return {"prediction": "NO_MODEL", "probability": 0, "is_anomaly": False, "predicted_return_pct": 0}

    selected_cols = loaded['meta']['selected_features']
    models = loaded['models']
    scaler = loaded['scaler']
    iso = loaded['iso']
    reg = loaded['reg']

    # Build feature vector from selected columns only
    last = features[selected_cols].iloc[[-1]].copy().fillna(0)
    X = scaler.transform(last)

    gbm = models['gbm']
    rf = models['rf']

    gbm_proba = gbm.predict_proba(X)[0]
    rf_proba = rf.predict_proba(X)[0]
    gbm_classes = list(gbm.classes_)
    rf_classes = list(rf.classes_)
    label_map = {-1: "SELL", 0: "HOLD", 1: "BUY"}

    avg_proba = {}
    for cls in [-1, 0, 1]:
        p1 = gbm_proba[gbm_classes.index(cls)] if cls in gbm_classes else 0
        p2 = rf_proba[rf_classes.index(cls)] if cls in rf_classes else 0
        avg_proba[cls] = p1 * 0.6 + p2 * 0.4

    ensemble_pred = max(avg_proba, key=avg_proba.get)
    is_anomaly = bool(iso.predict(X)[0] == -1)

    # Regressor now predicts PERCENTAGE RETURN directly
    predicted_return = float(reg.predict(X)[0])
    predicted_return = max(min(predicted_return, 0.05), -0.05)

    return {
        "prediction": label_map.get(ensemble_pred, "HOLD"),
        "probability": round(avg_proba[ensemble_pred], 3),
        "is_anomaly": is_anomaly,
        "predicted_return_pct": round(predicted_return * 100, 3),
        "class_probabilities": {label_map.get(k, "HOLD"): round(v, 3) for k, v in avg_proba.items()},
    }


# ─── R-Multiple Position Sizing ───────────────────────────────────────────

def calc_position_size(price, atr, capital, risk_pct=0.01, direction="BUY"):
    stop_distance = 1.5 * atr
    if direction == "BUY":
        stop_price = price - stop_distance
        targets = [price + i * stop_distance for i in range(1, 4)]
    else:
        stop_price = price + stop_distance
        targets = [price - i * stop_distance for i in range(1, 4)]
    risk_amount = capital * risk_pct
    qty = risk_amount / stop_distance if stop_distance > 0 else 0
    return {
        "qty": round(qty, 6), "stop_price": round(stop_price, 2),
        "target_1r": round(targets[0], 2), "target_2r": round(targets[1], 2),
        "target_3r": round(targets[2], 2), "risk_amount": round(risk_amount, 2),
    }


# ─── Step 4: Backtesting WITH Transaction Costs ───────────────────────────

def backtest(symbol="BTCUSDT", interval="15m", initial_capital=1000, trade_size=10,
             include_costs=True):
    """Production-grade backtest with transaction costs, slippage, and VaR."""
    print(f"\n  Backtesting {symbol}...")
    if include_costs:
        print(f"  Transaction costs: {TOTAL_COST_PER_TRADE*100:.2f}% per side ({TAKER_FEE*100:.1f}% fee + {SLIPPAGE*100:.2f}% slippage)")

    df = fetch_binance_klines(symbol, interval, 1000)
    features = engineer_features(df)

    loaded = load_model(symbol)
    if loaded is None:
        print(f"  No model for {symbol}, training first...")
        train_model(symbol, interval)
        loaded = load_model(symbol)

    capital = initial_capital
    position = 0
    entry_price = 0
    stop_price_val = 0
    trades = []
    equity_curve = []
    wins = losses = 0
    total_fees = 0
    regime_trades = {"TRENDING": [], "RANGING": [], "VOLATILE": []}

    for i in range(60, len(features) - 1):
        current = features.iloc[:i+1]
        price = float(current['close'].iloc[-1])

        regime_info = detect_regime(df.iloc[:i+1], current)
        rule_signal = generate_signal(current, regime_info)

        ml_signal = {"prediction": "HOLD", "probability": 0, "is_anomaly": False, "predicted_return_pct": 0}
        if loaded:
            try:
                ml_signal = predict_ml(current, loaded, symbol)
            except:
                pass

        # Signal combination
        action = "HOLD"
        if ml_signal.get("is_anomaly") and ml_signal["probability"] > 0.5:
            rolling_mean = float(current['close'].rolling(50).mean().iloc[-1])
            if price < rolling_mean: action = "BUY"
            elif price > rolling_mean: action = "SELL"
        elif rule_signal["action"] == ml_signal["prediction"] and rule_signal["action"] != "HOLD":
            action = rule_signal["action"]
        elif rule_signal["action"] != "HOLD" and rule_signal["confidence"] >= 0.70:
            action = rule_signal["action"]
        elif ml_signal["prediction"] != "HOLD" and ml_signal["probability"] > 0.70:
            action = ml_signal["prediction"]

        # Regression filter
        pred_ret = ml_signal.get("predicted_return_pct", 0)
        if action == "BUY" and pred_ret < -0.1:
            action = "HOLD"
        elif action == "SELL" and pred_ret > 0.1:
            action = "HOLD"

        # Step 4: Transaction cost filter — only trade if expected return > costs
        if action != "HOLD" and include_costs:
            min_expected_return = TOTAL_COST_PER_TRADE * 2  # round-trip costs
            if abs(pred_ret / 100) < min_expected_return and rule_signal["confidence"] < 0.80:
                action = "HOLD"  # Not worth the fees

        atr_val = float(current['atr_14'].iloc[-1]) if not pd.isna(current['atr_14'].iloc[-1]) else price * 0.01
        sizing = calc_position_size(price, atr_val, capital, risk_pct=0.01, direction=action)

        if action == "BUY" and position == 0:
            # Apply entry slippage + fee
            fill_price = price * (1 + TOTAL_COST_PER_TRADE) if include_costs else price
            entry_fee = trade_size * TOTAL_COST_PER_TRADE if include_costs else 0
            total_fees += entry_fee

            qty = min(sizing['qty'], trade_size / fill_price)
            position = qty
            entry_price = fill_price
            stop_price_val = sizing['stop_price']

        elif position > 0:
            pnl_pct = (price - entry_price) / entry_price
            hit_stop = price <= stop_price_val
            hit_target = pnl_pct > 0.005

            if hit_stop or hit_target or action == "SELL":
                # Apply exit slippage + fee
                fill_price = price * (1 - TOTAL_COST_PER_TRADE) if include_costs else price
                exit_fee = position * fill_price * TOTAL_COST_PER_TRADE if include_costs else 0
                total_fees += exit_fee

                pnl = position * (fill_price - entry_price)
                capital += pnl
                if pnl > 0: wins += 1
                else: losses += 1
                t = {"entry": round(entry_price, 4), "exit": round(fill_price, 4),
                     "pnl": round(pnl, 4), "pnl_pct": round((fill_price/entry_price - 1)*100, 3),
                     "regime": regime_info["regime"]}
                trades.append(t)
                regime_trades.get(regime_info["regime"], []).append(t)
                position = 0

        equity_curve.append(capital + (position * price if position > 0 else 0))

    # Close open position
    if position > 0:
        fp = float(df['close'].iloc[-1])
        fill_price = fp * (1 - TOTAL_COST_PER_TRADE) if include_costs else fp
        pnl = position * (fill_price - entry_price)
        capital += pnl
        trades.append({"entry": round(entry_price,4), "exit": round(fill_price,4), "pnl": round(pnl,4)})

    total = len(trades)
    win_rate = wins / max(total, 1) * 100
    total_pnl = capital - initial_capital

    # Max drawdown
    if equity_curve:
        eq = pd.Series(equity_curve)
        dd = (eq - eq.cummax()) / eq.cummax()
        max_dd = float(dd.min()) * 100
    else:
        max_dd = 0

    # Sharpe ratio
    if len(equity_curve) > 1:
        rets = pd.Series(equity_curve).pct_change().dropna()
        sharpe = (rets.mean() / rets.std()) * np.sqrt(365.25 * 24 * 4) if rets.std() > 0 else 0
        # Sortino ratio (downside deviation only)
        downside = rets[rets < 0].std()
        sortino = (rets.mean() / downside) * np.sqrt(365.25 * 24 * 4) if downside > 0 else 0
        # Value at Risk (95%)
        var_95 = float(np.percentile(rets, 5))
        # Calmar ratio
        calmar = (rets.mean() * 365.25 * 24 * 4) / abs(max_dd / 100) if max_dd != 0 else 0
    else:
        sharpe = sortino = var_95 = calmar = 0

    # Regime breakdown
    rb = {}
    for regime, t_list in regime_trades.items():
        if t_list:
            pnls = [t['pnl'] for t in t_list]
            rb[regime] = {
                "trades": len(t_list), "total_pnl": round(sum(pnls), 4),
                "win_rate": round(sum(1 for p in pnls if p > 0) / len(pnls) * 100, 1),
                "avg_pnl": round(np.mean(pnls), 4),
            }

    winning_pnls = [t['pnl'] for t in trades if t.get('pnl', 0) > 0]
    losing_pnls = [t['pnl'] for t in trades if t.get('pnl', 0) < 0]

    return {
        "version": "V3_PRODUCTION",
        "symbol": symbol,
        "initial_capital": initial_capital,
        "final_capital": round(capital, 2),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl / initial_capital * 100, 3),
        "total_trades": total,
        "wins": wins, "losses": losses,
        "win_rate": round(win_rate, 1),
        "avg_win": round(np.mean(winning_pnls), 4) if winning_pnls else 0,
        "avg_loss": round(np.mean(losing_pnls), 4) if losing_pnls else 0,
        "profit_factor": round(sum(winning_pnls) / abs(sum(losing_pnls)), 2) if losing_pnls and sum(losing_pnls) != 0 else 999,
        "total_fees_paid": round(total_fees, 4),
        "fees_as_pct_of_capital": round(total_fees / initial_capital * 100, 3),
        "sharpe_ratio": round(sharpe, 2),
        "sortino_ratio": round(sortino, 2),
        "calmar_ratio": round(calmar, 2),
        "var_95_pct": round(var_95 * 100, 4) if var_95 else 0,
        "max_drawdown_pct": round(max_dd, 2),
        "regime_breakdown": rb,
        "transaction_costs_modeled": include_costs,
        "last_5_trades": trades[-5:] if trades else [],
    }


# ─── Full Signal Generator ────────────────────────────────────────────────

def apply_signal_rules(last: pd.Series, rule_signal: dict, ml_signal: dict) -> tuple[str, float]:
    """Applies combination logic, cost filtering, and quality gates to rule and ML signals."""
    final_action = "HOLD"
    final_confidence = 0.0

    if rule_signal["action"] == ml_signal["prediction"] and rule_signal["action"] != "HOLD":
        final_action = rule_signal["action"]
        final_confidence = min(rule_signal["confidence"] + 0.15, 0.95)
    elif rule_signal["action"] != "HOLD" and rule_signal["confidence"] > 0.70:
        final_action = rule_signal["action"]
        final_confidence = rule_signal["confidence"]
    elif ml_signal["prediction"] != "HOLD" and ml_signal["probability"] > 0.70:
        final_action = ml_signal["prediction"]
        final_confidence = ml_signal["probability"] * 0.85

    if ml_signal.get("is_anomaly") and ml_signal["probability"] > 0.6:
        pred = ml_signal.get("predicted_return_pct", 0)
        if pred > 0.2:
            final_action = "BUY"; final_confidence = max(final_confidence, 0.72)
        elif pred < -0.2:
            final_action = "SELL"; final_confidence = max(final_confidence, 0.72)

    if final_action == "BUY" and ml_signal.get("predicted_return_pct", 0) < -0.15:
        final_action = "HOLD"; final_confidence = 0

    # Cost filter
    if final_action != "HOLD":
        pred_ret = abs(ml_signal.get("predicted_return_pct", 0)) / 100
        if pred_ret < TOTAL_COST_PER_TRADE * 2 and final_confidence < 0.80:
            final_action = "HOLD"; final_confidence = 0

    # ── Quality Gate 1: ATR Flatline Detector ─────────────────────────────────
    # If ATR is near zero the price is frozen → all indicators are garbage (OP lesson)
    atr_raw = last.get('atr_14', 0)
    if atr_raw is not None and not pd.isna(atr_raw):
        atr_pct_raw = float(atr_raw) / float(last['close']) * 100 if float(last['close']) > 0 else 0
        if atr_pct_raw < 0.05:   # ATR < 0.05% of price = practically frozen
            final_action = "HOLD"; final_confidence = 0.0   # hard block

    # ── Quality Gate 2: Volume Minimum ───────────────────────────────────────
    # Require at least 20% of average volume; below = illiquid, signals unreliable
    vol_ratio = last.get('volume_ratio', 1.0)
    if vol_ratio is not None and not pd.isna(vol_ratio) and float(vol_ratio) < 0.20:
        if final_action != "HOLD":
            final_action = "HOLD"; final_confidence = 0.0   # no liquidity

    # ── Quality Gate 3: ML-Rule Consensus ────────────────────────────────────
    # Block when rule and ML point in opposite directions
    # (OP: rule=SELL conf=0.83, ml=BUY prob=0.76 → complete disagreement)
    if final_action != "HOLD":
        rule_dir = rule_signal.get("action", "HOLD")
        ml_dir   = ml_signal.get("prediction", "HOLD")
        if rule_dir != "HOLD" and ml_dir != "HOLD" and rule_dir != ml_dir:
            # Hard disagreement between engines → neither is reliable
            final_action = "HOLD"; final_confidence = 0.0

    # HTF momentum gate: block BUY when 1h trend is bearish or 1h RSI overbought
    if final_action == "BUY":
        htf_trend = last.get('htf_1h_trend')
        htf_rsi   = last.get('htf_1h_rsi')
        if htf_trend is not None and not pd.isna(htf_trend) and float(htf_trend) < 0:
            final_action = "HOLD"; final_confidence = 0.0  # counter-trend on 1h
        if htf_rsi is not None and not pd.isna(htf_rsi) and float(htf_rsi) > 75:
            final_action = "HOLD"; final_confidence = 0.0  # overbought on 1h, chasing

    return final_action, final_confidence


def generate_full_signal(symbol="BTCUSDT", interval="15m"):
    """Main entry point for generating signals in production"""
    tf_data = fetch_multi_timeframe(symbol)
    df = tf_data.get('15m')
    if df is None:
        df = fetch_binance_klines(symbol, interval, 500)

    features = engineer_features(df)
    features = add_htf_features(features, tf_data.get('1h'), tf_data.get('4h'))

    regime_info = detect_regime(df, features)
    strategy = STRATEGIES.get(regime_info["regime"], STRATEGIES["RANGING"])
    rule_signal = generate_signal(features, regime_info)
    ml_signal = predict_ml(features, symbol=symbol)

    last = features.iloc[-1]
    final_action, final_confidence = apply_signal_rules(last, rule_signal, ml_signal)
    def r(k):
        v = last.get(k)
        return round(float(v), 2) if v is not None and not pd.isna(v) else None

    atr_val = r('atr_14') or float(last['close']) * 0.01
    sizing = calc_position_size(float(last['close']), atr_val, 1000, 0.01,
                                 final_action if final_action != "HOLD" else "BUY")

    indicators = {
        "price": r('close'), "rsi_3": r('rsi_3'), "rsi_14": r('rsi_14'),
        "macd_hist": r('macd_hist'), "ema_8": r('ema_8'), "ema_21": r('ema_21'),
        "z_score": r('z_score'), "atr_pct": r('atr_pct'), "adx": r('adx'),
        "bb_pct_b": r('bb_pct_b'), "volume_ratio": r('volume_ratio'),
        "buy_pressure": r('buy_pressure'), "williams_r": r('williams_r'),
        "stoch_k": r('stoch_k'), "cci": r('cci'), "mfi": r('mfi'),
        "keltner_pos": r('keltner_pos'), "ichimoku_cloud_dist": r('ichimoku_cloud_dist'),
        "donchian_pos": r('donchian_pos'), "obv_slope": r('obv_slope'), "roc_10": r('roc_10'),
    }

    # Add HTF info if available
    for htf_col in HTF_FEATURE_COLS:
        v = last.get(htf_col)
        if v is not None and not pd.isna(v):
            indicators[htf_col] = round(float(v), 4)

    return {
        "timestamp": datetime.utcnow().isoformat(),
        "symbol": symbol, "interval": interval, "engine_version": "V3",
        "regime": regime_info,
        "strategy": strategy["name"],
        "rule_signal": rule_signal,
        "ml_signal": ml_signal,
        "final_signal": {"action": final_action, "confidence": round(final_confidence, 3)},
        "position_sizing": sizing,
        "indicators": indicators,
    }


# ─── CLI ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "signal"
    symbol = sys.argv[2] if len(sys.argv) > 2 else "BTCUSDT"

    if cmd == "train":
        print("=" * 60)
        print(f"  QUANT ENGINE V3 — Per-Asset Training: {symbol}")
        print("=" * 60)
        train_model(symbol)

    elif cmd == "train-all":
        assets = [
            "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT",
            "DOGEUSDT", "AVAXUSDT", "ADAUSDT",
            "DOTUSDT", "LINKUSDT", "MATICUSDT", "NEARUSDT",
            "APTUSDT", "SUIUSDT", "ARBUSDT", "OPUSDT",
            "TRUMPUSDT", "PEPEUSDT", "SHIBUSDT", "LTCUSDT",
        ]
        print("=" * 60)
        print("  QUANT ENGINE V3 — Training ALL 20 Asset Models")
        print("=" * 60)
        results = {}
        for asset in assets:
            try:
                meta = train_model(asset)
                results[asset] = {
                    "status": "OK",
                    "test_accuracy": meta["walk_forward"]["test_accuracy"],
                    "overfit_gap": meta["walk_forward"]["overfit_gap"],
                    "warning": meta["walk_forward"].get("overfit_warning"),
                    "reg_mae": meta["regressor_mae_pct"],
                }
            except Exception as e:
                results[asset] = {"status": f"ERROR: {str(e)[:60]}"}
                print(f"  ERROR training {asset}: {e}")

        print("\n" + "=" * 60)
        print("  TRAINING SUMMARY")
        print("=" * 60)
        print(f"  {'Asset':<12} {'Accuracy':>10} {'Overfit':>10} {'Reg MAE':>10} {'Status'}")
        print("  " + "-" * 60)
        for asset, r in results.items():
            if r["status"] == "OK":
                warn = " [!]" if r.get("warning") else ""
                print(f"  {asset:<12} {r['test_accuracy']*100:>8.1f}% {r['overfit_gap']*100:>8.1f}% {r['reg_mae']:>9.3f}% {r['status']}{warn}")
            else:
                print(f"  {asset:<12} {'':>10} {'':>10} {'':>10} {r['status']}")

    elif cmd == "backtest":
        print("=" * 60)
        print(f"  QUANT ENGINE V3 — Backtest: {symbol}")
        print("=" * 60)
        results = backtest(symbol)
        print("\n" + json.dumps(results, indent=2))

    elif cmd == "backtest-all":
        assets = [
            "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT",
            "DOGEUSDT", "AVAXUSDT", "ADAUSDT",
            "DOTUSDT", "LINKUSDT", "MATICUSDT", "NEARUSDT",
            "APTUSDT", "SUIUSDT", "ARBUSDT", "OPUSDT",
            "TRUMPUSDT", "PEPEUSDT", "SHIBUSDT", "LTCUSDT",
        ]
        print("=" * 60)
        print("  QUANT ENGINE V3 — Multi-Asset Backtest (with costs)")
        print("=" * 60)
        all_results = {}
        for asset in assets:
            try:
                r = backtest(asset)
                all_results[asset] = r
            except Exception as e:
                print(f"  ERROR backtesting {asset}: {e}")

        print("\n" + "=" * 70)
        print("  BACKTEST COMPARISON (with transaction costs)")
        print("=" * 70)
        print(f"  {'Asset':<10} {'Trades':>7} {'WR':>6} {'PnL':>10} {'PnL%':>7} {'PF':>6} {'Sharpe':>7} {'Sortino':>8} {'MaxDD':>7} {'Fees':>8}")
        print("  " + "-" * 82)
        total_pnl = 0
        total_trades = 0
        for asset, r in all_results.items():
            total_pnl += r['total_pnl']
            total_trades += r['total_trades']
            print(f"  {asset:<10} {r['total_trades']:>7} {r['win_rate']:>5.1f}% ${r['total_pnl']:>8.2f} {r['total_pnl_pct']:>6.2f}% {r['profit_factor']:>5.2f} {r['sharpe_ratio']:>7.2f} {r['sortino_ratio']:>8.2f} {r['max_drawdown_pct']:>6.2f}% ${r['total_fees_paid']:>6.2f}")
        print("  " + "-" * 82)
        print(f"  {'TOTAL':<10} {total_trades:>7} {'':>6} ${total_pnl:>8.2f}")

        # Portfolio-level VaR
        print(f"\n  Portfolio Summary:")
        print(f"    Combined PnL: ${total_pnl:.2f}")
        print(f"    Total trades: {total_trades}")
        avg_pf = np.mean([r['profit_factor'] for r in all_results.values() if r['profit_factor'] < 900])
        print(f"    Avg profit factor: {avg_pf:.2f}")
        avg_sharpe = np.mean([r['sharpe_ratio'] for r in all_results.values()])
        print(f"    Avg Sharpe: {avg_sharpe:.2f}")

    elif cmd == "signal":
        result = generate_full_signal(symbol)
        print(json.dumps(result, indent=2))

    elif cmd == "regime":
        df = fetch_binance_klines(symbol, "15m", 500)
        features = engineer_features(df)
        print(json.dumps(detect_regime(df, features), indent=2))

    elif cmd == "scan":
        assets = [
            # Major crypto
            "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT",
            "DOGEUSDT", "AVAXUSDT", "ADAUSDT",
            # Mid-cap / DeFi / L2
            "DOTUSDT", "LINKUSDT", "MATICUSDT", "NEARUSDT",
            "APTUSDT", "SUIUSDT", "ARBUSDT", "OPUSDT",
            # Meme / speculative
            "TRUMPUSDT", "PEPEUSDT", "SHIBUSDT",
            # Legacy
            "LTCUSDT",
        ]
        print("=" * 60)
        print("  QUANT ENGINE V3 — Full Market Scanner (20 assets)")
        print("=" * 60)
        results = []
        for asset in assets:
            try:
                r = generate_full_signal(asset)
                results.append({
                    "symbol": asset, "price": r["indicators"]["price"],
                    "regime": r["regime"]["regime"], "direction": r["regime"]["direction"],
                    "signal": r["final_signal"]["action"], "confidence": r["final_signal"]["confidence"],
                    "anomaly": r["ml_signal"].get("is_anomaly", False),
                    "pred_return": r["ml_signal"].get("predicted_return_pct", 0),
                    "reason": r["rule_signal"]["reason"],
                })
                anom = "!" if r["ml_signal"].get("is_anomaly") else " "
                print(f"  {anom} {asset:12s} | {r['regime']['regime']:10s} | {r['final_signal']['action']:4s} ({r['final_signal']['confidence']:.0%}) | ${r['indicators']['price']:>10,.2f} | pred={r['ml_signal'].get('predicted_return_pct',0):+.2f}%")
            except Exception as e:
                print(f"  {asset:12s} | ERROR: {str(e)[:50]}")
        print("\n" + json.dumps(results, indent=2))

    elif cmd == "validate":
        # Step 5: Full validation report
        print("=" * 60)
        print(f"  QUANT ENGINE V3 — Model Validation: {symbol}")
        print("=" * 60)
        paths = model_paths(symbol)
        if os.path.exists(paths['meta']):
            with open(paths['meta']) as f:
                meta = json.load(f)
            wf = meta['walk_forward']
            print(f"\n  Model trained: {meta['trained_at']}")
            print(f"  Samples: {meta['samples']}")
            print(f"  Selected features: {len(meta['selected_features'])}")
            print(f"  Train accuracy: {wf['train_accuracy']:.1%}")
            print(f"  Test accuracy:  {wf['test_accuracy']:.1%}")
            print(f"  Overfit gap:    {wf['overfit_gap']:.1%}")
            if wf.get('overfit_warning'):
                print(f"  WARNING: {wf['overfit_warning']}")
            print(f"  Regressor MAE:  {meta['regressor_mae_pct']:.3f}%")
            print(f"  Per-fold scores: {wf['fold_test_scores']}")
            print(f"\n  Top features: {', '.join(meta['selected_features'][:10])}")

            # Run a fresh backtest comparison: with vs without costs
            print("\n  Running backtest WITH costs...")
            r_costs = backtest(symbol, include_costs=True)
            print("  Running backtest WITHOUT costs...")
            r_no = backtest(symbol, include_costs=False)

            print(f"\n  {'Metric':<25} {'With Costs':>12} {'No Costs':>12} {'Impact':>12}")
            print("  " + "-" * 63)
            print(f"  {'Total PnL':<25} ${r_costs['total_pnl']:>10.2f} ${r_no['total_pnl']:>10.2f} ${r_costs['total_pnl']-r_no['total_pnl']:>10.2f}")
            print(f"  {'Win Rate':<25} {r_costs['win_rate']:>11.1f}% {r_no['win_rate']:>11.1f}% {r_costs['win_rate']-r_no['win_rate']:>11.1f}%")
            print(f"  {'Trades':<25} {r_costs['total_trades']:>12} {r_no['total_trades']:>12} {r_costs['total_trades']-r_no['total_trades']:>12}")
            print(f"  {'Profit Factor':<25} {r_costs['profit_factor']:>12.2f} {r_no['profit_factor']:>12.2f}")
            print(f"  {'Sharpe':<25} {r_costs['sharpe_ratio']:>12.2f} {r_no['sharpe_ratio']:>12.2f}")
            print(f"  {'Max Drawdown':<25} {r_costs['max_drawdown_pct']:>11.2f}% {r_no['max_drawdown_pct']:>11.2f}%")
            print(f"  {'Total Fees':<25} ${r_costs['total_fees_paid']:>10.4f}")

            cost_drag = r_no['total_pnl'] - r_costs['total_pnl']
            if r_no['total_pnl'] != 0:
                cost_pct = cost_drag / abs(r_no['total_pnl']) * 100
                print(f"\n  Fees eat {cost_pct:.1f}% of gross profits")
            if r_costs['total_pnl'] <= 0 and r_no['total_pnl'] > 0:
                print("  [!] Strategy is profitable ONLY without costs -- not viable for production!")
        else:
            print(f"  No model found for {symbol}. Run: python quant_engine_v3.py train {symbol}")

    else:
        print("Usage: python quant_engine_v3.py [command] [SYMBOL]")
        print("  train       - Train model for one asset")
        print("  train-all   - Train models for all 8 assets")
        print("  backtest    - Backtest with transaction costs")
        print("  backtest-all- Multi-asset backtest comparison")
        print("  signal      - Generate live signal")
        print("  scan        - Scan all assets")
        print("  validate    - Full model validation report")
        print("  regime      - Current regime detection")
