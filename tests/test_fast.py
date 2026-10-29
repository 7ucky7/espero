"""The fast book proposes, never places; the human's keys do the placing;
risk halts it; the journal remembers why."""
from __future__ import annotations

import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from espero import book as bk
from espero import fast
from espero.execution import PaperExchange

HAVE_RICH = importlib.util.find_spec("rich") is not None   # the tui extra is optional


def snap(ts=0.0, bid=100.0, ask=100.1, trades=()):
    s = bk.BookSnapshot(ts, "X-USD", bids=[(bid, 1.0), (bid - 0.1, 5.0)], asks=[(ask, 1.0), (ask + 0.1, 5.0)])
    s.trades = [bk.Trade(i, ts, side, px, size) for i, (side, px, size) in enumerate(trades)]
    return s


def book(tmp, threshold=0.003, cash=1000.0, check_feed_age=False, **limits):
    # the snapshots here carry made-up timestamps, like a replay: no wall-clock feed age
    fb = fast.FastBook("X-USD", PaperExchange(cash=cash), venue="binanceus", threshold=threshold,
                       order_notional=50.0, journal_path=Path(tmp) / "fast.db",
                       check_feed_age=check_feed_age)
    for k, v in limits.items():
        setattr(fb.limits, k, v)
    return fb


class TestSignal(unittest.TestCase):
    def test_compute_signal_is_beta_scaled_gap_with_rolling_ic(self):
        rng = np.random.default_rng(0)
        n = 400
        lead = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, n))), index=range(n))
        coin = lead * np.exp(np.cumsum(rng.normal(0, 0.003, n))) * 0.5   # beta ~ 1 plus noise
        st = fast.compute_signal(coin, lead, window=168)
        self.assertIsNotNone(st.value)
        self.assertAlmostEqual(st.beta, 1.0, delta=0.3)
        self.assertIsNotNone(st.rolling_ic)
        self.assertEqual(st.error, "")

    def test_too_little_history_is_an_error_not_a_crash(self):
        s = pd.Series(np.arange(50, dtype=float))
        st = fast.compute_signal(s, s, window=168)
        self.assertIsNone(st.value)
        self.assertIn("need", st.error)


class TestScan(unittest.TestCase):
    def fetch(self, product, granularity, limit):
        rng = np.random.default_rng(abs(hash(product)) % 2**32)
        n = 300
        idx = np.arange(n) * 3600
        if product == "BAD-USD":
            raise OSError("404")
        lead = 100 * np.exp(np.cumsum(np.random.default_rng(7).normal(0, 0.01, n)))
        close = lead * np.exp(np.cumsum(rng.normal(0, 0.004, n)))
        return pd.DataFrame({"ts": idx, "close": close})

    def test_scan_sorts_by_absolute_gap_and_keeps_failures(self):
        rows = fast.scan(["BTC-USD", "AAA-USD", "BBB-USD", "BAD-USD"], fetch=self.fetch, pause=0)
        self.assertEqual([r.coin for r in rows][-1], "BAD")          # errors last
        self.assertNotIn("BTC", [r.coin for r in rows])              # the leader is not scanned
        gaps = [abs(r.state.value) for r in rows if r.state.value is not None]
        self.assertEqual(gaps, sorted(gaps, reverse=True))
        self.assertIn("404", rows[-1].state.error)

    def test_percentile_and_status(self):
        rows = fast.scan(["AAA-USD"], fetch=self.fetch, pause=0)
        st = rows[0].state
        self.assertTrue(0 < st.pct <= 1)
        self.assertEqual(fast.scan_status(fast.SignalState(value=0.004), 0.003), "BUY candidate")
        self.assertEqual(fast.scan_status(fast.SignalState(value=-0.004), 0.003), "sell if held")
        self.assertEqual(fast.scan_status(fast.SignalState(value=0.0025), 0.003), "near")
        self.assertEqual(fast.scan_status(fast.SignalState(value=0.0001), 0.003), "")

    def test_sources(self):
        from espero import hyperliquid as hl
        self.assertEqual(fast.source_feed("hyperliquid"), (hl.closed_bars, hl.HyperliquidBook))
        self.assertIs(fast.source_feed("coinbase")[1], fast.CoinbaseBook)
        coins = fast.scan_products("hyperliquid", listed={"BTC", "ETH", "kSHIB"})
        self.assertEqual(coins, ["BTC-USD", "ETH-USD", "SHIB-USD"])
        with self.assertRaises(ValueError):
            fast.source_feed("binance")

    def test_a_cold_signal_is_never_called_a_candidate(self):
        cold = dict(rolling_ic=-0.022)                 # LTC on 2026-10-29: +98 bps, IC -0.022
        self.assertEqual(fast.scan_status(fast.SignalState(value=0.0098, **cold), 0.003), "BUY (cold)")
        self.assertEqual(fast.scan_status(fast.SignalState(value=-0.004, **cold), 0.003), "sell (cold)")
        self.assertEqual(fast.scan_status(fast.SignalState(value=0.0098, rolling_ic=0.05), 0.003), "BUY candidate")

    @unittest.skipUnless(HAVE_RICH, "tui extra not installed")
    def test_scan_table_renders(self):
        import io

        from rich.console import Console
        rows = fast.scan(["AAA-USD", "BAD-USD"], fetch=self.fetch, pause=0)
        buf = io.StringIO()
        Console(file=buf, width=120).print(fast.scan_table(rows, 0.003, title="t"))
        out = buf.getvalue()
        self.assertIn("AAA", out)
        self.assertIn("OSError", out)

    def test_scan_products_skip_coins_coinbase_does_not_list(self):
        ps = fast.scan_products("coinbase")
        self.assertIn("ETH-USD", ps)
        self.assertNotIn("TRX-USD", ps)


