"""#18's pieces: 5-minute bars from the archive, liquidations in dollars, #10's
trigger and its mirror, the hour before and after a break, and the within-day
grouping behind the four criteria."""
from __future__ import annotations

import importlib.util
import io
import unittest
import urllib.error
import zipfile
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

from espero import degen
from espero import liq as lq

DAY = 1_759_276_800                    # 2025-10-01 00:00 UTC
ROOT = Path(__file__).resolve().parents[1]


def quiet(day_start=DAY, days=3, px=100.0):
    """Flat 5-minute bars from the day before to the day after: nothing ever triggers."""
    ts = np.arange(day_start - 86400, day_start - 86400 + days * 86400, lq.BAR_S)
    return pd.DataFrame({"open": px, "high": px, "low": px, "close": px, "volume": 100.0,
                         "quote_volume": 1000.0, "taker_buy_quote": 600.0},
                        index=pd.Index(ts, name="ts")).astype(float)


def plant_up(bars, t, close=103.0, after=101.0):
    """An up-break at bar open `t`: a new high on 20x volume, then a fade to `after`."""
    b = bars.copy()
    b.loc[t, ["close", "high", "volume", "quote_volume", "taker_buy_quote"]] = [close, close + 0.5, 2000.0,
                                                                                20000.0, 12000.0]
    later = b.index > t
    b.loc[later, ["open", "high", "low", "close"]] = after
    b.loc[t + lq.BAR_S, "open"] = close - 0.2           # the next open is not the break's close
    return b


def at(hours, minutes=0, day=DAY):
    """Open time of the bar that CLOSES at the given UTC time of the test day."""
    return day + hours * 3600 + minutes * 60 - lq.BAR_S


def liq_rows(*rows):
    return pd.DataFrame(rows, columns=["ts", "side", "usd", "venue"])


class TestInputs(unittest.TestCase):
    def test_bars_5m_combines_minutes(self):
        t0 = DAY * 1000
        k = pd.DataFrame({"open_time": [t0 + 60_000 * i for i in range(10)],
                          "open": np.arange(10.0) + 1, "high": np.arange(10.0) + 5, "low": np.arange(10.0),
                          "close": np.arange(10.0) + 2, "volume": 1.0, "quote_volume": 10.0,
                          "taker_buy_quote_volume": 4.0})
        b = lq.bars_5m(k)
        self.assertEqual(list(b.index), [DAY, DAY + 300])
        self.assertEqual(list(b.iloc[0][["open", "high", "low", "close", "volume", "quote_volume",
                                         "taker_buy_quote"]]), [1.0, 9.0, 0.0, 6.0, 5.0, 50.0, 20.0])
        micro = k.assign(open_time=k["open_time"] * 1000)
        pd.testing.assert_frame_equal(lq.bars_5m(micro), b)

    def test_liquidations_are_dollars_and_named_sides(self):
        rows = pd.DataFrame({"timestamp": [1_000_000_000, 2_500_000, 3_000_000], "side": ["buy", "sell", "unknown"],
                             "price": [100.0, 50.0, 1.0], "amount": [2.0, 0.5, 9.0]})
        out = lq.liquidations(rows, "bybit")
        self.assertEqual(list(out["side"]), ["buy", "sell"])
        self.assertEqual(list(out["usd"]), [200.0, 25.0])
        self.assertEqual(list(out["ts"]), [1000.0, 2.5])
        self.assertEqual(set(out["venue"]), {"bybit"})

    def test_symbols(self):
        self.assertEqual(lq.symbol("binance-futures", "SHIB"), "1000SHIBUSDT")
        self.assertEqual(lq.symbol("bybit", "SHIB"), "SHIB1000USDT")
        self.assertEqual(lq.symbol("bybit", "ADA"), "ADAUSDT")


def walk(seed=1, n=2000):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.004, n)))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) * (1 + rng.uniform(0, 0.002, n))
    low = np.minimum(open_, close) * (1 - rng.uniform(0, 0.002, n))
    vol = rng.lognormal(4, 0.8, n)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": vol,
                         "quote_volume": vol * close, "taker_buy_quote": vol * close / 2},
                        index=pd.Index(DAY - 86400 + 300 * np.arange(n), name="ts"))


class TestTriggers(unittest.TestCase):
    def test_up_is_exactly_degens_candidate(self):
        b = walk()
        f = lq.triggers(b)
        expected = degen.features(b).apply(degen.is_candidate, axis=1)
        self.assertGreater(int(expected.sum()), 5)
        self.assertEqual(list(f["up"]), list(expected))

    def test_down_is_the_mirror_of_up(self):
        b = walk(seed=2, n=8000)
        mirror = pd.DataFrame({"open": 1 / b["open"], "high": 1 / b["low"], "low": 1 / b["high"],
                               "close": 1 / b["close"], "volume": b["volume"]}, index=b.index)
        down = lq.triggers(b)["down"]
        self.assertGreater(int(down.sum()), 5)
        self.assertEqual(list(down), list(lq.triggers(mirror)["up"]))


