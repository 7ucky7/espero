"""Weekly cross-sectional account: picks, costs, and no negative cash."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from espero import venues, xs


class TestSignals(unittest.TestCase):
    def test_targets_pick_the_top_n(self):
        sig = {"A": 0.5, "B": 0.2, "C": -0.1, "D": 0.9, "E": 0.0}
        w = xs.targets(sig, top=2)
        self.assertEqual(w["D"], 0.5)
        self.assertEqual(w["A"], 0.5)
        self.assertEqual(w["B"], 0.0)

    def test_empty_signal_means_no_positions(self):
        self.assertEqual(xs.targets({}, top=5), {})

    def test_rebalance_day_is_monday(self):
        self.assertTrue(xs.is_rebalance_day(datetime(2026, 11, 2, tzinfo=timezone.utc)))   # Monday
        self.assertFalse(xs.is_rebalance_day(datetime(2026, 11, 3, tzinfo=timezone.utc)))  # Tuesday


class TestAccount(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "xs.db"

    def tearDown(self):
        self.tmp.cleanup()

    def test_cash_never_goes_negative(self):
        acc = xs.XSAccount(self.path)
        acc.cash = 600.0
        px = pd.Series({"A": 10.0, "B": 20.0})
        acc.rebalance(px, {"A": 0.5, "B": 0.5})
        self.assertGreaterEqual(acc.cash, -1e-9)
        self.assertAlmostEqual(acc.equity(px), 600.0 * (1 - xs.COST), places=6)

    def test_rebalance_costs_the_fee(self):
        acc = xs.XSAccount(self.path)
        acc.cash = 600.0
        px = pd.Series({"A": 10.0})
        acc.rebalance(px, {"A": 1.0})
        self.assertAlmostEqual(acc.equity(px), 600.0 * (1 - xs.COST), places=6)

    def test_state_survives_restart(self):
        acc = xs.XSAccount(self.path)
        acc.cash = 600.0
        acc.rebalance(pd.Series({"A": 10.0}), {"A": 1.0})
        acc.save(1_700_000_000, acc.equity(pd.Series({"A": 10.0})),
                 {"A": 1.0}, {"A": 0.05}, {"A": 599.4}, 600.0, "init")
        again = xs.XSAccount(self.path)
        self.assertAlmostEqual(again.cash, acc.cash)
        self.assertIn("A", again.units)


def fake_fetch(coins, days=400, stale=(), failing=(), end="2026-10-26"):
    """A stand-in for data.yahoo_daily: a rising series per coin, optionally
    stale (ends 5 days early) or raising."""
    def fetch(symbol, span):
        c = symbol.replace("-USD", "")
        if c in failing:
            raise OSError("503")
        if c not in coins:
            raise KeyError(symbol)
        idx = pd.date_range(end=end, periods=days, freq="D", tz="UTC")
        if c in stale:
            idx = idx[:-5]
        n = len(idx)
        base = 100 + (hash(c) % 50)
        close = [base * (1 + 0.001 * i + 0.0001 * (hash(c) % 7) * i) for i in range(n)]
        return pd.DataFrame({"dt": idx, "ts": idx.astype("int64") // 10**9,
                             "open": close, "high": close, "low": close, "close": close,
                             "volume": 1.0})
    return fetch


class TestDataIntegrity(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "xs.db"
        self.monday = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)

    def tearDown(self):
        self.tmp.cleanup()

    def test_load_prices_reports_failures_instead_of_hiding_them(self):
        prices, errors = xs.load_prices(fetch=fake_fetch(xs.UNIVERSE, failing=("BTC", "ETH")))
        self.assertNotIn("BTC", prices)
        self.assertIn("BTC", errors)
        self.assertIn("503", errors["BTC"])

    def test_stale_coin_is_not_ranked(self):
        prices, _ = xs.load_prices(fetch=fake_fetch(xs.UNIVERSE, stale=("DOGE",)))
        fresh, stale = xs.split_stale(prices)
        self.assertIn("DOGE", stale)
        self.assertNotIn("DOGE", fresh)
        self.assertEqual(len(fresh), len(xs.UNIVERSE) - 1)

    def test_degraded_universe_marks_but_refuses_to_rebalance(self):
        half = xs.UNIVERSE[: xs.MIN_UNIVERSE - 1]
        res = xs.run(str(self.path), 100.0, now=self.monday, fetch=fake_fetch(half))
        self.assertTrue(res["degraded"])
        self.assertEqual(res["traded"], 0.0)
        self.assertEqual(res["account"].units, {})
        self.assertAlmostEqual(res["equity"], 100.0)
        self.assertIn("degraded", res["note"])

    def test_healthy_universe_invests_on_first_run(self):
        res = xs.run(str(self.path), 100.0, now=self.monday, fetch=fake_fetch(xs.UNIVERSE))
        self.assertFalse(res["degraded"])
        self.assertEqual(sum(1 for w in res["weights"].values() if w > 0), xs.TOP)
        self.assertGreater(res["traded"], 0)

    def test_held_coin_that_stops_reporting_keeps_its_last_price(self):
        xs.run(str(self.path), 100.0, now=self.monday, fetch=fake_fetch(xs.UNIVERSE))
        acc = xs.XSAccount(self.path)
        held = next(c for c, u in acc.units.items() if u > 0)
        before = acc.equity(pd.Series(acc.last_px))
        # the next day the held coin is missing entirely from the feed
        others = [c for c in xs.UNIVERSE if c != held]
        res = xs.run(str(self.path), 100.0, now=self.monday.replace(day=3),
                     fetch=fake_fetch(others, end="2026-10-27"))
        self.assertIn(held, res["positions"])
        self.assertGreater(res["positions"][held], 0)
        self.assertGreater(res["equity"], 0.5 * before)


class TestVenues(unittest.TestCase):
    def test_binanceus_is_cheapest_for_crypto(self):
        self.assertEqual(venues.cheapest_for([], "crypto"), "binanceus")

    def test_alpaca_is_the_equity_venue(self):
        self.assertEqual(venues.cheapest_for([], "equity"), "alpaca")

    def test_round_trip_is_two_sides(self):
        self.assertAlmostEqual(venues.round_trip_bps("binanceus"), 4.0)
        self.assertAlmostEqual(venues.round_trip_bps("coinbase"), 240.0)

    def test_symbol_conventions(self):
        self.assertEqual(venues.symbol("coinbase", "btc"), "BTC-USD")
        self.assertEqual(venues.symbol("binanceus", "btc"), "BTCUSD")


if __name__ == "__main__":
    unittest.main(verbosity=2)