class TestPrices(unittest.TestCase):
    def test_decimals_follow_the_price(self):
        self.assertEqual(fast.px(2314.561), "2,314.56")
        self.assertEqual(fast.px(2.57843), "2.5784")
        self.assertEqual(fast.px(0.123456), "0.12346")
        self.assertEqual(fast.px(0.0000123456), "0.00001235")
        self.assertEqual(fast.px(None), "-")

    def test_open_proposal_follows_the_touch_and_keeps_dollar_size(self):
        with tempfile.TemporaryDirectory() as d:
            fb = book(d)
            sig = fast.SignalState(value=0.01, beta=1.0, r_leader=0.01, r_coin=0.0)
            fb.on_snapshot(snap(bid=100.0, ask=100.1), sig)
            notional = fb.proposal.size * fb.proposal.price
            fb.on_snapshot(snap(ts=13, bid=101.0, ask=101.1), fast.SignalState(value=0.01))
            self.assertEqual(fb.proposal.price, 101.0)
            self.assertAlmostEqual(fb.proposal.size * fb.proposal.price, notional)
            fb.accept()
            o = fb.exchange.resting()[0]
            self.assertEqual(o.price, 101.0)
            self.assertAlmostEqual(o.queue_ahead, 1.0)          # only the size at the touch, not the levels above


class TestPrintsRate(unittest.TestCase):
    def test_prints_per_minute_averages_batched_ticks(self):
        with tempfile.TemporaryDirectory() as d:
            fb = book(d)
            for i in range(31):                             # a batch of 8 every 4 seconds, zeros between
                trades = [("buy", 100.1, 0.01)] * 8 if i % 4 == 0 else []
                fb.on_snapshot(snap(ts=float(i), trades=trades), fast.SignalState())
            self.assertAlmostEqual(fb.prints_per_min(), 60 * 64 / 30, places=6)


class TestCountdown(unittest.TestCase):
    def test_minutes_to_the_next_hourly_close(self):
        self.assertEqual(fast.next_signal_minutes(3600 * 10 + 5 * 60), 56)   # 10:05 -> 11:00, +1 refresh
        self.assertEqual(fast.next_signal_minutes(3600 * 10 + 59 * 60 + 30), 1)


