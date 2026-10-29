"""#28's pieces: the NYSE calendar, the Eastern clock across daylight saving, the
reference close, the signal taken from the bar before the entry, and the criteria."""
from __future__ import annotations

import datetime as dt
import unittest

import numpy as np
import pandas as pd

from espero import levetf as lv

D = dt.date


def utc(s: str) -> int:
    return int(pd.Timestamp(s, tz="UTC").timestamp())


def flat(first: str, last: str, price: float = 100.0) -> pd.DataFrame:
    ts = np.arange(utc(first), utc(last), lv.BAR_S)
    return pd.DataFrame({"open": price, "close": price}, index=pd.Index(ts, name="ts"))


def step(b: pd.DataFrame, t: int, price: float) -> None:
    """From the bar opening at t on, every bar opens and closes at `price`."""
    b.loc[b.index >= t, ["open", "close"]] = price


def one(b: pd.DataFrame, day: str) -> pd.Series:
    return lv.rows(b, "BTC", day, day).iloc[0]


class TestCalendar(unittest.TestCase):
    def test_sessions_per_year(self):
        for year, n in {2020: 253, 2021: 252, 2022: 251, 2023: 250, 2024: 252, 2025: 250}.items():
            got = sum(lv.kind(d) != "closed" for d in lv.days(f"{year}-01-01", f"{year}-12-31"))
            self.assertEqual(got, n, year)

    def test_kinds(self):
        self.assertEqual(lv.kind(D(2025, 1, 9)), "closed")      # a day of mourning
        self.assertEqual(lv.kind(D(2024, 11, 29)), "early")
        self.assertEqual(lv.kind(D(2024, 11, 30)), "closed")
        self.assertEqual(lv.kind(D(2024, 12, 2)), "trading")

    def test_eastern_clock_follows_daylight_saving(self):
        self.assertEqual(lv.at(D(2024, 7, 1), 16, 0), utc("2024-07-01 20:00"))
        self.assertEqual(lv.at(D(2024, 12, 2), 16, 0), utc("2024-12-02 21:00"))
        self.assertEqual(lv.at(D(2024, 3, 8), 16, 0), utc("2024-03-08 21:00"))   # Friday, still winter
        self.assertEqual(lv.at(D(2024, 3, 11), 16, 0), utc("2024-03-11 20:00"))  # Monday, summer time

    def test_reference_is_the_previous_session_close(self):
        self.assertEqual(lv.reference(D(2024, 12, 2)), lv.at(D(2024, 11, 29), 13, 0))   # after an early close
        self.assertEqual(lv.reference(D(2024, 12, 3)), lv.at(D(2024, 12, 2), 16, 0))
        self.assertEqual(lv.reference(D(2025, 1, 10)), lv.at(D(2025, 1, 8), 16, 0))    # over a closed day

    def test_a_closed_day_refers_to_16_00_the_day_before(self):
        self.assertEqual(lv.reference(D(2024, 11, 30)), lv.at(D(2024, 11, 29), 16, 0))

    def test_calendar_mismatches(self):
        sessions = [d.isoformat() for d in lv.days("2024-11-25", "2024-12-06") if lv.kind(d) != "closed"]
        self.assertEqual(lv.calendar_mismatches(sessions, "2024-11-25", "2024-12-06"), [])
        self.assertEqual(lv.calendar_mismatches([s for s in sessions if s != "2024-12-03"],
                                                "2024-11-25", "2024-12-06"), ["2024-12-03"])
        self.assertEqual(lv.calendar_mismatches(sessions + ["2024-11-30"], "2024-11-25", "2024-12-06"),
                         ["2024-11-30"])

    def test_eras(self):
        self.assertEqual(lv.era("2023-06-26"), "before")
        self.assertEqual(lv.era("2023-06-27"), "ramp")
        self.assertEqual(lv.era("2024-06-04"), "with")
        self.assertIsNone(lv.era("2026-10-29"))


