"""#25: open interest at or before a time, the drop over a breakdown's hour, and
the criteria on #18's within-day grouping."""
from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from espero import oi


class TestSeries(unittest.TestCase):
    def test_snapshots_and_the_drop(self):
        m = pd.DataFrame({"create_time": ["2026-01-02 00:00:00", "2026-01-02 00:05:00", "2026-01-02 01:00:00"],
                          "sum_open_interest": [100.0, 95.0, 80.0]})
        s = oi.series(m)
        t0 = int(pd.Timestamp("2026-01-02", tz="UTC").timestamp())
        self.assertEqual(list(s.index), [t0, t0 + 300, t0 + 3600])
        got = oi.at_or_before(s, np.array([t0 - 1, t0 + 299, t0 + 3700]))
        self.assertTrue(np.isnan(got[0]))
        self.assertEqual(list(got[1:]), [100.0, 80.0])
        ev = pd.DataFrame({"ts": [t0 + 3600, t0 + 3000]})
        d = oi.drop(ev, s)
        self.assertAlmostEqual(d[0], (100 - 80) / 100)     # an hour before: 00:00; at the close: 01:00
        self.assertTrue(np.isnan(d[1]))                    # no snapshot an hour before 00:50


def table(days=60, effect=0.004, base=0.002, noise=0.002, seed=0, late_flip=False):
    rng = np.random.default_rng(seed)
    rows = []
    for k in range(days):
        day = (pd.Timestamp("2021-02-01") + pd.Timedelta(days=k * 30)).strftime("%Y-%m-%d")
        flip = -1 if (late_flip and day >= oi.SPLIT) else 1
        for i in range(9):
            d = i / 100
            y = base + (flip * effect if i >= 6 else 0.0) + rng.normal(0, noise)
            rows.append({"day": day, "coin": f"C{(i + k) % 9}", "oi_drop": d, "r60": y, "r240": y})   # coins rotate
    return pd.DataFrame(rows)


class TestCriteria(unittest.TestCase):
    def test_forced_breakdowns_that_bounce_more_and_pay(self):
        rows = oi.criteria(table(effect=0.004, base=0.002))
        self.assertEqual([r["met"] for r in rows], [True, True, True, True])

    def test_real_but_small(self):
        rows = oi.criteria(table(effect=0.0008, base=0.0, noise=0.0003))
        self.assertEqual([r["met"] for r in rows], [True, True, True, False])

    def test_one_era(self):
        self.assertFalse(oi.criteria(table(late_flip=True))[2]["met"])

    def test_no_difference(self):
        self.assertFalse(oi.criteria(table(effect=0.0, noise=0.003))[0]["met"])


if __name__ == "__main__":
    unittest.main()
