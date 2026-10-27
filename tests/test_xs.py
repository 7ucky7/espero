"""Weekly cross-sectional account: picks, costs, and no negative cash."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from espero import venues
from espero import xs


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
