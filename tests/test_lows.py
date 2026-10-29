"""#20's pieces: #18's breakdown trigger exactly, one event per coin per hour,
returns from the next open, #18's days left out, and the four criteria."""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from espero import liq as lq
from espero import lows as lw
from tests.test_liq import DAY, at, plant_up, quiet

ROOT = Path(__file__).resolve().parents[1]


def flipped(b):
    """The mirror image of a frame: an up-break becomes a down-break."""
    return pd.DataFrame({"open": 1e4 / b["open"], "high": 1e4 / b["low"], "low": 1e4 / b["high"],
                         "close": 1e4 / b["close"], "volume": b["volume"]}, index=b.index)


class TestDays(unittest.TestCase):
    def test_18s_days_and_their_neighbours(self):
        x = lw.excluded_days()
        for d in ("2019-12-31", "2020-01-01", "2020-01-02", "2026-03-31", "2026-04-01"):
            self.assertIn(d, x)
        self.assertNotIn("2020-01-03", x)


class TestEvents(unittest.TestCase):
    def setUp(self):
        self.t = at(10, day=DAY + 10 * 86400)               # the 11th of the month, a used day
        self.b = flipped(plant_up(quiet(day_start=DAY + 10 * 86400), self.t))

    def test_the_trigger_is_18s_down_exactly(self):
        f = lq.triggers(self.b)
        ev = lw.events(self.b, "down", skip=set(), first="2000-01-01", last="2100-01-01")
        self.assertEqual(len(ev), int(f["down"].sum()))
        self.assertEqual(ev.iloc[0]["ts"], self.t + 300)

    def test_long_returns_from_the_next_open(self):
        ev = lw.events(self.b, "down", skip=set(), first="2000-01-01", last="2100-01-01")
        e = ev.iloc[0]
        b = self.b
        entry = b.loc[self.t + 300, "open"]
        self.assertAlmostEqual(e["r60"], b.loc[self.t + 12 * 300, "close"] / entry - 1)
        self.assertAlmostEqual(e["r15"], b.loc[self.t + 3 * 300, "close"] / entry - 1)
        self.assertGreater(e["r60"], 0)                    # the planted fade, mirrored, is a bounce

    def test_a_used_day_is_left_out(self):
        day = lw.day_of(self.t)
        self.assertEqual(len(lw.events(self.b, "down", skip={day}, first="2000-01-01", last="2100-01-01")), 0)

    def test_one_per_hour_and_gaps_stay_empty(self):
        b = flipped(plant_up(plant_up(quiet(day_start=DAY + 10 * 86400), self.t, after=102.0), self.t + 12 * 300,
                             close=106.0, after=104.0))
        self.assertEqual(len(lw.events(b, "down", skip=set(), first="2000-01-01", last="2100-01-01")), 1)
        gap = self.b.drop(index=[self.t + 12 * 300])
        e = lw.events(gap, "down", skip=set(), first="2000-01-01", last="2100-01-01").iloc[0]
        self.assertTrue(np.isnan(e["r60"]))
        self.assertFalse(np.isnan(e["r15"]))

    def test_kline_times_in_ms_or_us(self):
        k = pd.DataFrame({"open_time": [DAY * 1000, (DAY + 300) * 1000], "open": [1.0, 2.0], "high": [2.0, 3.0],
                          "low": [0.5, 1.5], "close": [2.0, 3.0], "volume": [1.0, 1.0]})
        pd.testing.assert_frame_equal(lw.bars(k), lw.bars(k.assign(open_time=k["open_time"] * 1000)))


def table(days=60, mean=0.003, noise=0.002, r15=0.001, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for k in range(days):
        day = (pd.Timestamp("2020-02-01") + pd.Timedelta(days=k * 35)).strftime("%Y-%m-%d")
        for _ in range(3):
            rows.append({"day": day, "direction": "down", "r15": r15 + rng.normal(0, noise / 3),
                         "r60": mean + rng.normal(0, noise), "r240": 0.0})
    return pd.DataFrame(rows)


class TestCriteria(unittest.TestCase):
    def test_a_bounce_that_pays(self):
        rows = lw.criteria(table())
        self.assertEqual([r["met"] for r in rows], [True, True, True, True])

    def test_real_but_too_small(self):
        rows = lw.criteria(table(mean=0.0008, noise=0.0005))
        self.assertEqual([r["met"] for r in rows], [True, True, True, False])
        self.assertEqual(lw.verdict(rows), "real, not tradable after costs")

    def test_no_bounce_at_once(self):
        self.assertFalse(lw.criteria(table(r15=-0.002))[1]["met"])

    def test_one_era_only(self):
        ev = table()
        ev.loc[ev["day"] >= lw.SPLIT, "r60"] *= -1
        self.assertFalse(lw.criteria(ev)[2]["met"])

    def test_breakouts_do_not_count(self):
        up = table(mean=0.01).assign(direction="up")              # strong breakouts would carry a mixed average
        rows = lw.criteria(pd.concat([up, table(mean=-0.0005, noise=0.0002)]))
        self.assertRegex(rows[0]["actual"], r"^-[45]\.\d bps")
        self.assertFalse(rows[0]["met"])

    def test_a_weak_bounce_is_not_enough(self):
        rows = lw.criteria(table(mean=0.0003, noise=0.01, seed=4))
        self.assertRegex(rows[0]["actual"], r"t [0-2]\.\d\d")
        self.assertFalse(rows[0]["met"])


class TestDownloads(unittest.TestCase):
    def test_window(self):
        spec = importlib.util.spec_from_file_location("research_lows", ROOT / "research" / "lows.py")
        r = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(r)
        self.assertEqual((r.MONTHS[0], r.MONTHS[-1], len(r.MONTHS)), ("2019-12", "2026-03", 76))
        self.assertIn("/5m/BTCUSDT-5m-2020-01.zip", r.URL.format(sym="BTCUSDT", month="2020-01"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
