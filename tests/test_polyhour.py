"""#37: the slug for each Eastern hour, the crowd's last fresh price, the random walk's
probability, the bet's profit on both sides, and the criteria."""
from __future__ import annotations

import datetime as dt
import math
import unittest

import numpy as np
import pandas as pd

from espero import polyhour as ph


class TestSlugsAndClock(unittest.TestCase):
    def test_slugs(self):
        d = dt.date(2026, 10, 27)
        self.assertEqual(ph.slug(d, 14), "bitcoin-up-or-down-october-27-2026-2pm-et")
        self.assertEqual(ph.slug(d, 0), "bitcoin-up-or-down-october-27-2026-12am-et")
        self.assertEqual(ph.slug(d, 12), "bitcoin-up-or-down-october-27-2026-12pm-et")
        self.assertEqual(ph.slug(dt.date(2026, 5, 1), 9), "bitcoin-up-or-down-may-1-2026-9am-et")

    def test_hour_start_in_eastern_time(self):
        self.assertEqual(ph.hour_start(dt.date(2026, 10, 27), 14),
                         int(pd.Timestamp("2026-10-27 18:00", tz="UTC").timestamp()))


class TestCrowd(unittest.TestCase):
    def test_last_fresh_price(self):
        h = [{"t": 1000, "p": 0.4}, {"t": 1060, "p": 0.55}, {"t": 1200, "p": 0.9}]
        self.assertEqual(ph.crowd(h, 1100), 0.55)
        self.assertTrue(math.isnan(ph.crowd(h, 1300, stale=60)))       # the last one is 100 s old
        self.assertTrue(math.isnan(ph.crowd(h, 900)))                   # nothing yet


def bars(t0, sigma_5m=0.002, p0=100.0, p30=100.0, seed=0):
    rng = np.random.default_rng(seed)
    ts = np.arange(t0 - 288 * ph.BAR_S, t0 + 3600, ph.BAR_S)
    px = p0 * np.exp(np.r_[np.cumsum(rng.normal(0, sigma_5m, 288))[::-1] * 0, np.zeros(len(ts) - 288)])
    b = pd.DataFrame({"open": px}, index=pd.Index(ts, name="ts"))
    past = p0 * np.exp(np.cumsum(rng.normal(0, sigma_5m, 289)) - np.cumsum(rng.normal(0, sigma_5m, 289))[-1] * 0)
    b.loc[ts[:289], "open"] = past / past[-1] * p0
    b.loc[t0 + 1800, "open"] = p30
    return b


class TestModel(unittest.TestCase):
    def test_no_move_is_a_coin_flip(self):
        t0 = 1_800_000_000
        self.assertAlmostEqual(ph.model(bars(t0), t0), 0.5, places=6)

    def test_up_moves_raise_the_chance(self):
        t0 = 1_800_000_000
        b = bars(t0, p30=100.3)
        q = ph.model(b, t0)
        sigma = float(np.log(b["open"].loc[t0 - 288 * ph.BAR_S:t0]).diff().dropna().std(ddof=1)) / math.sqrt(5)
        z = math.log(100.3 / 100.0) / (sigma * math.sqrt(30))
        self.assertAlmostEqual(q, 0.5 * (1 + math.erf(z / math.sqrt(2))))
        self.assertGreater(q, 0.5)

    def test_a_gap_in_the_day_before_gives_nothing(self):
        t0 = 1_800_000_000
        self.assertTrue(math.isnan(ph.model(bars(t0).drop(t0 - 3600), t0)))


class TestBet(unittest.TestCase):
    def test_both_sides(self):
        self.assertAlmostEqual(ph.bet(0.40, 0.60, 1.0), 1 - 0.40 - 0.01)      # buy Up, it wins
        self.assertAlmostEqual(ph.bet(0.40, 0.60, 0.0), 0 - 0.40 - 0.01)      # buy Up, it loses
        self.assertAlmostEqual(ph.bet(0.70, 0.50, 0.0), 0.70 - 0.01)          # buy Down at 0.30, it wins
        self.assertTrue(math.isnan(ph.bet(0.50, 0.53, 1.0)))                  # under the threshold


def frame(edge, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for d in pd.date_range(ph.FIRST, ph.LAST):
        for _ in range(10):
            q = rng.uniform(0.2, 0.8)
            outcome = float(rng.random() < q)
            p = q - edge
            rows.append({"day": d.strftime("%Y-%m-%d"), "p": p, "q": q, "outcome": outcome,
                         "profit": ph.bet(p, q, outcome)})
    return pd.DataFrame(rows)


class TestCriteria(unittest.TestCase):
    def test_a_crowd_that_underprices_up(self):
        crit = ph.criteria(frame(0.10))
        self.assertEqual([c["met"] for c in crit], [True, True, True])

    def test_a_right_crowd_fails(self):
        crit = ph.criteria(frame(0.0))
        self.assertEqual(ph.verdict(crit), "FAIL")


if __name__ == "__main__":
    unittest.main()
