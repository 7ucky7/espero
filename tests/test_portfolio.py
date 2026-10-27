"""Weights that never borrow, caps that redistribute, a buffer that holds."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from espero import portfolio as pf
from espero import tca, tsmom, xs


class TestVolScaling(unittest.TestCase):
    def test_scales_by_target_over_vol_and_never_exceeds_gross(self):
        w = pd.Series({"A": 0.5, "B": 0.5})
        vol = pd.Series({"A": 0.40, "B": 0.10})
        out = pf.vol_scaled(w, vol, target=0.20, max_gross=1.0, max_scale=3.0)
        # A: 0.5 * 0.5 = 0.25 ; B: 0.5 * 2.0 = 1.0 ; gross 1.25 -> scaled to 1.0
        self.assertAlmostEqual(out.sum(), 1.0)
        self.assertAlmostEqual(out["A"] / out["B"], 0.25)

    def test_unknown_vol_means_no_position(self):
        w = pd.Series({"A": 0.5, "B": 0.5})
        vol = pd.Series({"A": 0.2, "B": np.nan})
        out = pf.vol_scaled(w, vol, target=0.2)
        self.assertEqual(out["B"], 0.0)
        self.assertAlmostEqual(out["A"], 0.5)


class TestCaps(unittest.TestCase):
    def test_excess_is_redistributed(self):
        w = pd.Series({"A": 0.7, "B": 0.2, "C": 0.1})
        out = pf.cap_weights(w, 0.4)
        self.assertAlmostEqual(out["A"], 0.4)
        self.assertAlmostEqual(out.sum(), 1.0)
        self.assertAlmostEqual(out["B"] / out["C"], 2.0)

    def test_cascading_caps(self):
        w = pd.Series({"A": 0.6, "B": 0.35, "C": 0.05})
        out = pf.cap_weights(w, 0.4)
        self.assertLessEqual(out.max(), 0.4 + 1e-9)
        self.assertAlmostEqual(out.sum(), 1.0)


class TestBuffer(unittest.TestCase):
    def test_held_name_inside_the_buffer_is_kept(self):
        scores = pd.Series({c: -i for i, c in enumerate("ABCDEFGH")})   # A best ... H worst
        picks = pf.turnover_buffer(scores, held=["D"], top=2, buffer=2.0)   # D is rank 4 <= 4
        self.assertIn("D", picks)
        self.assertEqual(len(picks), 2)
        self.assertEqual(picks, ["D", "A"])

    def test_held_name_outside_the_buffer_is_dropped(self):
        scores = pd.Series({c: -i for i, c in enumerate("ABCDEFGH")})
        picks = pf.turnover_buffer(scores, held=["F"], top=2, buffer=2.0)   # F is rank 6 > 4
        self.assertEqual(picks, ["A", "B"])

    def test_no_held_is_plain_top_n(self):
        scores = pd.Series({"A": 1.0, "B": 3.0, "C": 2.0, "D": np.nan})
        self.assertEqual(pf.turnover_buffer(scores, [], 2), ["B", "C"])


class TestPortfolioVol(unittest.TestCase):
    def test_target_vol_scales_down_never_up_past_gross(self):
        cov = pd.DataFrame([[0.0004, 0.0], [0.0, 0.0004]], index=["A", "B"], columns=["A", "B"])
        w = pd.Series({"A": 0.5, "B": 0.5})
        v = pf.portfolio_vol(w, cov)             # ~0.27 annualized
        self.assertGreater(v, 0.2)
        out = pf.target_portfolio_vol(w, cov, target=0.10)
        self.assertAlmostEqual(pf.portfolio_vol(out, cov), 0.10, places=6)
        big = pf.target_portfolio_vol(w, cov, target=1.0)
        self.assertLessEqual(big.sum(), 1.0 + 1e-9)


class TestTCA(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_tsmom_rows_store_traded_and_tca_reads_them(self):
        acc = tsmom.Account(self.dir / "t.db")
        acc.cash = 100.0
        px = pd.Series({"SPY": 10.0, "GLD": 20.0})
        traded = acc.rebalance(px, {"SPY": 0.5, "GLD": 0.5})
        acc.save(1_700_000_000, acc.equity(px), {"SPY": 0.5, "GLD": 0.5}, "init", traded=traded)
        acc.save(1_700_000_000 + 86400 * 30, acc.equity(px), {"SPY": 0.5, "GLD": 0.5}, "mark")
        t = tca.account_tca(self.dir / "t.db", "account", tsmom.COST)
        self.assertEqual(t.n, 1)
        self.assertFalse(t.any_estimated)
        self.assertAlmostEqual(t.trades[0].traded, 100.0, places=6)
        self.assertAlmostEqual(t.total_cost, 100.0 * tsmom.COST, places=8)
        self.assertGreater(t.turnover_per_year, 0)
        self.assertIn("bps", tca.format_line(t))

    def test_xs_rows_without_traded_are_estimated(self):
        acc = xs.XSAccount(self.dir / "x.db")
        acc.cash = 600.0
        px = pd.Series({"A": 10.0, "B": 20.0})
        acc.rebalance(px, {"A": 0.5, "B": 0.5})
        acc.save(1_700_000_000, acc.equity(px), {"A": 0.5, "B": 0.5}, {}, {"A": 300.0, "B": 300.0}, 600.0, "init")
        acc.db.execute("UPDATE xs_account SET traded = NULL")
        acc.db.commit()
        t = tca.account_tca(self.dir / "x.db", "xs_account", xs.COST)
        self.assertEqual(t.n, 1)
        self.assertTrue(t.any_estimated)
        self.assertAlmostEqual(t.trades[0].traded, 600.0)

    def test_missing_db_is_empty_not_an_error(self):
        t = tca.account_tca(self.dir / "nope.db", "account", 0.001)
        self.assertEqual(t.n, 0)
        self.assertEqual(tca.format_line(t), "no trades yet")


if __name__ == "__main__":
    unittest.main(verbosity=2)
