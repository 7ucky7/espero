"""#36: Monday weeks, the supply flow set against NEXT week's funding change (not this
week's), least squares recovering a planted coefficient, and the criteria's signs."""
from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from espero import ethena as et


def ts(s):
    return int(pd.Timestamp(s, tz="UTC").timestamp())


class TestWeeks(unittest.TestCase):
    def test_monday_weeks(self):
        w = et.week_of([ts("2024-03-04 00:00"), ts("2024-03-10 23:59"), ts("2024-03-11 00:00")])
        self.assertEqual([str(x.date()) for x in w], ["2024-03-04", "2024-03-04", "2024-03-11"])

    def test_supply_is_the_week_s_last_day(self):
        rows = [{"date": ts(d), "circulating": {"peggedUSD": v}}
                for d, v in (("2024-03-04", 1.0), ("2024-03-09", 2.0), ("2024-03-12", 3.0))]
        s = et.weekly_supply(rows)
        self.assertEqual(s.tolist(), [2.0, 3.0])


class TestRegression(unittest.TestCase):
    def test_recovers_a_planted_coefficient(self):
        rng = np.random.default_rng(1)
        x = rng.normal(size=(500, 2))
        y = 0.5 - 2.0 * x[:, 0] + 0.3 * x[:, 1] + rng.normal(0, 0.5, 500)
        r = et.ols_nw(y, x)
        self.assertAlmostEqual(r["beta"][1], -2.0, delta=0.1)
        self.assertLess(r["t"][1], -20)

    def test_newey_west_widens_with_autocorrelation(self):
        rng = np.random.default_rng(2)
        e = np.convolve(rng.normal(size=520), np.ones(10) / 10, mode="valid")[:500]   # autocorrelated
        x = np.convolve(rng.normal(size=520), np.ones(10) / 10, mode="valid")[:500]
        y = 0.2 * x + e
        plain, nw = et.ols_nw(y, x[:, None], lags=0), et.ols_nw(y, x[:, None], lags=8)
        self.assertGreater(nw["se"][1], plain["se"][1])


def series(flow_effect, seed=0):
    """Weekly flow and funding where next week's funding change is flow_effect * flow."""
    rng = np.random.default_rng(seed)
    weeks = pd.date_range(et.FIRST_WEEK, "2026-11-02", freq="W-MON")
    flow = pd.Series(rng.normal(0, 0.03, len(weeks)), index=weeks)
    f = np.zeros(len(weeks))
    f[0] = 0.1
    for i in range(1, len(weeks)):
        f[i] = 0.1 + 0.6 * (f[i - 1] - 0.1) + flow_effect * flow.iloc[i - 1] + rng.normal(0, 0.005)
    return flow, pd.Series(f, index=weeks)


class TestCriteria(unittest.TestCase):
    def test_redemptions_raise_funding(self):
        flow, f = series(-0.5)
        crit = et.criteria(flow, f, f)
        self.assertEqual([c["met"] for c in crit], [True, True, True])
        self.assertEqual(et.verdict(crit), "PASS")

    def test_no_effect_fails(self):
        flow, f = series(0.0)
        self.assertEqual(et.verdict(et.criteria(flow, f, f)), "FAIL")

    def test_the_flow_is_set_against_next_week(self):
        flow, f = series(-0.5)
        d = et.design(flow, f)
        w = d.index[5]
        self.assertAlmostEqual(d.loc[w, "y"], f.shift(-1).loc[w] - f.loc[w])
        self.assertAlmostEqual(d.loc[w, "flow"], flow.loc[w])


if __name__ == "__main__":
    unittest.main()
