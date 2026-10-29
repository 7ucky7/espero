"""#19's pieces: 8-hour settlements with the previous rate, the hour before and
after each one and around its placebo, the baseline comparison, and the four
criteria with each day counted once."""
from __future__ import annotations

import importlib.util
import io
import json
import tempfile
import unittest
import urllib.error
import zipfile
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

from espero import settle as st

H = 3600
T0 = 1_577_836_800                  # 2020-01-01 00:00 UTC
ROOT = Path(__file__).resolve().parents[1]


def frow(ts, rate, jitter_ms=0):
    return {"symbol": "X", "fundingTime": ts * 1000 + jitter_ms, "fundingRate": str(rate)}


class TestSettlements(unittest.TestCase):
    def test_only_8_hour_settlements_with_the_previous_rate(self):
        rows = [frow(T0 - 8 * H, 0.0001), frow(T0, 0.0002, 7), frow(T0 + 8 * H, 0.0003, -4),
                frow(T0 + 12 * H, 0.0004), frow(T0 + 20 * H, 0.0005), frow(T0 + 28 * H, 0.0006)]
        s = st.settlements(rows)
        self.assertEqual(list(s["ts"]), [T0, T0 + 8 * H, T0 + 20 * H, T0 + 28 * H])     # +12h came 4h after
        self.assertEqual(list(s["prev"]), [0.0001, 0.0002, 0.0004, 0.0005])
        self.assertEqual(list(s["placebo_ok"]), [True, False, True, False])             # +4h must be empty


def bars(ts_open, opens, closes):
    return pd.DataFrame({"open": opens, "close": closes}, index=pd.Index(ts_open, name="ts"))


class TestHourly(unittest.TestCase):
    def test_milliseconds_and_microseconds_agree(self):
        k = pd.DataFrame({"open_time": [T0 * 1000, (T0 + H) * 1000], "open": [1.0, 2.0], "close": [2.0, 3.0]})
        micro = k.assign(open_time=k["open_time"] * 1000)
        pd.testing.assert_frame_equal(st.hourly(k), st.hourly(micro))
        self.assertEqual(list(st.hourly(k).index), [T0, T0 + H])


class TestEvents(unittest.TestCase):
    def setUp(self):
        t = np.arange(T0 - 3 * H, T0 + 7 * H, H)
        o = np.full(len(t), 100.0)
        c = np.full(len(t), 100.0)
        at = {int(x): i for i, x in enumerate(t)}
        c[at[T0 - H]] = 99.0                      # the hour before: down 1%
        o[at[T0]], c[at[T0]] = 99.0, 100.0        # the hour after: back up
        c[at[T0 + 3 * H]] = 101.0                 # placebo hours
        o[at[T0 + 4 * H]], c[at[T0 + 4 * H]] = 101.0, 102.0
        self.perp = bars(t, o, c)
        self.setl = pd.DataFrame({"ts": [T0], "rate": [0.0002], "prev": [0.0006], "placebo_ok": [True]})

    def test_the_four_windows(self):
        e = st.events(self.setl, self.perp, None, T0, T0).iloc[0]
        self.assertAlmostEqual(e["pre"], np.log(0.99))
        self.assertAlmostEqual(e["post"], np.log(100 / 99))
        self.assertAlmostEqual(e["pre_p"], np.log(1.01))
        self.assertAlmostEqual(e["post_p"], np.log(102 / 101))
        self.assertAlmostEqual(e["pre2"], np.log(99 / 100))           # open T-2h .. close T-1h
        self.assertEqual((e["f_prev"], e["f_now"], e["day"]), (0.0006, 0.0002, "2020-01-01"))
        self.assertTrue(np.isnan(e["spot_pre"]))

    def test_no_placebo_when_something_settles_at_plus_4h_and_missing_bars_stay_empty(self):
        e = st.events(self.setl.assign(placebo_ok=False), self.perp.drop(index=[T0]), None, T0, T0).iloc[0]
        self.assertTrue(np.isnan(e["pre_p"]) and np.isnan(e["post_p"]))
        self.assertTrue(np.isnan(e["post"]))
        self.assertFalse(np.isnan(e["pre"]))


