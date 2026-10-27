"""TSMOM paper account: weights, cash, and no money appearing from nowhere."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from espero import tsmom as T


class TestLookback(unittest.TestCase):
    def test_lookback_is_52_weeks_on_the_calendar_not_252_rows(self):
        idx = pd.date_range("2024-01-01", periods=500, freq="D")
        s = pd.Series(np.linspace(100, 200, 500), index=idx)
        sig = T.signals({"X": s})["X"]
        ref = s[s.index <= s.index[-1] - pd.Timedelta(days=T.LOOKBACK_DAYS)].iloc[-1]
        self.assertAlmostEqual(sig, s.iloc[-1] / ref - 1, places=10)
        # the old row-based version would have used the price 252 rows back
        old = s.iloc[-1] / s.iloc[-253] - 1
        self.assertNotAlmostEqual(sig, old, places=3)


class TestWeights(unittest.TestCase):
    def test_four_positive_assets_get_one_sixth_each(self):
        sig = {"SPY": 0.1, "TLT": -0.1, "GLD": -0.05, "USO": 1.2, "BTC": 0.16, "ETH": 0.15}
        w, cash = T.target_weights(sig)
        for a in ("SPY", "USO", "BTC", "ETH"):
            self.assertAlmostEqual(w[a], 1 / 6)
        for a in ("TLT", "GLD"):
            self.assertEqual(w[a], 0.0)
        self.assertAlmostEqual(cash, 1 - 4 / 6)

    def test_all_cash_when_nothing_is_positive(self):
        sig = {a: -0.01 for a in ("SPY", "TLT", "GLD", "USO", "BTC", "ETH")}
        w, cash = T.target_weights(sig)
        self.assertEqual(sum(w.values()), 0)
        self.assertAlmostEqual(cash, 1.0)

    def test_single_asset_is_capped_at_one_sixth(self):
        sig = {"SPY": 0.1, "TLT": -0.1, "GLD": -0.1, "USO": -0.1, "BTC": -0.1, "ETH": -0.1}
        w, cash = T.target_weights(sig)
        self.assertAlmostEqual(w["SPY"], 1 / 6)
        self.assertAlmostEqual(cash, 5 / 6)


class TestAccount(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "acct.db"

    def tearDown(self):
        self.tmp.cleanup()

    def test_rebalance_conserves_cash_minus_costs(self):
        acc = T.Account(self.path)
        acc.cash = 100.0
        prices = pd.Series({"SPY": 100.0, "BTC": 100.0})
        weights = {"SPY": 1 / 6, "BTC": 1 / 6}
        traded = acc.rebalance(prices, weights)
        equity = acc.equity(prices)
        self.assertAlmostEqual(traded, 100 / 3, places=6)
        self.assertAlmostEqual(equity, 100 - (100 / 3) * T.COST, places=6)

    def test_state_survives_restart(self):
        acc = T.Account(self.path)
        acc.cash = 50.0
        acc.rebalance(pd.Series({"SPY": 10.0}), {"SPY": 1 / 6})
        units = dict(acc.units)
        acc.save(1_700_000_000, acc.equity(pd.Series({"SPY": 10.0})), {"SPY": 1 / 6}, "test")

        reopened = T.Account(self.path)
        self.assertAlmostEqual(reopened.cash, acc.cash)
        self.assertAlmostEqual(reopened.units["SPY"], units["SPY"])

    def test_decision_snapshot_survives_restart(self):
        acc = T.Account(self.path)
        acc.cash = 100.0
        acc.rebalance(pd.Series({"SPY": 10.0}), {"SPY": 1 / 6})
        acc.save(1_700_000_000, acc.equity(pd.Series({"SPY": 10.0})), {"SPY": 1 / 6},
                 "init", positions={"SPY": 10.0}, signals={"SPY": 0.139, "TLT": -0.1})
        reopened = T.Account(self.path)
        import json
        row = reopened.last()
        self.assertEqual(json.loads(row["signals"])["SPY"], 0.139)

    def test_no_leverage(self):
        acc = T.Account(self.path)
        acc.cash = 100.0
        acc.rebalance(pd.Series({"SPY": 10.0}), {"SPY": 1 / 6})
        self.assertGreaterEqual(acc.cash, -1e-9)


if __name__ == "__main__":
    unittest.main(verbosity=2)
