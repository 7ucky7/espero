"""Causal technical indicators.

Every function here uses only information available at or before the row it
returns a value for. If you add an indicator, keep that property -- the
backtester's honesty depends on it.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI, EWM form. Neutral 50 where there is no downside yet."""
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50.0)


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """Return (line, signal, histogram) with adjusted=False EMAs."""
    line = close.ewm(span=fast, adjust=False).mean() - close.ewm(span=slow, adjust=False).mean()
    sig = line.ewm(span=signal, adjust=False).mean()
    return line, sig, line - sig


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Attach the columns the bundled strategies read. Never mutates the input."""
    out = df.copy()
    out["sma20"] = out["close"].rolling(20).mean()
    out["sma50"] = out["close"].rolling(50).mean()
    out["rsi14"] = rsi(out["close"])
    mid = out["close"].rolling(20).mean()
    sd = out["close"].rolling(20).std()
    out["bb_up"] = mid + 2 * sd
    out["bb_lo"] = mid - 2 * sd
    out["macd"], out["macd_sig"], out["macd_hist"] = macd(out["close"])
    return out
