"""Hypothesis #15's rule and book (espero/trend.py) and its simulator (research/trend.py)."""
from __future__ import annotations

import importlib.util
import math
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from espero import trend

ROOT = Path(__file__).resolve().parents[1]
MON = pd.Timestamp("2026-03-02")           # a Monday in winter (EST)
SUMMER_MON = pd.Timestamp("2026-07-06")    # a Monday in summer (EDT)


def research_trend():
    spec = importlib.util.spec_from_file_location("research_trend", ROOT / "research" / "trend.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod              # its dataclasses look themselves up there
    spec.loader.exec_module(mod)
    return mod


def bars(dates, close, adj=None, open_=None, volume=1e9) -> pd.DataFrame:
    close = np.asarray(close, dtype=float)
    return pd.DataFrame({
        "ts": [d.timestamp() for d in dates],
        "open": close if open_ is None else np.asarray(open_, dtype=float),
        "high": close, "low": close, "close": close,
        "adj_close": close if adj is None else np.asarray(adj, dtype=float),
        "volume": volume,
    }, index=pd.DatetimeIndex(dates))


def path(n, drift=0.001, wiggle=0.004, seed=None):
    """Prices with a steady drift and an alternating wiggle: a known, non-zero vol."""
    i = np.arange(n)
    noise = wiggle * (-1.0) ** i if seed is None else np.random.default_rng(seed).normal(0, wiggle, n)
    return 100 * np.exp(drift * i + noise)


def etf(start="2024-01-01", end="2026-12-31", volume=1e9, **kw):
    dates = pd.bdate_range(start, end)
    return bars(dates, path(len(dates), **kw), volume=volume)


def coin(start="2024-01-01", end="2026-12-31", volume=1e9, **kw):
    dates = pd.date_range(start, end, freq="D")
    return bars(dates, path(len(dates), **kw), volume=volume)


class TestCalendar(unittest.TestCase):
    def test_complete_reads_only_bars_dated_before_the_cutoff(self):
        df = coin()
        self.assertEqual(trend.complete(df, MON).index[-1], MON - pd.Timedelta(days=1))
        self.assertEqual(trend.complete(df, MON + pd.Timedelta(hours=11)).index[-1],
                         MON - pd.Timedelta(days=1))

    def test_fresh(self):
        c = trend.complete(coin(), MON)
        self.assertTrue(trend.fresh(c, MON, "crypto"))
        self.assertFalse(trend.fresh(c.drop(MON - pd.Timedelta(days=1)), MON, "crypto"))   # Sunday dropped
        e = trend.complete(etf(), MON)
        good_friday = e.drop(MON - pd.Timedelta(days=3))                                   # Thursday is last
        self.assertTrue(trend.fresh(good_friday, MON, "etf"))
        self.assertFalse(trend.fresh(e[e.index <= MON - pd.Timedelta(days=6)], MON, "etf"))

    def test_run_and_open_follow_new_york_daylight_saving(self):
        self.assertEqual(trend.run_moment(MON), MON + pd.Timedelta(hours=12, minutes=30))
        self.assertEqual(trend.run_moment(SUMMER_MON), SUMMER_MON + pd.Timedelta(hours=11, minutes=30))
        self.assertEqual(trend.fill_moment(MON, "etf"), MON + pd.Timedelta(hours=14, minutes=30))
        self.assertEqual(trend.fill_moment(SUMMER_MON, "etf"), SUMMER_MON + pd.Timedelta(hours=13, minutes=30))
        self.assertEqual(trend.fill_moment(MON, "crypto"), MON + pd.Timedelta(days=1))

    def test_fill_bars(self):
        e, c = etf(), coin()
        run = trend.run_moment(MON)
        self.assertEqual(trend.fill_bar(e, "etf", run), MON)                          # Monday's open
        self.assertEqual(trend.fill_bar(e.drop(MON), "etf", run), MON + pd.Timedelta(days=1))   # holiday
        late = MON + pd.Timedelta(hours=16)                                           # after the open
        self.assertEqual(trend.fill_bar(e, "etf", late), MON + pd.Timedelta(days=1))
        self.assertEqual(trend.fill_bar(c, "crypto", run), MON)                       # Monday's close
        self.assertEqual(trend.fill_bar(c, "crypto", late), MON)
        self.assertIsNone(trend.fill_bar(trend.complete(c, MON + pd.Timedelta(days=1)).iloc[:-1], "crypto", run))


class TestSignal(unittest.TestCase):
    def test_lookbacks_are_calendar_days_not_rows(self):
        daily = coin()
        weekdays = daily[daily.index.weekday < 5]          # same prices, an ETF's calendar
        asof = pd.Timestamp("2026-03-07")                  # Saturday: both end on Friday
        f1, r1 = trend.fraction(trend.complete(daily, asof)["adj_close"])
        f2, r2 = trend.fraction(trend.complete(weekdays, asof)["adj_close"])
        self.assertEqual((f1, r1), (f2, r2))               # 28/91/364 land on the same Friday

    def test_fraction_counts_rising_lookbacks(self):
        px = pd.Series([100.0] * 400, index=pd.date_range("2025-01-01", periods=400))
        px.iloc[-1] = 101.0
        self.assertEqual(trend.fraction(px)[0], 1.0)
        px.iloc[-29:-1] = 102.0                             # above the last close for the last 4 weeks
        self.assertAlmostEqual(trend.fraction(px)[0], 2 / 3)
        self.assertEqual(trend.fraction(px.iloc[-300:]), (None, {}))

    def test_vol_is_annualised_by_each_series_own_calendar(self):
        for cal, n in ((pd.bdate_range("2025-01-01", "2026-03-06"), 260),
                       (pd.date_range("2025-01-01", "2026-03-06"), 364)):
            a = 0.20 / math.sqrt(n)
            px = pd.Series(100 * np.exp(a * (np.arange(len(cal)) % 2)), index=cal)
            self.assertAlmostEqual(trend.ann_vol(px), 0.20, delta=0.01)

    def test_vol_of_a_series_with_a_zero_print_is_none_not_nan(self):
        px = pd.Series(100 * np.exp(0.01 * (np.arange(80) % 2)), index=pd.date_range("2026-01-01", periods=80))
        px.iloc[-5] = 0.0                                   # Yahoo rounds SHIB's 2020 prices to 0
        self.assertIsNone(trend.ann_vol(px))

    def test_vol_needs_twenty_returns(self):
        px = pd.Series(100 + np.arange(15.0), index=pd.date_range("2026-01-01", periods=15))
        self.assertIsNone(trend.ann_vol(px))

    def test_alt_liquidity_is_eights_rule(self):
        c = trend.complete(coin(volume=1e5), MON)                 # close ~100+ x 1e5 > $1M
        self.assertTrue(trend.alt_liquid(c))
        self.assertFalse(trend.alt_liquid(c.iloc[-364:]))         # fewer than 365 closes
        self.assertFalse(trend.alt_liquid(c.drop(c.index[-10])))  # a missing day in the last 30
        self.assertFalse(trend.alt_liquid(trend.complete(coin(volume=10.0), MON)))


class TestDecide(unittest.TestCase):
    CLASSES = {"equity": ("SPY", "QQQ"), "crypto": ("BTC-USD", trend.ALTS)}

    def frames(self, **override):
        f = {"SPY": etf(), "QQQ": etf(wiggle=0.008), "BTC-USD": coin(wiggle=0.02),
             "ADA-USD": coin(wiggle=0.03), "XRP-USD": coin(wiggle=0.03)}
        f.update(override)
        return f

    def test_budgets_split_by_class_then_member_then_alt(self):
        d = trend.decide(self.frames(), MON, classes=self.CLASSES)
        budgets = {s: v.budget for s, v in d.views.items() if v.eligible}
        self.assertEqual(budgets, {"SPY": 0.25, "QQQ": 0.25, "BTC-USD": 0.25, "ADA-USD": 0.125, "XRP-USD": 0.125})
        self.assertLessEqual(d.gross, 1.0)
        for s, w in d.targets.items():
            v = d.views[s]
            self.assertAlmostEqual(w, v.f * v.budget * min(0.20 / v.vol, 2.0))
        self.assertEqual(d.views["SOL-USD" if "SOL-USD" in d.views else "BNB-USD"].why, "no data")

    def test_falling_member_keeps_its_share_in_cash(self):
        falling = etf(drift=-0.001)
        d = trend.decide(self.frames(QQQ=falling), MON, classes=self.CLASSES)
        base = trend.decide(self.frames(), MON, classes=self.CLASSES)
        self.assertEqual(d.targets["QQQ"], 0.0)
        self.assertAlmostEqual(d.targets["SPY"], base.targets["SPY"])

    def test_scale_cap_and_gross_cap(self):
        calm = {s: etf(wiggle=0.0001) for s in ("SPY", "QQQ")}
        d = trend.decide(calm, MON, classes={"equity": ("SPY", "QQQ")})
        self.assertAlmostEqual(d.gross, 1.0)                     # 2 x 0.5 x 2.0 = 2.0, scaled to 1
        self.assertAlmostEqual(d.targets["SPY"], 0.5)

    def test_class_without_members_holds_cash(self):
        d = trend.decide({"SPY": etf()}, MON, classes=self.CLASSES)
        self.assertEqual(set(d.targets), {"SPY"})
        self.assertEqual(d.views["SPY"].budget, 0.5)          # crypto's half is not handed over

    def test_modes(self):
        f = self.frames(QQQ=etf(drift=-0.001))
        vol = trend.decide(f, MON, "volonly", classes=self.CLASSES)
        static = trend.decide(f, MON, "static", classes=self.CLASSES)
        self.assertGreater(vol.targets["QQQ"], 0.0)              # f = 1 whatever the trend
        self.assertEqual(static.targets, {s: v.budget for s, v in static.views.items() if v.eligible})
        sixty = trend.decide(f, MON, "6040")
        self.assertEqual(sixty.targets, {"SPY": 0.6})            # no TLT in these frames
        self.assertEqual(sixty.stale, ["TLT"])

    def test_decision_reads_only_complete_bars(self):
        full = self.frames()
        cut = {s: trend.complete(df, MON) for s, df in full.items()}
        a = trend.decide(full, MON, classes=self.CLASSES)
        b = trend.decide(cut, MON, classes=self.CLASSES)
        self.assertEqual(a.targets, b.targets)

    def test_stale_assets_are_not_eligible_and_not_traded(self):
        no_sunday = coin().drop(MON - pd.Timedelta(days=1))
        d = trend.decide(self.frames(**{"BTC-USD": no_sunday}), MON, classes=self.CLASSES)
        self.assertIn("BTC-USD", d.stale)
        self.assertNotIn("BTC-USD", d.targets)
        book = trend.Book(cash=0.0, values={"BTC-USD": 100.0}, marks={"BTC-USD": 1.0})
        orders = book.rebalance(d, self.frames(), trend.run_moment(MON))
        self.assertNotIn("BTC-USD", [o.symbol for o in orders])


class TestBook(unittest.TestCase):
    def setUp(self):
        self.f = {"SPY": etf(), "BTC-USD": coin(wiggle=0.02)}

    def decision(self, targets):
        return trend.Decision(MON, "trend", {}, targets, [], sum(targets.values()))

    def test_etf_fills_at_the_open_and_crypto_at_mondays_close(self):
        book = trend.Book(cash=100.0)
        book.mark(self.f, MON)
        book.rebalance(self.decision({"SPY": 0.5, "BTC-USD": 0.2}), self.f, trend.run_moment(MON))
        self.assertEqual(book.fill(self.f, MON + pd.Timedelta(hours=20)), [])   # nothing has closed yet
        fills = {x.symbol: x for x in book.fill(self.f, MON + pd.Timedelta(days=1))}
        self.assertEqual({s: x.date for s, x in fills.items()}, {"SPY": MON, "BTC-USD": MON})
        spy_open = trend.adj_open(self.f["SPY"], MON)
        spy_dec = trend.last_adj(self.f["SPY"], MON)
        self.assertAlmostEqual(fills["SPY"].amount, 50.0 * spy_open / spy_dec)
        self.assertAlmostEqual(book.values["BTC-USD"], 20.0 * self.f["BTC-USD"]["adj_close"].loc[MON]
                               / trend.last_adj(self.f["BTC-USD"], MON))
        self.assertFalse(any(x.late for x in fills.values()))

    def test_late_run_fills_the_next_session_and_is_counted(self):
        book = trend.Book(cash=100.0)
        book.rebalance(self.decision({"SPY": 0.5}), self.f, MON + pd.Timedelta(hours=16))
        fills = book.fill(self.f, MON + pd.Timedelta(days=2))
        self.assertEqual((fills[0].date, fills[0].late, book.late), (MON + pd.Timedelta(days=1), True, 1))

    def test_cash_never_goes_negative_when_crypto_sales_fund_etf_buys(self):
        book = trend.Book(cash=20.0, values={"BTC-USD": 100.0},
                          marks={"BTC-USD": trend.last_adj(self.f["BTC-USD"], MON)})
        book.rebalance(self.decision({"SPY": 0.5, "BTC-USD": 0.0}), self.f, trend.run_moment(MON))
        book.fill(self.f, MON + pd.Timedelta(days=1))
        self.assertGreaterEqual(book.cash, -1e-12)
        self.assertAlmostEqual(book.values["SPY"], 20.0 / (1 + trend.COSTS["etf"]))   # scaled to the cash
        self.assertNotIn("BTC-USD", book.values)                                     # the exit sold it all

    def test_dividends_accrue_through_adjusted_marks(self):
        dates = pd.bdate_range("2026-02-02", "2026-03-06")
        raw = np.full(len(dates), 100.0)
        raw[dates >= "2026-02-20"] = 99.0                     # $1 dividend, ex on the 20th
        adj = np.full(len(dates), 99.0)                        # history scaled by 0.99: no drop at all
        frames = {"TLT": bars(dates, raw, adj=adj)}
        book = trend.Book(cash=0.0, values={"TLT": 100.0})
        book.mark(frames, pd.Timestamp("2026-02-14"))         # before the ex-date
        book.mark(frames, pd.Timestamp("2026-03-07"))         # after it
        self.assertAlmostEqual(book.values["TLT"], 100.0)     # a price-only mark would show -1%

    def test_signal_reads_adjusted_closes(self):
        dates = pd.bdate_range("2025-01-01", "2026-02-27")
        raw = np.full(len(dates), 100.0)
        raw[-1] = 99.5                                        # $1 paid out on the last day
        adj = np.full(len(dates), 99.0)
        adj[-1] = 99.5                                        # with the payout it is up 0.5%
        noisy = bars(dates, raw * np.exp(1e-4 * (-1.0) ** np.arange(len(dates))),
                     adj=adj * np.exp(1e-4 * (-1.0) ** np.arange(len(dates))))
        d = trend.decide({"TLT": noisy}, MON, classes={"bonds": ("TLT",)})
        self.assertEqual(d.views["TLT"].f, 1.0)               # on raw closes it would be 0

    def test_band_skips_small_moves_but_not_entries_or_exits(self):
        book = trend.Book(cash=50.0, values={"SPY": 50.0}, marks={"SPY": trend.last_adj(self.f["SPY"], MON)})
        self.assertEqual(book.rebalance(self.decision({"SPY": 0.505}), self.f, trend.run_moment(MON)), [])
        self.assertEqual(len(book.rebalance(self.decision({"SPY": 0.52}), self.f, trend.run_moment(MON))), 1)
        orders = book.rebalance(self.decision({"SPY": 0.0, "BTC-USD": 0.001}), self.f, trend.run_moment(MON))
        self.assertEqual({(o.symbol, o.exit) for o in orders}, {("SPY", True), ("BTC-USD", False)})


class TestFlipLevels(unittest.TestCase):
    def test_flip_level_is_on_todays_raw_scale_across_a_dividend(self):
        dates = pd.bdate_range("2025-01-01", "2026-03-06")
        raw = np.full(len(dates), 100.0)
        raw[dates >= "2026-02-20"] = 98.0                     # $2 paid out, ex on the 20th
        adj = raw.copy()
        adj[dates < "2026-02-20"] = 100.0 * 0.98              # Yahoo scales the history down
        levels = trend.flip_levels(bars(dates, raw, adj=adj), pd.Timestamp("2026-03-07"), MON + pd.Timedelta(days=7),
                                   "etf")
        self.assertAlmostEqual(levels[364], 98.0)             # 100 before the dividend is 98 today
        self.assertAlmostEqual(levels[28], 98.0)


class TestSimulator(unittest.TestCase):
    def setUp(self):
        self.r = research_trend()
        up = {"SPY": etf(start="2024-01-01", end="2026-06-30", wiggle=0.002),
              "TLT": etf(start="2024-01-01", end="2026-06-30", wiggle=0.004, drift=0.0005),
              "BTC-USD": coin(start="2024-01-01", end="2026-06-30", wiggle=0.01, drift=0.002)}
        self.up = up
        self.classes = {"equity": ("SPY",), "bonds": ("TLT",), "crypto": ("BTC-USD",)}

    def test_trend_equals_volonly_when_every_lookback_is_up(self):
        kw = dict(start="2025-06-02", end="2026-03-02", classes=self.classes)
        tr = self.r.simulate(self.up, **kw)
        vo = self.r.simulate(self.up, mode="volonly", **kw)
        self.assertGreaterEqual(tr.book.trades, 3)
        np.testing.assert_allclose(tr.equity.to_numpy(), vo.equity.to_numpy(), rtol=1e-12)

    def test_falling_market_trend_stays_flat_and_volonly_does_not(self):
        down = {s: bars(df.index, df["close"].to_numpy()[::-1]) for s, df in self.up.items()}
        kw = dict(start="2025-06-02", end="2026-03-02", classes=self.classes)
        tr = self.r.simulate(down, **kw)
        vo = self.r.simulate(down, mode="volonly", **kw)
        self.assertEqual(tr.book.trades, 0)
        self.assertLess(vo.equity.iloc[-1], 1.0)
        self.assertEqual(tr.equity.iloc[-1], 1.0)

    def test_metrics(self):
        eq = pd.Series([1.0, 1.1, 0.99, 1.2], index=pd.date_range("2026-01-05", periods=4, freq="7D"))
        self.assertAlmostEqual(self.r.maxdd(eq), 0.99 / 1.1 - 1)
        self.assertEqual(len(self.r.weekly(eq)), 3)


if __name__ == "__main__":
    unittest.main()