class TestExcess(unittest.TestCase):
    def frame(self, n_base=3):
        rows = [{"ts": T0, "day": "2020-01-01", "f_prev": 0.0001, "pre": 0.001 * k, "post": 0.002 * k,
                 "pre_p": 0.0, "post_p": 0.001} for k in range(1, n_base + 1)]
        rows.append({"ts": T0, "day": "2020-01-01", "f_prev": -0.0008, "pre": 0.01, "post": -0.004,
                     "pre_p": 0.002, "post_p": 0.0})
        rows.append({"ts": T0, "day": "2020-01-01", "f_prev": 0.0003, "pre": 9.0, "post": 9.0,  # neither group
                     "pre_p": 9.0, "post_p": 9.0})
        return pd.DataFrame(rows)

    def test_against_the_same_hours_baseline_coins(self):
        x = st.excess(self.frame())
        self.assertEqual(len(x), 1)
        e = x.iloc[0]
        b_pre, b_post = 0.002, 0.004                                   # baseline means
        self.assertAlmostEqual(e["e_pre"], -1 * (0.01 - b_pre))         # shorts paid: d = -1
        self.assertAlmostEqual(e["e_post"], -1 * (-0.004 - b_post))
        self.assertAlmostEqual(e["e"], e["e_post"] - e["e_pre"])
        self.assertAlmostEqual(e["ep"], -1 * ((0.0 - 0.002) - (0.001 - 0.0)))
        self.assertAlmostEqual(e["g"], e["e"] - e["ep"])

    def test_fewer_than_three_baseline_coins_is_no_comparison(self):
        e = st.excess(self.frame(n_base=2)).iloc[0]
        self.assertTrue(np.isnan(e["e"]) and np.isnan(e["g"]))

    def test_groups(self):
        g = st.group(pd.Series([0.0005, -0.0005, 0.000125, -0.0001, 0.0003]))
        self.assertEqual(list(g), ["high", "high", "base", "base", ""])


