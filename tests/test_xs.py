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


COIN = {sym: c for c, sym in xs.YAHOO.items()}


def fake_fetch(coins, days=400, stale=(), failing=(), end="2026-10-26", dead=(), price=None, asked=None):
    """A stand-in for data.yahoo_daily: a rising series per coin with dollar volume, optionally
    stale (ends 5 days early), raising, dead (no volume) or at a fixed `price`."""
    def fetch(symbol, span):
        if asked is not None:
            asked.append(symbol)
        c = COIN.get(symbol, symbol.replace("-USD", ""))
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
        if price and c in price:
            close = [price[c]] * n
        return pd.DataFrame({"dt": idx, "ts": idx.astype("int64") // 10**9,
                             "open": close, "high": close, "low": close, "close": close,
                             "volume": 0.0 if c in dead else 1e6})
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


class TestWrongSeries(unittest.TestCase):
    """Yahoo's ARB-USD is "ARbit", a dead token, and the account bought it on day one."""

    THURSDAY = datetime(2026, 10, 29, 12, tzinfo=timezone.utc)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "xs.db"

    def tearDown(self):
        self.tmp.cleanup()

    def test_on_yahoo_arb_is_priced_from_arbitrum(self):
        asked = []
        xs.load_prices(fetch=fake_fetch(xs.UNIVERSE, asked=asked), source="yahoo")
        self.assertIn("ARB11841-USD", asked)
        self.assertNotIn("ARB-USD", asked)
        self.assertEqual(xs.yahoo_symbol("TIA"), "TIA-USD")

    def test_hyperliquid_is_the_default_and_its_arb_is_arbitrum(self):
        asked = []
        prices, _ = xs.load_prices(fetch=fake_fetch(xs.UNIVERSE, asked=asked))
        self.assertEqual(xs.SOURCE, "hyperliquid")
        self.assertIn("ARB-USD", asked)                 # Hyperliquid's ARB perp is Arbitrum
        self.assertIn("ARB", prices)

    def test_hyperliquid_volume_is_in_coins_so_the_guard_uses_dollars(self):
        cheap = fake_fetch(xs.UNIVERSE, price={"DOGE": 0.001})   # 1e6 coins a day x $0.001 = $7k a week
        prices, errors = xs.load_prices(fetch=cheap)
        self.assertNotIn("DOGE", prices)
        self.assertIn("dead or mis-mapped", errors["DOGE"])

    def test_a_series_nobody_trades_is_not_ranked(self):
        prices, errors = xs.load_prices(fetch=fake_fetch(xs.UNIVERSE, dead=("DOGE",)))
        self.assertNotIn("DOGE", prices)
        self.assertIn("dead or mis-mapped", errors["DOGE"])

    def held_dead_arb(self):
        """The real account's state: ARB bought at ARbit's $0.000629, next to a real coin."""
        acc = xs.XSAccount(self.path)
        acc.db.execute("DELETE FROM xs_meta")                   # an account from before the fix
        acc.cash, acc.units = 0.0, {"ARB": 10.0 / 0.000629, "BTC": 90.0 / 140.0}
        acc.save(1, 100.0, {"ARB": 0.1, "BTC": 0.9}, {"ARB": 0.0, "BTC": 0.05}, {}, 100.0, "init",
                 last_px={"ARB": 0.000629, "BTC": 140.0})
        acc.db.close()

    def test_held_dead_arb_is_closed_at_its_last_print_not_revalued(self):
        self.held_dead_arb()
        res = xs.run(str(self.path), 100.0, now=self.THURSDAY,
                     fetch=fake_fetch(xs.UNIVERSE, price={"ARB": 0.1655, "BTC": 140.0}))
        rows = res["account"].db.execute("SELECT note, equity, cash, units FROM xs_account ORDER BY id").fetchall()
        fix = [r for r in rows if r["note"].startswith("correction")]
        self.assertEqual(len(fix), 1)
        self.assertIn("ARB $10.00 at 0.000629", fix[0]["note"])
        self.assertAlmostEqual(fix[0]["equity"], 100.0)            # cash 10 + BTC 90: no jump
        self.assertAlmostEqual(res["equity"], 100.0)               # not 10 / 0.000629 x 0.1655 = $2,631
        self.assertNotIn("ARB", res["account"].units)
        self.assertEqual(res["traded"], 0.0)                       # a Thursday: no rebalance

    def test_the_correction_happens_once(self):
        self.held_dead_arb()
        fetch = fake_fetch(xs.UNIVERSE, price={"ARB": 0.1655, "BTC": 140.0})
        xs.run(str(self.path), 100.0, now=self.THURSDAY, fetch=fetch)
        res = xs.run(str(self.path), 100.0, now=self.THURSDAY, fetch=fetch)
        n = res["account"].db.execute("SELECT COUNT(*) FROM xs_account WHERE note LIKE 'correction%'").fetchone()[0]
        self.assertEqual(n, 1)

    def test_a_new_account_never_corrects_real_arbitrum(self):
        monday = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)
        fetch = fake_fetch(xs.UNIVERSE, price={"ARB": 0.1655})
        xs.run(str(self.path), 100.0, now=monday, fetch=fetch)
        acc = xs.XSAccount(self.path)
        acc.units["ARB"] = 50.0                                     # bought on the real series
        acc.last_px["ARB"] = 0.1655
        latest = acc.db.execute("SELECT MAX(ts) FROM xs_account").fetchone()[0]
        acc.save(latest + 86400, 100.0, {}, {}, {}, 0.0, "rebalance", last_px=acc.last_px)
        acc.db.close()
        res = xs.run(str(self.path), 100.0, now=self.THURSDAY, fetch=fetch)
        self.assertIn("ARB", res["account"].units)


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