class TestEvents(unittest.TestCase):
    def test_measures_and_window_edges(self):
        t = at(10)
        b = plant_up(quiet(), t)
        start, close_t = t - 11 * 300, t + 300
        liq = liq_rows((start, "buy", 1000.0, "binance-futures"),      # first instant of the hour: in
                       (start - 0.001, "buy", 9e9, "bybit"),            # before it: out
                       (close_t, "buy", 9e9, "bybit"),                  # at the break's close: out
                       (t + 10, "buy", 550.0, "bybit"),                 # in, the other venue
                       (t + 20, "sell", 777.0, "bybit"))                # longs: not an up-break's forced side
        ev = lq.events(b, liq, DAY)
        self.assertEqual(len(ev), 1)
        e = ev.iloc[0]
        self.assertEqual((e["ts"], e["direction"]), (close_t, 1))
        self.assertEqual((e["forced"], e["forced_binance"], e["forced_bybit"]), (1550.0, 1000.0, 550.0))
        self.assertEqual(e["liq_total"], 1550.0 + 777.0)
        self.assertEqual(e["volume"], 11 * 1000.0 + 20000.0)
        self.assertAlmostEqual(e["s"], 1550.0 / 31000.0)
        self.assertAlmostEqual(e["s15"], 550.0 / 22000.0)               # 1000 is outside the last 15 min
        self.assertAlmostEqual(e["agree"], (2 * (11 * 600 + 12000) - 31000) / 31000)
        self.assertAlmostEqual(e["y60"], 101.0 / 102.8 - 1)             # next open to the close an hour on
        self.assertAlmostEqual(e["y15"], 101.0 / 102.8 - 1)

    def test_only_breaks_closing_from_one_am_to_midnight(self):
        for close_at, n in (((0, 55), 0), ((1, 0), 1), ((23, 55), 1), ((24, 5), 0)):
            t = at(*close_at)
            ev = lq.events(plant_up(quiet(), t), liq_rows(), DAY)
            self.assertEqual(len(ev), n, close_at)

    def test_one_event_per_coin_and_direction_per_hour(self):
        for gap, n in ((12, 1), (13, 2)):
            t1 = at(10)
            t2 = t1 + gap * 300
            b = plant_up(quiet(), t1, after=102.0)
            b = plant_up(b, t2, close=106.0, after=104.0)
            self.assertEqual(len(lq.events(b, liq_rows(), DAY)), n, gap)

    def test_a_missing_bar_leaves_the_measure_empty(self):
        t = at(10)
        b = plant_up(quiet(), t)
        ev = lq.events(b.drop(index=[t - 5 * 300]), liq_rows(), DAY)
        self.assertTrue(np.isnan(ev.iloc[0]["s"]))
        ev = lq.events(b.drop(index=[t + 12 * 300]), liq_rows(), DAY)
        self.assertTrue(np.isnan(ev.iloc[0]["y60"]))
        self.assertFalse(np.isnan(ev.iloc[0]["y15"]))


def table(days=40, per_day=12, seed=0, forced_y=-0.003, organic_y=0.003, noise=0.002):
    """Synthetic events: the top third by s returns `forced_y`, the bottom third `organic_y`."""
    rng = np.random.default_rng(seed)
    rows = []
    for k in range(days):
        day = f"{2020 + k // 12 + (2 if k >= days // 2 else 0)}-{k % 12 + 1:02d}-01"
        s = rng.permutation(per_day) / per_day
        for i in range(per_day):
            y = forced_y if s[i] >= 2 / 3 else organic_y if s[i] < 1 / 3 else 0.0
            rows.append({"day": day, "coin": f"C{i}", "direction": 1 if i % 2 else -1, "s": s[i],
                         "y60": y + rng.normal(0, noise)})
    return pd.DataFrame(rows)


class TestGrouping(unittest.TestCase):
    def test_terciles_within_the_day_and_ties_in_the_middle(self):
        ev = pd.DataFrame({"day": ["a"] * 9 + ["b"] * 6, "s": list(range(9)) + [0.5] * 6})
        t = lq.tag(ev)
        self.assertEqual(list(t[:9]), ["organic"] * 3 + ["middle"] * 3 + ["forced"] * 3)
        self.assertEqual(set(t[9:]), {"middle"})

    def test_day_diff_sees_fading_forced_breaks_and_drops_thin_days(self):
        ev = table()
        d = lq.day_diff(ev)
        self.assertEqual(len(d), 40)
        self.assertLess(lq.clustered(d)["t"], -10)
        thin = pd.concat([ev, pd.DataFrame({"day": ["2099-01-01"] * 5, "coin": "X", "direction": 1,
                                            "s": np.arange(5.0), "y60": 0.0})])
        self.assertNotIn("2099-01-01", lq.day_diff(thin).index)

    def test_a_long_leg_earns_minus_y_on_a_down_break(self):
        ev = pd.DataFrame({"day": "a", "coin": [f"C{i}" for i in range(6)], "direction": [-1] * 6,
                           "s": np.arange(6.0), "y60": [0.0, 0.0, 0.0, 0.0, -0.02, -0.02]})
        self.assertAlmostEqual(float(lq.leg(ev, -1, "forced").iloc[0]), 0.02)

    def test_clustered_t(self):
        c = lq.clustered(pd.Series([1.0, 2.0, 3.0]))
        self.assertAlmostEqual(c["t"], 2.0 / (1.0 / np.sqrt(3)))
        self.assertEqual(c["n"], 3)


