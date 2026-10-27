"""The dashboard must render from a database, and from nothing at all."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from espero import dashboard, tsmom


class TestDashboard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_empty_state_does_not_crash(self):
        html = dashboard.render(self.dir / "none.db", self.dir / "p.db", self.dir / "l.db")
        self.assertIn("No accounts yet", html)
        self.assertIn("<!doctype html>", html)

    def test_account_is_rendered(self):
        path = self.dir / "tsmom.db"
        acc = tsmom.Account(path)
        acc.cash = 100.0
        acc.rebalance(pd.Series({"SPY": 100.0}), {"SPY": 1 / 6})
        eq = acc.equity(pd.Series({"SPY": 100.0}))
        acc.save(1_793_059_200, eq, {"SPY": 1 / 6}, "init",
                 positions={"SPY": acc.units["SPY"] * 100.0})

        html = dashboard.render(path, self.dir / "p.db", self.dir / "l.db")
        self.assertIn("Cross-asset trend", html)
        self.assertIn(f"${eq:,.2f}", html)   # net of the 10 bps cost
        self.assertIn("SPY", html)

    def test_equity_equals_cash_plus_positions(self):
        path = self.dir / "tsmom.db"
        acc = tsmom.Account(path)
        acc.cash = 100.0
        acc.rebalance(pd.Series({"SPY": 50.0}), {"SPY": 1 / 6})
        eq = acc.equity(pd.Series({"SPY": 50.0}))
        acc.save(1_793_059_200, eq, {"SPY": 1 / 6}, "init",
                 positions={"SPY": acc.units["SPY"] * 50.0})
        html = dashboard.render(path, self.dir / "p.db", self.dir / "l.db")
        self.assertIn(f"${eq:,.2f}", html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
