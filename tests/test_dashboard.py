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
        html = dashboard.render(self.dir / "none.db", self.dir / "p.db", self.dir / "l.db",
                             self.dir / "x.db")
        self.assertIn("No accounts yet", html)
        self.assertIn("<!doctype html>", html)

    def test_account_is_rendered(self):
        path = self.dir / "tsmom.db"
        acc = tsmom.Account(path)
        acc.cash = 100.0
        acc.rebalance(pd.Series({"SPY": 100.0}), {"SPY": 1 / 6})
        eq = acc.equity(pd.Series({"SPY": 100.0}))
        acc.save(1_793_059_200, eq, {"SPY": 1 / 6}, "init",
                 positions={"SPY": acc.units["SPY"] * 100.0},
                 signals={"SPY": 0.139})

        html = dashboard.render(path, self.dir / "p.db", self.dir / "l.db", self.dir / "x.db", offline=True)
        self.assertIn("Cross-asset trend", html)
        self.assertIn(f"${eq:,.2f}", html)   # net of the 10 bps cost
        self.assertIn("SPY", html)
        self.assertIn("+13.9%", html)        # the snapshot the bot decided on
        self.assertIn("as of the last decision", html)

    def test_cards_are_split_by_asset_class(self):
        path = self.dir / "tsmom.db"
        acc = tsmom.Account(path)
        acc.cash = 100.0
        acc.rebalance(pd.Series({"SPY": 100.0}), {"SPY": 1 / 6})
        eq = acc.equity(pd.Series({"SPY": 100.0}))
        acc.save(1_793_059_200, eq, {"SPY": 1 / 6}, "init",
                 positions={"SPY": acc.units["SPY"] * 100.0}, signals={"SPY": 0.1})
        html = dashboard.render(path, self.dir / "p.db", self.dir / "l.db", self.dir / "x.db", offline=True)
        for title in ("Equities", "Bonds", "Commodities", "Crypto", "Cash"):
            self.assertIn(title, html)
        self.assertIn("plan", html)          # the move column exists

    def test_equity_equals_cash_plus_positions(self):
        path = self.dir / "tsmom.db"
        acc = tsmom.Account(path)
        acc.cash = 100.0
        acc.rebalance(pd.Series({"SPY": 50.0}), {"SPY": 1 / 6})
        eq = acc.equity(pd.Series({"SPY": 50.0}))
        acc.save(1_793_059_200, eq, {"SPY": 1 / 6}, "init",
                 positions={"SPY": acc.units["SPY"] * 50.0})
        html = dashboard.render(path, self.dir / "p.db", self.dir / "l.db", self.dir / "x.db", offline=True)
        self.assertIn(f"${eq:,.2f}", html)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestForwardAndBoardCards(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def render(self, **kw):
        return dashboard.render(self.dir / "t.db", self.dir / "p.db", self.dir / "l.db", self.dir / "x.db", **kw)

    def test_mf_card_only_when_asked(self):
        from espero import mf
        acc = mf.MFAccount(self.dir / "mf.db", cash=100.0)
        acc.save(1_793_232_000, 100.0, {}, {}, 100.0, "init", {}, 0.0)
        acc.close()
        self.assertNotIn("#8 multifactor", self.render(offline=True))
        html = self.render(offline=True, mf_db=self.dir / "mf.db")
        self.assertIn("#8 multifactor, forward test", html)
        self.assertIn("holding cash until the first fill on 2026-11-02", html)

    def test_board_card_is_online_only_and_labelled_a_scanner(self):
        from unittest import mock

        import numpy as np

        from espero import board
        dates = pd.bdate_range("2025-01-01", "2026-10-28")
        close = 100 * np.exp(0.001 * np.arange(len(dates)))
        spy = pd.DataFrame({"ts": 0.0, "open": close, "high": close, "low": close, "close": close,
                            "adj_close": close, "volume": 1e9}, index=dates)
        with mock.patch.object(board, "fetch_frames", return_value=({"SPY": spy}, {})) as fetch:
            self.assertNotIn("Signal board", self.render(offline=True, board=True))
            fetch.assert_not_called()
            html = self.render(board=True)
        self.assertIn("Signal board", html)
        self.assertIn("scanner · #15 failed its test", html)
        self.assertIn("▲▲▲", html)

    def test_a_board_failure_does_not_lose_the_page(self):
        from unittest import mock

        from espero import board
        with mock.patch.object(board, "fetch_frames", side_effect=RuntimeError("yahoo down")):
            html = self.render(board=True)
        self.assertIn("unavailable: RuntimeError: yahoo down", html)
        self.assertIn("<!doctype html>", html)