class TestProposals(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_nothing_is_placed_without_accept(self):
        fb = book(self.tmp.name)
        fb.on_snapshot(snap(), fast.SignalState(value=0.01, beta=1.0, r_leader=0.01, r_coin=0.0))
        self.assertIsNotNone(fb.proposal)
        self.assertEqual(fb.proposal.side, "buy")
        self.assertEqual(fb.proposal.price, 100.0)          # at the bid, post-only
        self.assertEqual(fb.exchange.resting(), [])

    def test_accept_places_at_the_bid_and_decline_clears(self):
        fb = book(self.tmp.name)
        fb.on_snapshot(snap(), fast.SignalState(value=0.01, beta=1.0, r_leader=0.01, r_coin=0.0))
        oid = fb.accept()
        self.assertIsNotNone(oid)
        self.assertEqual(len(fb.exchange.resting()), 1)
        self.assertIsNone(fb.proposal)
        fb.on_snapshot(snap(ts=1), fast.SignalState(value=0.01))
        self.assertIsNone(fb.proposal)                      # no new proposal while one rests
        fb.cancel()
        fb.on_snapshot(snap(ts=2), fast.SignalState(value=0.01, beta=1.0, r_leader=0.01, r_coin=0.0))
        fb.decline()
        self.assertIsNone(fb.proposal)

    def test_no_proposal_below_threshold_or_without_signal(self):
        fb = book(self.tmp.name)
        fb.on_snapshot(snap(), fast.SignalState(value=0.001))
        self.assertIsNone(fb.proposal)
        fb.on_snapshot(snap(ts=1), fast.SignalState())
        self.assertIsNone(fb.proposal)

    def test_edge_budget_flags_a_thin_ratio(self):
        fb = book(self.tmp.name)
        fb.on_snapshot(snap(bid=100.0, ask=100.1), fast.SignalState(value=0.01, beta=1.0, r_leader=0.01, r_coin=0.0))
        p = fb.proposal
        self.assertAlmostEqual(p.edge_bps, fast.MEASURED_EDGE_BPS)
        self.assertGreater(p.cost_bps, 0)                   # binanceus maker 0 + half spread
        self.assertEqual(p.advised, p.ratio >= fast.MIN_EDGE_RATIO)

    def test_fill_then_horizon_exit_is_proposed(self):
        fb = book(self.tmp.name)
        fb.on_snapshot(snap(), fast.SignalState(value=0.01, beta=1.0, r_leader=0.01, r_coin=0.0))
        fb.accept()
        fills = fb.on_snapshot(snap(ts=5, trades=[("sell", 100.0, 5.0)]), fast.SignalState(value=0.0))
        self.assertEqual(len(fills), 1)
        self.assertGreater(fb.exchange.inventory, 0)
        fb.on_snapshot(snap(ts=5 + fast.HORIZON_H * 3600 + 1), fast.SignalState(value=0.0))
        self.assertIsNotNone(fb.proposal)
        self.assertEqual(fb.proposal.side, "sell")
        self.assertIn("exit", fb.proposal.reason)


class TestRiskAndJournal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_daily_loss_halts_and_cancels(self):
        fb = book(self.tmp.name, max_daily_loss=1.0)
        fb.on_snapshot(snap(), fast.SignalState(value=0.01, beta=1.0, r_leader=0.01, r_coin=0.0))
        fb.accept()
        fb.on_snapshot(snap(ts=1, trades=[("sell", 100.0, 5.0)]), fast.SignalState())   # filled 0.5 @ 100
        fb.on_snapshot(snap(ts=2, bid=90.0, ask=90.1), fast.SignalState(value=0.01))      # mark -5
        self.assertIn("daily loss", fb.halted)
        self.assertEqual(fb.exchange.resting(), [])
        self.assertIsNone(fb.proposal)
        self.assertIsNone(fb.accept())

    def test_orders_per_hour_cap(self):
        fb = book(self.tmp.name, max_orders_per_hour=2)
        for i in range(3):
            fb.on_snapshot(snap(ts=i), fast.SignalState(value=0.01, beta=1.0, r_leader=0.01, r_coin=0.0))
            fb.accept()
            fb.cancel()
        self.assertEqual(fb.halted, "max orders per hour")

    def test_kill_cancels_and_halts(self):
        fb = book(self.tmp.name)
        fb.on_snapshot(snap(), fast.SignalState(value=0.01, beta=1.0, r_leader=0.01, r_coin=0.0))
        fb.accept()
        fb.kill()
        self.assertEqual(fb.exchange.resting(), [])
        self.assertTrue(fb.halted)
        fb.on_snapshot(snap(ts=1), fast.SignalState(value=0.01, beta=1.0, r_leader=0.01, r_coin=0.0))
        self.assertIsNone(fb.proposal)

    def test_risk_strip_fractions(self):
        fb = book(self.tmp.name)
        fb.on_snapshot(snap(), fast.SignalState())
        r = fb.risk()
        self.assertEqual(set(r), {"inventory $", "day loss $", "orders/hr", "feed age s"})
        self.assertEqual(r["orders/hr"][0], 0)

    def test_fills_and_notes_land_in_the_journal_with_the_why(self):
        fb = book(self.tmp.name)
        fb.on_snapshot(snap(), fast.SignalState(value=0.01, beta=1.2, r_leader=0.01, r_coin=0.0, rolling_ic=0.05))
        fb.accept()
        fb.on_snapshot(snap(ts=3, trades=[("sell", 100.0, 5.0)]), fast.SignalState(value=0.0))
        fb.note("felt rushed")
        con = sqlite3.connect(Path(self.tmp.name) / "fast.db")
        row = con.execute("SELECT side, price, delay_s, why FROM fast_fills").fetchone()
        self.assertEqual(row[0], "buy")
        self.assertAlmostEqual(row[2], 3.0)
        self.assertIn('"beta": 1.2', row[3])
        self.assertEqual(con.execute("SELECT note FROM fast_notes").fetchone()[0], "felt rushed")

    def test_reprice_moves_resting_orders_to_the_touch(self):
        fb = book(self.tmp.name)
        fb.on_snapshot(snap(bid=100.0, ask=100.1), fast.SignalState(value=0.01, beta=1.0, r_leader=0.01, r_coin=0.0))
        fb.accept()
        fb.on_snapshot(snap(ts=1, bid=101.0, ask=101.1), fast.SignalState())
        fb.reprice()
        self.assertEqual(fb.exchange.resting()[0].price, 101.0)

    @unittest.skipUnless(HAVE_RICH, "tui extra not installed")
    def test_render_has_no_terminal_dependency(self):
        import io

        from rich.console import Console
        fb = book(self.tmp.name)
        fb.on_snapshot(snap(), fast.SignalState(value=0.01, beta=1.0, r_leader=0.01, r_coin=0.0, rolling_ic=-0.1))
        buf = io.StringIO()
        Console(file=buf, width=120).print(fast.render(fb, "TEST"))
        out = buf.getvalue()
        self.assertIn("proposal", out)
        self.assertIn("SIGNAL COLD", out)
        self.assertIn("budget", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestManualClose(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def holding(self):
        fb = book(self.tmp.name)
        fb.on_snapshot(snap(), fast.SignalState(value=0.01, beta=1.0, r_leader=0.01, r_coin=0.0))
        fb.accept()
        fb.on_snapshot(snap(ts=5, trades=[("sell", 100.0, 5.0)]), fast.SignalState(value=0.0))
        self.assertGreater(fb.exchange.inventory, 0)
        return fb

    def test_x_proposes_selling_everything_at_the_ask_and_enter_places_it(self):
        fb = self.holding()
        inv = fb.exchange.inventory
        fb.close_position()
        p = fb.proposal
        self.assertEqual((p.side, p.price, p.reason), ("sell", 100.1, "manual close"))
        self.assertAlmostEqual(p.size, inv)
        self.assertIsNotNone(fb.accept())
        rest = fb.exchange.resting()
        self.assertEqual([(o.side, o.price) for o in rest], [("sell", 100.1)])
        fb.on_snapshot(snap(ts=10, bid=100.1, ask=100.2, trades=[("buy", 100.1, 5.0)]), fast.SignalState(value=0.0))
        self.assertLessEqual(fb.exchange.inventory, 1e-12)

    def test_works_after_a_kill_and_not_without_a_position(self):
        fb = book(self.tmp.name)
        fb.on_snapshot(snap(), fast.SignalState(value=0.0))
        fb.close_position()
        self.assertIsNone(fb.proposal)
        self.assertIn("nothing to close", fb.log[-1])
        fb = self.holding()
        fb.kill()
        fb.close_position()
        self.assertIsNotNone(fb.accept())            # a halted screen can still get out

    def test_a_resting_exit_keeps_its_place(self):
        fb = self.holding()
        fb.close_position()
        fb.accept()
        first = fb.exchange.resting()[0]
        fb.close_position()
        self.assertIs(fb.exchange.resting()[0], first)
        self.assertIsNone(fb.proposal)
