"""#33's measure: settlements at their minute and scaled to 8 hours, Monday 00:00 only,
the drift from P(00:00), the buckets and the criteria."""
from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from espero import fillcost as fc

MON = int(pd.Timestamp("2024-03-04", tz="UTC").timestamp())        # a Monday


def bars(first, days, price=100.0):
    ts = np.arange(first - 86400, first + days * 86400, fc.BAR_S)
    return pd.DataFrame({"open": price, "close": price}, index=pd.Index(ts, name="ts"))


class TestSettlements(unittest.TestCase):
    def test_minute_and_8_hour_scale(self):
        rows = [{"fundingTime": (MON - 14400) * 1000 + 7, "fundingRate": "0.0002"},
                {"fundingTime": MON * 1000 + 3, "fundingRate": "0.0003"}]      # a 4-hour coin
        s = fc.settlements(rows)
        self.assertEqual(s["ts"].tolist(), [MON - 14400, MON])
        self.assertAlmostEqual(s["rate8"].iloc[1], 0.0006)
        self.assertAlmostEqual(s["rate8"].iloc[0], 0.0002)         # first row: no previous, taken as 8 hours

    def test_buckets(self):
        self.assertEqual([fc.bucket(x) for x in (0.0005, 0.0001, -0.0005, -0.0004)],
                         ["longs pay", "normal", "shorts pay", "normal"])


class TestEvents(unittest.TestCase):
    def test_monday_00_00_drift(self):
        b = bars(MON, 3)
        b.loc[b.index >= MON + 600, "open"] = 101.0          # recovers from 00:10
        fund = pd.DataFrame({"ts": [MON - 28800, MON, MON + 28800, MON + 86400], "rate8": [0.0, 0.0007, 0.0, 0.0]})
        ev = fc.events(b, fund, "2024-01-01", "2024-12-31")
        self.assertEqual(len(ev), 1)                          # 08:00, and Tuesday's 00:00, are not Monday 00:00
        e = ev.iloc[0]
        self.assertEqual((e["day"], e["bucket"]), ("2024-03-04", "longs pay"))
        self.assertAlmostEqual(e["m15"], 0.01)
        self.assertAlmostEqual(e["m30"], 0.01)

    def test_every_day_and_other_hours_on_request(self):
        b = bars(MON, 3)
        fund = pd.DataFrame({"ts": [MON, MON + 28800, MON + 86400], "rate8": [0.0, 0.0, 0.0]})
        self.assertEqual(len(fc.events(b, fund, "2024-01-01", "2024-12-31", mondays=False)), 2)
        self.assertEqual(len(fc.events(b, fund, "2024-01-01", "2024-12-31", hour=8, mondays=False)), 1)

    def test_a_missing_bar_leaves_the_drift_empty(self):
        b = bars(MON, 3).drop(MON + 1800)
        fund = pd.DataFrame({"ts": [MON], "rate8": [0.0]})
        e = fc.events(b, fund, "2024-01-01", "2024-12-31").iloc[0]
        self.assertTrue(np.isnan(e["m30"]))
        self.assertFalse(np.isnan(e["m15"]))


def frame(longs, shorts, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for d in pd.date_range(fc.FIRST, fc.LAST, freq="W-MON"):
        for bkt, mu in (("longs pay", longs), ("shorts pay", shorts), ("normal", 0.0)):
            rows.append({"day": d.strftime("%Y-%m-%d"), "bucket": bkt, "m30": mu + rng.normal(0, 0.0002)})
    return pd.DataFrame(rows)


class TestCriteria(unittest.TestCase):
    def test_all_four(self):
        crit = fc.criteria(frame(0.001, -0.001))
        self.assertEqual([c["met"] for c in crit], [True, True, True, True])
        self.assertEqual(fc.verdict(crit), "PASS")

    def test_real_but_small(self):
        crit = fc.criteria(frame(0.0003, -0.001))
        self.assertEqual([c["met"] for c in crit], [True, False, True, True])
        self.assertEqual(fc.verdict(crit), "FAIL")

    def test_one_era(self):
        f = frame(0.001, -0.001)
        f.loc[(f["day"] >= fc.HALF) & (f["bucket"] == "longs pay"), "m30"] = -0.0005
        self.assertFalse(fc.criteria(f)[3]["met"])


if __name__ == "__main__":
    unittest.main()