def synthetic(days=40, swing=0.002, leg=0.0025, first_half_only=False, shape=(-1, 1), placebo=0.0,
              legs=("a", "b")):
    """Per day: 4 baseline coins flat; 2 high coins (longs pay, shorts pay) that move
    `shape` x `swing` / 2 before and after against the baseline, `placebo` at +4h."""
    rows = []
    rng = np.random.default_rng(1)
    for k in range(days):
        day = pd.Timestamp("2020-01-01") + pd.Timedelta(days=k * (2400 // days))
        late = day >= pd.Timestamp(st.SPLIT)
        ts = int(day.timestamp())
        for i in range(4):
            rows.append({"ts": ts, "day": day.strftime("%Y-%m-%d"), "f_prev": 0.0001, "pre": 0.0, "post": 0.0,
                         "pre_p": 0.0, "post_p": 0.0, "spot_pre": 0.0, "spot_post": 0.0})
        on = -0.5 if (first_half_only and late) else 1.0     # the second half reverses
        for d in (1, -1):
            n = rng.normal(0, swing / 10, 3)
            paid = np.log1p(leg + n[2])                        # a leg's return varies from day to day
            rows.append({"ts": ts, "day": day.strftime("%Y-%m-%d"), "f_prev": 0.0008 * d,
                         "pre": d * shape[0] * on * swing / 2 + n[0], "post": d * shape[1] * on * swing / 2 + n[1],
                         "pre_p": 0.0, "post_p": d * placebo,
                         "spot_post": paid if d > 0 and "a" in legs else 0.0,
                         "spot_pre": paid if d < 0 and "b" in legs else 0.0})
    return pd.DataFrame(rows)


class TestCriteria(unittest.TestCase):
    def test_a_dip_and_rebound_that_pays_passes(self):
        rows = st.criteria(synthetic())
        self.assertEqual([r["met"] for r in rows], [True, True, True, True])
        self.assertEqual(st.verdict(rows), "PASS")

    def test_too_small_to_trade(self):
        rows = st.criteria(synthetic(leg=0.0005))
        self.assertEqual([r["met"] for r in rows], [True, True, True, False])
        self.assertEqual(st.verdict(rows), "real, not tradable after costs")

    def test_the_wrong_shape(self):
        rows = st.criteria(synthetic(shape=(0.5, 1.5)))           # up before and more after: no dip
        self.assertTrue(rows[0]["met"])
        self.assertFalse(rows[1]["met"])

    def test_leg_b_alone_buys_the_hour_before(self):
        rows = st.criteria(synthetic(legs=("b",)))
        self.assertRegex(rows[3]["actual"], r"b: buy into the short cover \+2\d\.\d bps")
        self.assertTrue(rows[3]["met"])

    def test_a_positive_but_noisy_g_is_not_enough(self):
        ev = synthetic()
        days = sorted(ev["day"].unique())
        for k, day in enumerate(days):                        # alternate a big dip-and-rebound with its reverse
            hi = (ev["day"] == day) & (ev["f_prev"].abs() >= st.HIGH)
            ev.loc[hi, ["pre", "post"]] *= 1.0 if k % 2 else -0.9
        rows = st.criteria(ev)
        self.assertIn("t 0.", rows[0]["actual"])
        self.assertFalse(rows[0]["met"])

    def test_one_era_only(self):
        self.assertFalse(st.criteria(synthetic(first_half_only=True))[2]["met"])

    def test_a_placebo_as_big_as_the_settlement_is_nothing(self):
        rows = st.criteria(synthetic(placebo=0.002))
        self.assertFalse(rows[0]["met"])


def load_research():
    spec = importlib.util.spec_from_file_location("research_settle", ROOT / "research" / "settle.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestDownloads(unittest.TestCase):
    def setUp(self):
        self.r = load_research()

    def test_window_and_months(self):
        self.assertEqual((self.r.MONTHS[0], self.r.MONTHS[-1], len(self.r.MONTHS)), ("2019-12", "2026-09", 82))
        self.assertEqual(pd.Timestamp(self.r.END, unit="s").strftime("%Y-%m-%d %H:%M"), "2026-09-30 16:00")

    def test_an_invalid_symbol_is_no_market_and_other_400s_stop(self):
        def raise_(body):
            return mock.patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError(
                "u", 400, "Bad Request", {}, io.BytesIO(body)))
        with raise_(b'{"code": -1121, "msg": "Invalid symbol."}'):
            self.assertIsNone(self.r.get("https://example.test/a"))
        with raise_(b'{"code": -1100}'), mock.patch("time.sleep"), self.assertRaises(urllib.error.HTTPError):
            self.r.get("https://example.test/a")

    def test_funding_pages_forward_and_is_cached(self):
        start_ms = (self.r.START - 86400) * 1000
        pages = {start_ms: [{"fundingTime": start_ms + i * 8 * H * 1000, "fundingRate": "0.0001"} for i in range(1000)]}
        nxt = pages[start_ms][-1]["fundingTime"] + 1
        pages[nxt] = [{"fundingTime": nxt + 8 * H * 1000 - 1, "fundingRate": "0.0002"}]
        calls = []

        def fake_get(url):
            calls.append(url)
            start = int(url.split("startTime=")[1].split("&")[0])
            return json.dumps(pages.get(start, [])).encode()
        with tempfile.TemporaryDirectory() as d, mock.patch.object(self.r, "CACHE", Path(d)), \
                mock.patch.object(self.r, "get", side_effect=fake_get), mock.patch("time.sleep"):
            rows = self.r.funding("XUSDT")
            again = self.r.funding("XUSDT")
        self.assertEqual(len(rows), 1001)
        self.assertEqual(rows, again)
        self.assertEqual(len(calls), 2)                               # the second read came from the cache

    def test_a_missing_month_is_remembered(self):
        csv = "1577836800000,1,2,0.5,1.5,10,1577840399999,15,3,4,6,0\n"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("x.csv", csv)
        blobs = {m: (buf.getvalue() if m == "2020-01" else None) for m in self.r.MONTHS}
        calls = []

        def fake_get(url):
            month = url.rsplit("-1h-", 1)[1][:7]
            calls.append(month)
            return blobs[month]
        with tempfile.TemporaryDirectory() as d, mock.patch.object(self.r, "CACHE", Path(d)), \
                mock.patch.object(self.r, "get", side_effect=fake_get):
            bars_, missing = self.r.klines("perp", "XUSDT")
            again, missing2 = self.r.klines("perp", "XUSDT")
        self.assertEqual((len(bars_), missing, missing2), (1, 81, 81))
        self.assertEqual(len(calls), 82)                              # nothing fetched twice
        pd.testing.assert_frame_equal(bars_, again)


if __name__ == "__main__":
    unittest.main(verbosity=2)
