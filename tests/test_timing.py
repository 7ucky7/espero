"""A fill must happen strictly after the signal that caused it."""
from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

import espero.backtest as bt
from espero.backtest import Config, run
from espero.signals import Signal


def frame(n: int = 300, price: float = 100.0) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    close = price + 5 * np.sin(np.arange(n) / 9.0)
    return pd.DataFrame({
        "dt": idx, "open": close, "high": close * 1.002,
        "low": close * 0.998, "close": close, "volume": 1.0,
    })


class ScriptedBuy:
    """Emit one BUY on the n-th call, nothing otherwise."""

    def __init__(self, nth: int):
        self.nth, self.calls = nth, 0

    def __call__(self, sigs):
        self.calls += 1
        if self.calls == self.nth:
            return Signal("BUY", 0.9, "test")
        return None


class TestExecutionTiming(unittest.TestCase):
    """warmup=50, so call #10 is bar 59."""

    def setUp(self):
        self.df = frame()
        self.orig = bt.combine

    def tearDown(self):
        bt.combine = self.orig

    def trade(self, timing: str):
        bt.combine = ScriptedBuy(nth=10)
        cfg = Config(timing=timing, fee=0.0, slippage=0.001,
                     stop_pct=0.99, target_pct=0.0001, sizing="full")
        res = run(self.df, cfg)
        self.assertEqual(len(res.trades), 1)
        return res.trades[0]

    def test_next_bar_fills_at_following_open(self):
        t = self.trade("next_bar")
        self.assertEqual(t.entry_i, 60)
        self.assertAlmostEqual(t.entry_px, self.df["open"].iloc[60] * 1.001, places=6)

    def test_same_bar_reproduces_the_original_bug(self):
        t = self.trade("same_bar")
        self.assertEqual(t.entry_i, 59)
        self.assertAlmostEqual(t.entry_px, self.df["open"].iloc[59] * 1.001, places=6)

    def test_same_bar_is_one_bar_earlier(self):
        self.assertLess(self.trade("same_bar").entry_i, self.trade("next_bar").entry_i)


if __name__ == "__main__":
    unittest.main(verbosity=2)