class TestCriteria(unittest.TestCase):
    def test_a_strong_tradable_effect_passes(self):
        rows = lq.criteria(table())
        self.assertEqual([r["met"] for r in rows], [True, True, True, True])
        self.assertEqual(lq.verdict(rows), "PASS")

    def test_a_small_effect_is_real_but_not_tradable(self):
        rows = lq.criteria(table(forced_y=-0.0005, organic_y=0.0005, noise=0.0003))
        self.assertEqual([r["met"] for r in rows], [True, True, True, False])
        self.assertEqual(lq.verdict(rows), "real, not tradable after costs")

    def test_an_effect_that_is_only_the_coin_mix_fails(self):
        rng = np.random.default_rng(5)
        rows = []
        for k in range(40):
            day = f"{2020 + k // 12 + (2 if k >= 20 else 0)}-{k % 12 + 1:02d}-01"
            for i in range(12):
                hi = i < 6                                   # a leveraged coin: always a high s, always fades
                s = (0.5 if hi else 0.0) + rng.uniform(0, 0.1)
                y = (-0.003 if hi else 0.003) + 0.05 * (s - (0.55 if hi else 0.05)) + rng.normal(0, 0.0002)
                rows.append({"day": day, "coin": "HI" if hi else "LO", "direction": 1, "s": s, "y60": y})
        crit = lq.criteria(pd.DataFrame(rows))
        self.assertTrue(crit[0]["met"])
        self.assertFalse(crit[1]["met"])
        self.assertEqual(lq.verdict(crit), "FAIL")

    def test_a_negative_but_noisy_d_is_not_enough(self):
        rows = []
        for k in range(40):
            day = f"{2020 + k // 12 + (2 if k >= 20 else 0)}-{k % 12 + 1:02d}-01"
            fade = -0.002 if k % 2 else 0.0018          # mean D -1 bp, t about -0.3
            for i in range(6):
                rows.append({"day": day, "coin": f"C{i}", "direction": 1, "s": float(i),
                             "y60": fade if i >= 4 else 0.0})
        crit = lq.criteria(pd.DataFrame(rows))
        self.assertIn("D -1.0 bps", crit[0]["actual"])
        self.assertFalse(crit[0]["met"])

    def test_an_effect_in_one_era_only_fails(self):
        ev = table()
        late = ev["day"] >= lq.SPLIT
        ev.loc[late, "y60"] = -ev.loc[late, "y60"]
        crit = lq.criteria(ev)
        self.assertFalse(crit[2]["met"])


def load_research():
    spec = importlib.util.spec_from_file_location("research_liq", ROOT / "research" / "liq.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestDownloads(unittest.TestCase):
    def setUp(self):
        self.r = load_research()

    def zipped(self, text):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("x.csv", text)
        return buf.getvalue()

    def test_kline_files_with_and_without_a_header(self):
        row = "1759276800000,1,2,0.5,1.5,10,1759276859999,15,3,4,6,0\n"
        with_h = self.r.read_klines(self.zipped(",".join(self.r.KLINE_COLS) + "\n" + row))
        without = self.r.read_klines(self.zipped(row))
        pd.testing.assert_frame_equal(with_h, without)
        self.assertEqual(int(without["open_time"].iloc[0]), 1759276800000)

    def test_a_404_is_no_market_and_a_401_stops_the_run(self):
        def raise_(code):
            return mock.patch("urllib.request.urlopen",
                              side_effect=urllib.error.HTTPError("u", code, "x", {}, None))
        with raise_(404):
            self.assertIsNone(self.r.get("https://example.test/a"))
        with raise_(401), self.assertRaises(urllib.error.HTTPError):
            self.r.get("https://example.test/a")

    def test_the_82_free_days(self):
        self.assertEqual(len(self.r.DAYS), 82)
        self.assertEqual((str(self.r.DAYS[0]), str(self.r.DAYS[-1])), ("2020-01-01", "2026-10-01"))
        self.assertTrue(all(d.day == 1 for d in self.r.DAYS))
        self.assertEqual(sum(1 for d in self.r.DAYS if str(d) < lq.SPLIT), 41)


if __name__ == "__main__":
    unittest.main(verbosity=2)
