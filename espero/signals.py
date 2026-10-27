"""The four strategies from the original repo, reduced to pure functions.

A strategy may only return `Signal` objects. It cannot size a position, touch
the account, or call a broker. That constraint is what makes the rest testable.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import numpy as np
import pandas as pd

WEIGHTS = {"macross": 1.0, "rsi": 1.0, "bollinger": 1.0, "macd": 1.0}
CONSENSUS = 0.60
MIN_CONFIDENCE = 0.65


@dataclass(frozen=True)
class Signal:
    side: str  # "BUY" | "SELL"
    confidence: float
    strategy: str


def signals_at(row: pd.Series, prev: pd.Series) -> List[Signal]:
    """Signals visible at the close of one bar."""
    out: List[Signal] = []
    if not np.isfinite(row["sma50"]):
        return out

    # 1. MA crossover -- confidence from slope spread, 0.5..1.0
    s20 = (row["sma20"] - prev["sma20"]) / prev["sma20"]
    s50 = (row["sma50"] - prev["sma50"]) / prev["sma50"]
    if row["sma20"] > row["sma50"] and prev["sma20"] <= prev["sma50"]:
        out.append(Signal("BUY", 0.5 + min(0.5, max(0.0, (s20 - s50) * 10)), "macross"))
    elif row["sma20"] < row["sma50"] and prev["sma20"] >= prev["sma50"]:
        out.append(Signal("SELL", 0.5 + min(0.5, max(0.0, (s50 - s20) * 10)), "macross"))

    # 2. RSI mean reversion
    r = float(row["rsi14"])
    if r < 30:
        out.append(Signal("BUY", 0.5 + min(0.5, (30 - r) / 30), "rsi"))
    elif r > 70:
        out.append(Signal("SELL", 0.5 + min(0.5, (r - 70) / 30), "rsi"))

    # 3. Bollinger touch
    if row["close"] < row["bb_lo"]:
        out.append(Signal("BUY", 0.6, "bollinger"))
    elif row["close"] > row["bb_up"]:
        out.append(Signal("SELL", 0.6, "bollinger"))

    # 4. MACD histogram flip
    if row["macd_hist"] > 0 >= prev["macd_hist"]:
        out.append(Signal("BUY", 0.65, "macd"))
    elif row["macd_hist"] < 0 <= prev["macd_hist"]:
        out.append(Signal("SELL", 0.65, "macd"))
    return out


def combine(signals: List[Signal]) -> Optional[Signal]:
    """Weighted vote, normalised by total weight (the original's rule)."""
    if not signals:
        return None
    score: dict = {}
    total = 0.0
    for s in signals:
        w = WEIGHTS.get(s.strategy, 1.0)
        score[s.side] = score.get(s.side, 0.0) + s.confidence * w
        total += w
    if total <= 0:
        return None
    side = max(score, key=score.get)
    conf = score[side] / total
    if conf < CONSENSUS:
        return None
    return Signal(side, conf, "combined")
