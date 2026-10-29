"""#34: the placebo coins from their fund's first day only, SOL and XRP forward only, and
the three criteria's signs."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from espero import levetf as lv
from espero import levpush as lp


def rows(coins, first, last, y_trading, y_closed=0.0, seed=0):
    rng = np.random.default_rng(seed)
    out = []
    for c in coins:
        for d in lv.days(first, last):
            k = lv.kind(d)
            if k == "early":
                continue
            mu = y_trading if k == "trading" else y_closed
            out.append({"date": d.isoformat(), "coin": c, "kind": k, "y": mu + rng.normal(0, 0.0003)})
    return pd.DataFrame(out)


class TestRows(unittest.TestCase):
    def test_placebo_from_each_fund_s_first_day(self):
        r = rows(["ADA", "AVAX", "SOL"], "2026-03-01", "2026-10-31", 0.0)
        p = lp.placebo_rows(r)
        self.assertEqual(sorted(p["coin"].unique()), ["ADA", "AVAX"])
        self.assertEqual(p[p["coin"] == "ADA"]["date"].min(), "2026-04-01")
        self.assertEqual(p[p["coin"] == "AVAX"]["date"].min(), "2026-05-15")
        self.assertEqual(p["date"].max(), "2026-10-27")

    def test_forward_is_sol_and_xrp_in_the_window(self):
        r = rows(["SOL", "XRP", "BTC"], "2026-10-28", "2026-11-10", 0.0)
        f = lp.forward_rows(r)
        self.assertEqual(sorted(f["coin"].unique()), ["SOL", "XRP"])
        self.assertEqual(f["date"].min(), "2026-10-30")


class TestCriteria(unittest.TestCase):
    def test_all_three(self):
        p = lp.placebo_rows(rows(["ADA", "XLM"], "2026-04-01", "2026-10-27", 0.0))
        f = lp.forward_rows(rows(["SOL", "XRP"], "2026-10-30", "2027-03-31", 0.0008))
        crit = lp.criteria(p, f)
        self.assertEqual([c["met"] for c in crit], [True, True, True])
        self.assertEqual(lp.verdict(crit), "PASS")

    def test_a_push_on_the_placebo_fails_it(self):
        p = lp.placebo_rows(rows(["ADA", "XLM"], "2026-04-01", "2026-10-27", 0.0008))
        crit = lp.criteria(p)
        self.assertFalse(crit[0]["met"])
        self.assertEqual(lp.verdict(crit), "FAIL")

    def test_no_forward_rows_yet(self):
        p = lp.placebo_rows(rows(["ADA"], "2026-04-01", "2026-10-27", 0.0))
        crit = lp.criteria(p)
        self.assertTrue(crit[0]["met"])
        self.assertFalse(crit[1]["met"] or crit[2]["met"])


class TestRun(unittest.TestCase):
    def test_reads_29s_ledger(self):
        with tempfile.TemporaryDirectory() as s:
            self.assertEqual(lp.run(Path(s))["note"], "mark: 0 trading days")
            rows(["SOL", "XRP", "BTC"], "2026-10-30", "2026-11-06", 0.001).to_csv(Path(s) / lp.LEDGER_IN, index=False)
            out = lp.run(Path(s))
        self.assertIn("6 trading days", out["note"])
        self.assertIn("decides nothing", out["note"])


if __name__ == "__main__":
    unittest.main()
