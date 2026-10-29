"""#35: yesterday's low from a full previous day, the first sweep 10 bps through it, the
reclaim within 15 minutes, the long from the next open, failures measured alike."""
from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from espero import sweeps as sw

D1 = int(pd.Timestamp("2024-03-05", tz="UTC").timestamp())


def two_days(low_y=99.0, price=100.0):
    """Day 1 flat at `price` with one bar's low at `low_y`; day 2 flat at `price`."""
    ts = np.arange(D1 - 86400, D1 + 86400, sw.BAR_S)
    b = pd.DataFrame({"open": price, "high": price, "low": price, "close": price}, index=pd.Index(ts, name="ts"))
    b.loc[D1 - 86400 + 3600, "low"] = low_y
    return b


def at(minutes):
    return D1 + minutes * 60


class TestEvents(unittest.TestCase):
    def test_a_reclaimed_sweep_and_the_long_after_it(self):
        b = two_days()
        b.loc[at(60), ["low", "close"]] = [98.8, 98.9]       # through 99 by more than 10 bps, closes below
        b.loc[at(65), ["close"]] = 99.2                      # back above within 15 minutes
        b.loc[b.index >= at(70), ["open", "high", "low", "close"]] = 99.5
        b.loc[at(70) + 11 * sw.BAR_S, "close"] = 100.5       # the 12th bar from the entry
        ev = sw.events(b, "2024-03-05", "2024-03-05")
        self.assertEqual(len(ev), 1)
        e = ev.iloc[0]
        self.assertEqual((e["kind"], e["level"]), ("reclaimed", 99.0))
        self.assertAlmostEqual(e["r60"], 100.5 / 99.5 - 1)
        self.assertEqual(e["ts"], at(65) + sw.BAR_S)

    def test_less_than_10_bps_through_is_no_sweep(self):
        b = two_days()
        b.loc[at(60), "low"] = 99.0 * (1 - 0.0005)
        self.assertTrue(sw.events(b, "2024-03-05", "2024-03-05").empty)

    def test_no_close_back_within_15_minutes_is_failed(self):
        b = two_days()
        b.loc[b.index >= at(60), ["open", "high", "low", "close"]] = 98.5
        b.loc[at(80), "close"] = 99.5                         # back above only in the 5th bar
        e = sw.events(b, "2024-03-05", "2024-03-05").iloc[0]
        self.assertEqual(e["kind"], "failed")
        self.assertAlmostEqual(e["r60"], 98.5 / b.loc[at(80), "open"] - 1)   # entry at the open of bar j+4

    def test_only_the_first_sweep_a_day(self):
        b = two_days()
        b.loc[at(60), ["low"]] = 98.0
        b.loc[at(300), ["low"]] = 97.0
        self.assertEqual(len(sw.events(b, "2024-03-05", "2024-03-05")), 1)

    def test_an_incomplete_previous_day_is_skipped(self):
        b = two_days().drop(D1 - 3600)
        b.loc[at(60), "low"] = 98.0
        self.assertTrue(sw.events(b, "2024-03-05", "2024-03-05").empty)

    def test_the_short_side_mirrors(self):
        b = two_days()
        b.loc[D1 - 86400 + 3600, "high"] = 101.0
        b.loc[at(60), ["high", "close"]] = [101.2, 100.8]     # through 101, back below it in the same bar
        b.loc[b.index >= at(65), ["open", "high", "low", "close"]] = 100.8
        b.loc[at(65) + 11 * sw.BAR_S, "close"] = 100.0
        e = sw.events(b, "2024-03-05", "2024-03-05", side="high").iloc[0]
        self.assertEqual(e["kind"], "reclaimed")
        self.assertAlmostEqual(e["r60"], -(100.0 / 100.8 - 1))

    def test_round_number_levels(self):
        b = two_days(price=80_350.0, low_y=80_350.0)
        b.loc[at(60), ["low", "close"]] = [79_900.0, 80_100.0]
        e = sw.events(b, "2024-03-05", "2024-03-05", step=1000).iloc[0]
        self.assertEqual((e["level"], e["kind"]), (80_000.0, "reclaimed"))


def frame(rec, fail, seed=0):
    rng = np.random.default_rng(seed)
    out = []
    for d in pd.date_range(sw.FIRST, sw.LAST, freq="3D"):
        for kind, mu in (("reclaimed", rec), ("failed", fail)):
            out.append({"day": d.strftime("%Y-%m-%d"), "side": "low", "kind": kind, "r60": mu + rng.normal(0, 0.001)})
        out.append({"day": d.strftime("%Y-%m-%d"), "side": "high", "kind": "reclaimed", "r60": -0.05})
    return pd.DataFrame(out)


class TestCriteria(unittest.TestCase):
    def test_all_four(self):
        crit = sw.criteria(frame(0.003, 0.0))
        self.assertEqual([c["met"] for c in crit], [True, True, True, True])

    def test_real_not_tradable(self):
        crit = sw.criteria(frame(0.001, 0.0))
        self.assertEqual([c["met"] for c in crit], [True, True, True, False])
        self.assertEqual(sw.verdict(crit), "real, not tradable after costs")

    def test_no_better_than_failures(self):
        self.assertFalse(sw.criteria(frame(0.003, 0.003))[1]["met"])


if __name__ == "__main__":
    unittest.main()