class TestRows(unittest.TestCase):
    """A summer Tuesday: 100 at Monday's close, 101 from noon, 102 from 15:50 ET."""

    def setUp(self):
        self.d = D(2024, 7, 9)
        self.b = flat("2024-07-08", "2024-07-15")
        step(self.b, lv.at(self.d, 12, 0), 101.0)
        step(self.b, lv.at(self.d, 15, 50), 102.0)

    def test_an_up_day_and_a_late_rise(self):
        r = one(self.b, "2024-07-09")
        self.assertEqual(r["kind"], "trading")
        self.assertAlmostEqual(r["r"], 0.01)
        self.assertAlmostEqual(r["y"], 102 / 101 - 1)

    def test_a_down_day_flips_the_sign(self):
        b = flat("2024-07-08", "2024-07-15")
        step(b, lv.at(self.d, 12, 0), 99.0)
        step(b, lv.at(self.d, 15, 50), 100.0)
        r = one(b, "2024-07-09")
        self.assertAlmostEqual(r["r"], -0.01)
        self.assertAlmostEqual(r["y"], -(100 / 99 - 1))

    def test_the_signal_is_the_bar_before_the_entry(self):
        t = lv.at(self.d, 15, 45)
        self.b.loc[t, "close"] = 97.0             # the entry bar's own close must not set the sign
        r = one(self.b, "2024-07-09")
        self.assertAlmostEqual(r["r"], 0.01)
        self.assertAlmostEqual(r["y"], 102 / 101 - 1)

    def test_a_winter_day_uses_the_winter_clock(self):
        d = D(2024, 12, 10)
        b = flat("2024-12-08", "2024-12-12")
        step(b, lv.at(d, 12, 0), 101.0)
        step(b, lv.at(d, 15, 50), 102.0)          # 20:50 UTC in December
        self.assertAlmostEqual(one(b, "2024-12-10")["y"], 102 / 101 - 1)

    def test_a_missing_bar_leaves_the_day_empty(self):
        b = self.b.drop(lv.at(self.d, 16, 0))
        self.assertTrue(np.isnan(one(b, "2024-07-09")["y"]))

    def test_no_move_no_observation(self):
        b = flat("2024-07-08", "2024-07-15")
        step(b, lv.at(self.d, 15, 50), 102.0)
        r = one(b, "2024-07-09")
        self.assertEqual(r["r"], 0.0)
        self.assertTrue(np.isnan(r["y"]))

    def test_a_closed_day_is_measured_at_the_same_clock(self):
        d = D(2024, 7, 13)                         # Saturday
        b = flat("2024-07-08", "2024-07-15")
        step(b, lv.at(d, 12, 0), 101.0)
        step(b, lv.at(d, 15, 50), 102.0)
        r = one(b, "2024-07-13")
        self.assertEqual(r["kind"], "closed")
        self.assertAlmostEqual(r["y"], 102 / 101 - 1)

    def test_an_early_close_is_never_a_target(self):
        b = flat("2024-07-01", "2024-07-05")
        step(b, lv.at(D(2024, 7, 3), 12, 0), 101.0)
        r = one(b, "2024-07-03")
        self.assertEqual(r["kind"], "early")
        self.assertTrue(np.isnan(r["y"]))

    def test_after_the_close_is_signed_by_the_move_to_16_00(self):
        step(self.b, lv.at(self.d, 16, 5), 103.0)
        r = one(self.b, "2024-07-09")
        self.assertAlmostEqual(r["r_post15"], 0.02)
        self.assertAlmostEqual(r["post15"], 103 / 102 - 1)

    def test_the_utc_close(self):
        b = flat("2024-07-08", "2024-07-15")
        step(b, utc("2024-07-10 12:00"), 101.0)
        step(b, utc("2024-07-10 23:50"), 102.0)
        r = one(b, "2024-07-10")
        self.assertAlmostEqual(r["r_utc"], 0.01)
        self.assertAlmostEqual(r["utc"], 102 / 101 - 1)


def frame(y_with: float, y_closed: float, y_before: float, y_big: float, seed: int = 0) -> pd.DataFrame:
    """Rows for BTC and ETH: with-era trading days at y_with (y_big on |r| >= 2% days, every
    third date), with-era closed days at y_closed, before-era trading days at y_before."""
    rng = np.random.default_rng(seed)
    out = []
    for coin in lv.PRIMARY:
        for d in lv.days("2020-01-01", "2026-10-28"):
            s, k, e = d.isoformat(), lv.kind(d), lv.era(d.isoformat())
            big = d.toordinal() % 3 == 0
            if e == "with" and k == "trading":
                mu = y_big if big else y_with
            elif e == "with" and k == "closed":
                mu = y_closed
            elif e == "before" and k == "trading":
                mu = y_before
            else:
                continue
            out.append({"date": s, "coin": coin, "kind": k, "era": e, "r": 0.03 if big else 0.005,
                        "y": mu + rng.normal(0, 0.001)})
    return pd.DataFrame(out)


class TestCriteria(unittest.TestCase):
    def test_all_four(self):
        crit = lv.criteria(frame(0.003, 0.0, 0.0, 0.003))
        self.assertEqual([c["met"] for c in crit], [True, True, True, True])
        self.assertEqual(lv.verdict(crit), "PASS")

    def test_real_but_too_small_to_pay(self):
        crit = lv.criteria(frame(0.0005, 0.0, 0.0, 0.0005))
        self.assertEqual([c["met"] for c in crit], [True, True, True, False])
        self.assertEqual(lv.verdict(crit), "real, not tradable after costs")

    def test_it_pays_counts_only_big_days(self):
        crit = lv.criteria(frame(0.0005, 0.0, 0.0, 0.004))
        self.assertTrue(crit[3]["met"])
        self.assertRegex(crit[3]["actual"], r"^\+(39|40)\.\d bps")    # the big days' 40, not the mix's 17

    def test_the_same_push_on_closed_days_fails(self):
        crit = lv.criteria(frame(0.003, 0.003, 0.0, 0.003))
        self.assertFalse(crit[1]["met"])
        self.assertEqual(lv.verdict(crit), "FAIL")

    def test_only_btc_and_eth_count(self):
        f = frame(0.003, 0.0, 0.0, 0.003)
        extra = f[f["coin"] == "BTC"].assign(coin="SOL", y=-0.05)
        self.assertEqual([c["actual"] for c in lv.criteria(pd.concat([f, extra]))],
                         [c["actual"] for c in lv.criteria(f)])

    def test_welch(self):
        w = lv.welch(pd.Series([1.0, 2.0, 3.0]), pd.Series([0.0, 1.0, 2.0]))
        self.assertAlmostEqual(w["diff"], 1.0)
        self.assertAlmostEqual(w["t"], 1.0 / np.sqrt(1 / 3 + 1 / 3))


if __name__ == "__main__":
    unittest.main()
