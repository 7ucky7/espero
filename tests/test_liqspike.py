"""#21's pieces: a causal spike threshold, one event per cascade, returns from the
spike hour's close, the baseline, the four criteria, and the seal check."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from espero import liqspike as ls

ROOT = Path(__file__).resolve().parents[1]
H0 = pd.Timestamp("2026-06-01", tz="UTC")


def hourly(n=900, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range(H0, periods=n, freq="h")
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.002, n)))
    # a steady background, so only the planted hours can clear the 98th percentile
    return pd.DataFrame({"open": np.r_[close[0], close[:-1]], "close": close, "volume": 1e6,
                         "long": 1e3, "short": 1e3}, index=idx)


class TestSpikes(unittest.TestCase):
    def test_judged_on_the_past_only(self):
        df = hourly()
        df.iloc[750, df.columns.get_loc("long")] = 5e4
        whole = ls.spikes(df, "long", H0, H0 + pd.Timedelta(hours=899))
        self.assertIn(df.index[750], whole)
        later = df.copy()
        later.iloc[800:, later.columns.get_loc("long")] = 9e9          # a future flood changes nothing before it
        self.assertEqual(list(ls.spikes(later, "long", H0, df.index[790])), list(whole[whole <= df.index[790]]))

    def test_noise_at_the_edge_of_the_window_is_allowed_to_be_a_spike(self):
        df = hourly()
        rng = np.random.default_rng(1)
        df["long"] = rng.uniform(1e3, 2e3, len(df))           # random hours clear the 98th percentile ~2% of the time
        n = len(ls.spikes(df, "long", df.index[600], df.index[899]))
        self.assertTrue(0 < n < 15)

    def test_the_threshold_needs_600_earlier_hours(self):
        for hour, counted in ((599, False), (600, True)):           # hour 599 has only 599 hours before it
            df = hourly()
            df.iloc[hour, df.columns.get_loc("long")] = 5e4
            s = ls.spikes(df, "long", H0, H0 + pd.Timedelta(hours=899))
            self.assertEqual(df.index[hour] in s, counted, hour)

    def test_no_threshold_before_600_hours(self):
        df = hourly()
        df.iloc[500, df.columns.get_loc("long")] = 5e4
        self.assertNotIn(df.index[500], ls.spikes(df, "long", H0, H0 + pd.Timedelta(hours=899)))

    def test_one_event_per_cascade_even_across_the_window_start(self):
        df = hourly()
        for h in (700, 703, 708, 760):
            df.iloc[h, df.columns.get_loc("long")] = 5e4
        s = ls.spikes(df, "long", df.index[702], df.index[899])
        # 703 follows 700 within 6h (700 is before the window, still the same cascade); 708 is 5h after 703
        self.assertEqual(list(s), [df.index[760]])

    def test_an_hour_without_liquidations_is_never_a_spike(self):
        df = hourly()
        df["short"] = 0.0
        self.assertEqual(len(ls.spikes(df, "short", H0, H0 + pd.Timedelta(hours=899))), 0)


class TestEvents(unittest.TestCase):
    def test_returns_from_the_spike_hours_close(self):
        df = hourly()
        df.iloc[750, df.columns.get_loc("long")] = 5e4
        df.iloc[751, df.columns.get_loc("open")] = df["close"].iat[750] * 1.01   # the next hour gaps up
        ev = ls.events({"BTC": df}, H0, H0 + pd.Timedelta(hours=899))
        e = ev[ev["t"] == df.index[750]].iloc[0]
        self.assertAlmostEqual(e["r24"], np.log(df["close"].iat[774] / df["close"].iat[750]))
        self.assertAlmostEqual(e["r24_open"], np.log(df["close"].iat[774] / df["open"].iat[751]))
        self.assertEqual(e["side"], "long")

    def test_baseline_is_the_windows_mean(self):
        df = hourly()
        start, end = df.index[700], df.index[800]
        lc = np.log(df["close"])
        expect = float((lc.shift(-4) - lc).loc[start:end].mean())
        self.assertAlmostEqual(ls.baseline({"X": df}, start, end)[4], expect)


def synthetic(days=60, long_x=0.006, short_x=-0.006, raw_long=0.006, late_only_reverse=False, noise=0.002):
    rng = np.random.default_rng(3)
    rows = []
    for k in range(days):
        t = pd.Timestamp("2026-07-01", tz="UTC") + pd.Timedelta(days=2 * k)
        flip = -1.0 if (late_only_reverse and t >= pd.Timestamp(ls.SPLIT, tz="UTC")) else 1.0
        for side, x in (("long", long_x), ("short", short_x)):
            r24 = flip * x + rng.normal(0, noise) + (raw_long - long_x if side == "long" else 0.0)
            rows.append({"coin": "BTC", "side": side, "t": t, "day": t.strftime("%Y-%m-%d"),
                         "r1": 0.0, "r4": 0.0, "r24": r24, "r24_open": r24})
    return pd.DataFrame(rows)


BASE = {1: 0.0, 4: 0.0, 24: 0.0}


class TestCriteria(unittest.TestCase):
    def test_a_reversal_that_pays_passes(self):
        rows = ls.criteria(synthetic(), BASE)
        self.assertEqual([r["met"] for r in rows], [True, True, True, True])

    def test_real_but_the_market_ate_the_long_leg(self):
        rows = ls.criteria(synthetic(raw_long=0.0005), BASE)
        self.assertEqual([r["met"] for r in rows], [True, True, True, False])
        self.assertEqual(ls.verdict(rows), "real, not tradable after costs")

    def test_shorts_that_keep_rising_fail_criterion_2(self):
        rows = ls.criteria(synthetic(short_x=0.002), BASE)
        self.assertFalse(rows[1]["met"])

    def test_one_stretch_only(self):
        self.assertFalse(ls.criteria(synthetic(late_only_reverse=True), BASE)[2]["met"])

    def test_the_baseline_is_subtracted(self):
        rows = ls.criteria(synthetic(long_x=0.003, short_x=-0.003, raw_long=0.003, noise=0.0001),
                           {1: 0, 4: 0, 24: 0.004})
        self.assertIn("longs -10.", rows[1]["actual"])        # 30 bps raw, 40 bps average day: -10 excess
        self.assertFalse(rows[1]["met"])

    def test_the_long_leg_is_raw_not_net_of_the_baseline(self):
        # 10 bps raw in a falling market (baseline -50 bps): a +60 bps excess, but a buyer made 10 bps
        rows = ls.criteria(synthetic(long_x=0.001, short_x=-0.006, raw_long=0.001, noise=0.0005),
                           {1: 0, 4: 0, 24: -0.005})
        self.assertTrue(rows[1]["met"])
        self.assertFalse(rows[3]["met"])

    def test_a_weak_reversal_is_not_enough(self):
        rows = ls.criteria(synthetic(long_x=0.0003, short_x=-0.0003, noise=0.01), BASE)
        self.assertFalse(rows[0]["met"])


class TestSeal(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("research_liqspike", ROOT / "research" / "liqspike.py")
        self.r = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.r)

    def test_a_changed_file_stops_the_run(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "holdout").mkdir()
            f = Path(d) / "holdout" / "2026-07.csv.gz"
            f.write_bytes(b"sealed")
            m = Path(d) / "m.json"
            m.write_text(json.dumps({"files": {"2026-07.csv.gz": hashlib.sha256(b"sealed").hexdigest()}}))
            self.r.verify(Path(d), m)                                  # unchanged: passes
            f.write_bytes(b"edited")
            with self.assertRaises(RuntimeError):
                self.r.verify(Path(d), m)

    def test_the_real_seal_still_holds(self):
        ax_spec = importlib.util.spec_from_file_location("aggr_explore", ROOT / "research" / "aggr_explore.py")
        ax = importlib.util.module_from_spec(ax_spec)
        ax_spec.loader.exec_module(ax)
        if not (ax.DATA / "holdout").exists():
            self.skipTest("sealed files not on this machine")
        self.r.verify(ax.DATA, ax.MANIFEST)


if __name__ == "__main__":
    unittest.main(verbosity=2)
