"""
indicators.py
EMA · RSI · ATR · MACD · Bollinger Bands · Volume Filter
"""

import pandas as pd
import numpy as np


# ─── Trend ────────────────────────────────────────────────────────────────────

def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def macd(series: pd.Series, fast=12, slow=26, signal=9):
    fast_ema   = ema(series, fast)
    slow_ema   = ema(series, slow)
    macd_line  = fast_ema - slow_ema
    signal_line = ema(macd_line, signal)
    histogram  = macd_line - signal_line
    return macd_line, signal_line, histogram


# ─── Momentum ─────────────────────────────────────────────────────────────────

def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain  = delta.clip(lower=0.0)
    loss  = -delta.clip(upper=0.0)
    avg_g = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_l = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs    = avg_g / avg_l.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


# ─── Volatility ───────────────────────────────────────────────────────────────

def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    hl = df["high"] - df["low"]
    hc = (df["high"] - df["close"].shift()).abs()
    lc = (df["low"]  - df["close"].shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def bollinger(series: pd.Series, period: int = 20, std: float = 2.0):
    mid   = series.rolling(period).mean()
    sigma = series.rolling(period).std()
    upper = mid + std * sigma
    lower = mid - std * sigma
    return upper, mid, lower


# ─── Volume ───────────────────────────────────────────────────────────────────

def volume_ratio(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Current volume vs rolling average — values > 1.5 = high activity."""
    avg_vol = df["volume"].rolling(period).mean()
    return df["volume"] / avg_vol.replace(0, np.nan)


# ─── Apply all ────────────────────────────────────────────────────────────────

def apply_all(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    # Trend
    out["ema9"]  = ema(out["close"], 9)
    out["ema21"] = ema(out["close"], 21)
    out["ema50"] = ema(out["close"], 50)

    # Momentum
    out["rsi"] = rsi(out["close"], 14)
    out["macd"], out["macd_signal"], out["macd_hist"] = macd(out["close"])

    # Volatility
    out["atr"] = atr(out, 14)
    out["bb_upper"], out["bb_mid"], out["bb_lower"] = bollinger(out["close"])

    # Volume
    out["vol_ratio"] = volume_ratio(out)

    return out
