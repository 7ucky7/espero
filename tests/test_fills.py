"""Order of operations inside a bar: gaps, stop-before-target, fees, accounting."""
from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

import espero.backtest as bt
from espero.backtest import Config, run
from espero.signals import Signal


def frame(n: int = 200, price: float = 100.0) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    close = np.full(n, float(price))
    return pd.DataFrame({
        "dt": idx, "open": close, "high": close * 1.002,
        "low": close * 0.998, "close": close, "volume": 1.0,
    })


class BuyAt:
    def __init__(self, nth: int = 10):
        self.nth, self.calls = nth, 0

    def __call__(self, sigs):
        self.calls += 1
        return Signal("BUY", 0.9, "test") if self.calls == self.nth else None


class TestBarMechanics(unittest.TestCase):
    def setUp(self):
        self.orig = bt.combine

    def tearDown(self):
        bt.combine = self.orig

    def sim(self, df, **kw):
        bt.combine = BuyAt()
        cfg = Config(timing="next_bar", slippage=0.0, fee=kw.pop("fee", 0.0),
                     stop_pct=0.05, target_pct=0.10, sizing="full", **kw)
        return run(df, cfg)

    def test_stop_wins_when_a_bar_touches_both(self):
        df = frame()
        df.loc[61, ["low", "high"]] = [50.0, 200.0]  # entry is bar 60's open
        res = self.sim(df)
        self.assertEqual(len(res.trades), 1)
        self.assertEqual(res.trades[0].reason, "stop")

    def test_gap_through_stop_fills_at_the_open(self):
        df = frame()
        df.loc[61, "open"] = 80.0
        res = self.sim(df)
        self.assertEqual(res.trades[0].reason, "gap_stop")
        self.assertAlmostEqual(res.trades[0].exit_px, 80.0, places=6)

    def test_gap_through_target_fills_at_the_open(self):
        df = frame()
        df.loc[61, "open"] = 130.0
        res = self.sim(df)
        self.assertEqual(res.trades[0].reason, "gap_target")
        self.assertAlmostEqual(res.trades[0].exit_px, 130.0, places=6)

    def test_fees_are_charged_on_both_sides(self):
        df = frame()
        df.loc[65, "high"] = 120.0  # force a target exit, otherwise nothing closes
        bt.combine = BuyAt()
        cfg = Config(timing="next_bar", slippage=0.0, fee=0.002,
                     stop_pct=0.01, target_pct=0.02, sizing="full")
        res = run(df, cfg)
        self.assertTrue(res.trades)
        t = res.trades[0]
        self.assertAlmostEqual(t.fees, 0.002 * t.entry_px * t.size + 0.002 * t.exit_px * t.size, places=6)
        self.assertAlmostEqual(res.fees, t.fees, places=9)

    def test_equity_equals_cash_plus_marked_position(self):
        df = frame()
        df.loc[65, "high"] = 120.0
        res = self.sim(df, fee=0.001)
        self.assertAlmostEqual(res.equity.iloc[-1],
                               Config().initial + sum(t.pnl for t in res.trades), places=6)

    def test_bad_config_is_rejected(self):
        with self.assertRaises(ValueError):
            Config(timing="teleport")
        with self.assertRaises(ValueError):
            Config(sizing="yolo")


if __name__ == "__main__":
    unittest.main(verbosity=2)
