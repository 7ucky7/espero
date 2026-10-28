"""Regression tests for the 2026-10-27 audit, section A: the bugs that could end
or skew a running forward test. One class per fix."""
from __future__ import annotations

import contextlib
import io
import math
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

import espero.paper as paper_mod
from espero import carry, cli
from espero import carry_paper as cp
from espero import degen as dg
from espero.journal import Journal, Position
from espero.loop import run_loop
from espero.paper import PaperConfig, PaperTrader
from espero.signals import Signal

H = 3600


# ------------------------------------------------------------------ loop guard
class TestRunLoop(unittest.TestCase):
    def test_a_failing_step_is_logged_and_retried_with_backoff(self):
        calls, waits, log = [], [], []

        def step():
            calls.append(1)
            if len(calls) in (2, 3):
                raise RuntimeError("network down")

        failures = run_loop(step, 10, "t", sleep=waits.append, log=log.append, max_steps=5)
        self.assertEqual((len(calls), failures), (5, 2))
        self.assertEqual(waits, [10, 10, 20, 10])               # doubled once, reset on success
        self.assertIn("RuntimeError: network down", log[0])
        self.assertIn("recovered after 2 failed steps", log[-1])

    def test_backoff_is_capped(self):
        waits = []
        run_loop(lambda: 1 / 0, 60, sleep=waits.append, log=lambda s: None, max_backoff=200, max_steps=6)
        self.assertEqual(waits, [60, 120, 200, 200, 200])

    def test_ctrl_c_still_stops_it(self):
        def step():
            raise KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            run_loop(step, 1, sleep=lambda s: None, log=lambda s: None, max_steps=3)


# ------------------------------------------------------------- transactions
class TestJournalTransaction(unittest.TestCase):
    def test_rollback_discards_every_write_of_the_unit(self):
        with tempfile.TemporaryDirectory() as d:
            j = Journal(Path(d) / "j.db")
            with self.assertRaises(ValueError):
                with j.transaction():
                    j.add_bar("X", {"ts": 1, "open": 1, "high": 1, "low": 1, "close": 1})
                    with j.transaction():                      # nested joins the outer
                        j.mark_equity(1, 10.0, 0.0)
                    raise ValueError("boom")
            self.assertIsNone(j.last_bar_ts("X"))
            self.assertEqual(j.latest_equity(), (0.0, 0.0))
            with j.transaction():
                j.mark_equity(2, 9.0, 1.0)
            j.close()
            j2 = Journal(Path(d) / "j.db")
            self.assertEqual(j2.latest_equity(), (9.0, 10.0))
            j2.close()


# --------------------------------------------------------------------- paper
GRAN = 1000


def pbar(i: int, open_px: float, close_px=None, high=None, low=None) -> dict:
    close_px = open_px if close_px is None else close_px
    return {"ts": 1_000_000 + i * GRAN, "open": open_px,
            "high": high if high is not None else max(open_px, close_px) * 1.001,
            "low": low if low is not None else min(open_px, close_px) * 0.999,
            "close": close_px, "volume": 1.0}


class Script:
    """combine() replacement: a side per call, None when the script runs out."""

    def __init__(self, *sides):
        self.sides, self.calls = list(sides), 0

    def __call__(self, sigs):
        self.calls += 1
        side = self.sides[self.calls - 1] if self.calls <= len(self.sides) else None
        return Signal(side, 0.9, "test") if side else None


class TestPaperFixes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.orig = paper_mod.combine
        self.cfg = PaperConfig(granularity=GRAN, initial=500.0, fee=0.0, slippage=0.0,
                               warmup=1, stop_pct=0.10, target_pct=0.20)
        self.journal = Journal(Path(self.tmp.name) / "p.db")
        self.t = PaperTrader(self.journal, self.cfg)

    def tearDown(self):
        paper_mod.combine = self.orig
        self.journal.close()
        self.tmp.cleanup()

    def long_with_queued_sell(self):
        paper_mod.combine = Script("BUY", "SELL")
        for i in range(3):
            self.t.on_bar(pbar(i, 100.0))                # BUY queued at bar 2's close
        self.t.on_bar(pbar(3, 100.0))                    # filled at 100, stop 90; SELL queued
        self.assertIsNotNone(self.t.position)
        self.assertEqual(self.t.pending.side, "SELL")

    def test_queued_sell_after_a_gap_stop_is_cancelled_not_a_crash(self):
        self.long_with_queued_sell()
        size = self.t.position.size
        events = self.t.on_bar(pbar(4, 80.0))            # opens through the stop
        self.assertTrue(any("gap_stop" in e for e in events), events)
        self.assertTrue(any("SELL cancelled" in e for e in events), events)
        self.assertIsNone(self.t.position)
        self.assertAlmostEqual(self.t.cash, 500.0 + (80.0 - 100.0) * size)
        status = self.journal.db.execute("SELECT status FROM orders WHERE side='SELL'").fetchone()[0]
        self.assertEqual(status, "no position")
        cash, equity = self.journal.latest_equity()
        self.assertAlmostEqual(cash, self.t.cash)       # the bar's cash was saved

    def test_a_failure_mid_bar_rolls_back_and_the_bar_can_be_replayed(self):
        paper_mod.combine = Script("BUY")
        for i in range(4):
            self.t.on_bar(pbar(i, 100.0))
        cash, pos_id = self.t.cash, self.t.position.id
        with mock.patch.object(self.journal, "close_position", side_effect=OSError("disk")):
            with self.assertRaises(OSError):
                self.t.on_bar(pbar(4, 100.0, low=85.0))  # stop hit, then the write fails
        self.assertEqual((self.t.cash, self.t.position.id), (cash, pos_id))
        self.assertEqual(self.journal.last_bar_ts(self.cfg.product), pbar(3, 0)["ts"])
        events = self.t.on_bar(pbar(4, 100.0, low=85.0))  # same bar again: now it books
        self.assertTrue(any("exit stop" in e for e in events), events)
        self.assertAlmostEqual(self.t.cash, cash + 90.0 * self.journal.closed_positions()[0]["size"])


def coinbase_bars(n: int, start: int, gran: int, price: float = 100.0) -> pd.DataFrame:
    ts = [start + i * gran for i in range(n)]
    return pd.DataFrame({"dt": pd.to_datetime(ts, unit="s", utc=True), "ts": ts, "open": price,
                         "high": price, "low": price, "close": price, "volume": 1.0})


class TestPaperLoopCatchUp(unittest.TestCase):
    def test_every_missed_bar_goes_through_on_bar(self):
        with tempfile.TemporaryDirectory() as d:
            state = str(Path(d) / "p.db")
            args = cli.build_parser().parse_args(["paper", "--state", state, "--granularity", "300"])
            seen = []
            real = PaperTrader.on_bar

            def spy(self, bar):
                seen.append(int(bar["ts"]))
                return real(self, bar)

            out = io.StringIO()
            with mock.patch.object(PaperTrader, "on_bar", spy), contextlib.redirect_stdout(out):
                with mock.patch("espero.data.recent_closed_bars", return_value=coinbase_bars(10, 0, 300)):
                    cli._paper_loop(args)                 # new journal: seed 9, trade the newest
                self.assertEqual(seen, [2700])
                with mock.patch("espero.data.recent_closed_bars", return_value=coinbase_bars(14, 0, 300)):
                    cli._paper_loop(args)                 # four bars arrived while away
            self.assertEqual(seen, [2700, 3000, 3300, 3600, 3900])
            self.assertIn("catching up 4 bars", out.getvalue())


# --------------------------------------------------------------------- degen
T0 = 1_700_000_100 // 300 * 300


def drow(product, ts, px=1.0, low=None, breakout=False, **kw):
    r = {"product": product, "ts": ts, "open": px, "high": px * (1.01 if breakout else 1.0),
         "low": px if low is None else low, "close": px, "volume": 100.0, "atr": 0.01,
         "range_x": 1.0, "breakout": breakout, "near": False, "vol_z": 3.0 if breakout else 0.0,
         "burst": 0.02 if breakout else 0.0, "dollar_volume": 5e6}
    r.update(kw)
    return r


class TestDegenFixes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.journal = Journal(Path(self.tmp.name) / "d.db")
        self.t = dg.DegenTrader(self.journal, dg.DegenConfig(initial=1000.0, fee=0.0, slippage=0.0))

    def tearDown(self):
        self.journal.close()
        self.tmp.cleanup()

    def enter(self):
        self.t.on_cycle({"AAA-USD": drow("AAA-USD", T0, breakout=True)})
        self.t.on_cycle({"AAA-USD": drow("AAA-USD", T0 + 300)})
        return self.t.positions["AAA-USD"]

    def test_a_coin_outside_the_universe_is_managed_but_never_bought(self):
        ev = self.t.on_cycle({"OUT-USD": drow("OUT-USD", T0, breakout=True, in_universe=False)})
        self.assertFalse(any("queued BUY" in e for e in ev), ev)
        pos = self.enter()
        ev = self.t.on_cycle({"AAA-USD": drow("AAA-USD", T0 + 600, low=0.97, in_universe=False)})
        self.assertTrue(any("exit stop" in e for e in ev), ev)
        self.assertAlmostEqual(self.t.cash, 1000.0 + (pos.stop - 1.0) * pos.size)

    def test_held_lists_positions_and_pending(self):
        self.t.on_cycle({"AAA-USD": drow("AAA-USD", T0, breakout=True)})
        self.assertEqual(self.t.held(), ["AAA-USD"])

    def test_a_failed_cycle_rolls_back_and_reloads(self):
        self.enter()
        cash = self.t.cash
        with mock.patch.object(self.journal, "close_position", side_effect=OSError("disk")):
            with self.assertRaises(OSError):
                self.t.on_cycle({"AAA-USD": drow("AAA-USD", T0 + 600, low=0.97)})
        self.assertEqual(self.t.cash, cash)
        self.assertIn("AAA-USD", self.t.positions)
        ev = self.t.on_cycle({"AAA-USD": drow("AAA-USD", T0 + 600, low=0.97)})
        self.assertTrue(any("exit stop" in e for e in ev), ev)


def five_min(n: int, start: int, px: float = 1.0) -> pd.DataFrame:
    ts = [start + i * 300 for i in range(n)]
    return pd.DataFrame({"dt": pd.to_datetime(ts, unit="s", utc=True), "ts": ts, "open": px,
                         "high": px, "low": px, "close": px, "volume": 100.0})


class TestDegenLoop(unittest.TestCase):
    def test_held_coin_outside_the_universe_is_still_fetched(self):
        with tempfile.TemporaryDirectory() as d:
            state = str(Path(d) / "d.db")
            j = Journal(state)
            j.open_position(Position("p1", "GONE-USD", T0, 1.0, 10.0, 0.9, 1.2))
            j.mark_equity(T0, 990.0, 10.0)
            j.close()
            args = cli.build_parser().parse_args(["degen", "paper", "--state", state])
            fetched = []

            def bars(product, gran, limit):
                fetched.append(product)
                return five_min(100, T0 - 50 * 300)

            uni = [{"product": "AAA-USD", "dollar_volume": 5e6}]
            with mock.patch.object(cli, "_degen_universe", return_value=uni), \
                    mock.patch.object(cli.data, "recent_closed_bars", side_effect=bars), \
                    mock.patch("time.sleep"), contextlib.redirect_stdout(io.StringIO()):
                cli._degen_loop(args)
            self.assertEqual(fetched, ["AAA-USD", "GONE-USD"])

    def test_a_coin_back_in_the_universe_trades_only_bars_after_the_last_cycle(self):
        with tempfile.TemporaryDirectory() as d:
            state = str(Path(d) / "d.db")
            j = Journal(state)
            old = five_min(100, T0 - 100 * 300)                  # AAA last seen long ago
            for bar in old.to_dict("records"):
                j.add_bar("AAA-USD", bar)
            for bar in five_min(100, T0 - 30 * 300).to_dict("records"):
                j.add_bar("BBB-USD", bar)
            j.mark_equity(T0 + 69 * 300, 1000.0, 0.0)            # the loop's last cycle
            j.close()
            args = cli.build_parser().parse_args(["degen", "paper", "--state", state])
            cycles = []
            real = dg.DegenTrader.on_cycle

            def spy(self, rows):
                cycles.append(sorted(rows))
                return real(self, rows)

            uni = [{"product": "AAA-USD", "dollar_volume": 5e6}, {"product": "BBB-USD", "dollar_volume": 5e6}]
            with mock.patch.object(cli, "_degen_universe", return_value=uni), \
                    mock.patch.object(cli.data, "recent_closed_bars",
                                      side_effect=lambda p, g, n: five_min(100, T0 - 28 * 300)), \
                    mock.patch.object(dg.DegenTrader, "on_cycle", spy), \
                    mock.patch("time.sleep"), contextlib.redirect_stdout(io.StringIO()):
                cli._degen_loop(args)
            # bars 70 and 71 come after the last cycle: both coins, together, in order
            self.assertEqual(cycles, [["AAA-USD", "BBB-USD"], ["AAA-USD", "BBB-USD"]])

    def test_a_new_coin_whose_newest_bar_is_not_past_the_last_cycle_is_only_seeded(self):
        with tempfile.TemporaryDirectory() as d:
            state = str(Path(d) / "d.db")
            j = Journal(state)
            j.mark_equity(T0 + 99 * 300, 1000.0, 0.0)            # last cycle = the fetch's newest bar
            j.close()
            args = cli.build_parser().parse_args(["degen", "paper", "--state", state])
            with mock.patch.object(cli, "_degen_universe",
                                   return_value=[{"product": "NEW-USD", "dollar_volume": 5e6}]), \
                    mock.patch.object(cli.data, "recent_closed_bars", side_effect=lambda p, g, n: five_min(100, T0)), \
                    mock.patch.object(dg.DegenTrader, "on_cycle") as cyc, \
                    mock.patch("time.sleep"), contextlib.redirect_stdout(io.StringIO()):
                cli._degen_loop(args)
            cyc.assert_not_called()
            j = Journal(state)
            self.assertEqual(j.last_bar_ts("NEW-USD"), T0 + 99 * 300)   # seeded for next time
            j.close()

    def test_universe_refresh_failure_keeps_trading_held_coins(self):
        with tempfile.TemporaryDirectory() as d:
            state = str(Path(d) / "d.db")
            j = Journal(state)
            j.open_position(Position("p1", "GONE-USD", T0, 1.0, 10.0, 0.9, 1.2))
            j.close()
            args = cli.build_parser().parse_args(["degen", "paper", "--state", state])
            fetched = []
            with mock.patch.object(cli, "_degen_universe", side_effect=RuntimeError("5xx")), \
                    mock.patch.object(cli.data, "recent_closed_bars",
                                      side_effect=lambda p, g, n: fetched.append(p) or five_min(100, T0)), \
                    mock.patch("time.sleep"), contextlib.redirect_stdout(io.StringIO()) as out:
                cli._degen_loop(args)
            self.assertEqual(fetched, ["GONE-USD"])
            self.assertIn("universe refresh failed", out.getvalue())


# --------------------------------------------------------------------- carry
RATE = 0.20 / carry.HOURS_PER_YEAR


def crow(f_ann=0.2, perp=101.0, spot=100.0, funding=RATE):
    return cp.Row(funding=funding, f_ann=f_ann, perp=perp, spot=spot)


class TestCarryBookFixes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.book = cp.CarryBook(Path(self.tmp.name) / "c.db", costs="maker", initial=500.0)

    def tearDown(self):
        self.book.close()
        self.tmp.cleanup()

    def test_nan_prices_never_reach_cash(self):
        self.book.on_hour(H, {"A": crow()})
        for bad in (crow(spot=float("nan")), crow(perp=float("nan")), crow(funding=float("nan"))):
            ts = self.book.last_ts() + H
            self.book.on_hour(ts, {"A": bad})
            self.assertTrue(math.isfinite(self.book.cash))
            self.assertEqual(len(self.book.open_positions()), 1)
        self.book.close()
        again = cp.CarryBook(self.book.path, costs="maker")
        self.assertTrue(math.isfinite(again.cash))
        again.close()
        self.book = cp.CarryBook(self.book.path, costs="maker")

    def test_a_failed_hour_rolls_back_and_can_be_replayed(self):
        self.book.on_hour(H, {"A": crow()})
        cash = self.book.cash
        with mock.patch.object(self.book, "equity", side_effect=OSError("disk")):
            with self.assertRaises(OSError):
                self.book.on_hour(2 * H, {"A": crow()})
        self.assertEqual(self.book.cash, cash)
        self.assertEqual(self.book.last_ts(), H)
        self.assertEqual(self.book.open_positions()[0]["funding"], 0.0)   # the credit was undone
        self.book.on_hour(2 * H, {"A": crow()})
        self.assertGreater(self.book.open_positions()[0]["funding"], 0.0)

    def test_entries_stay_inside_the_universe(self):
        self.book.on_hour(H, {"A": crow(), "B": crow(f_ann=0.5)}, universe=["A"])
        self.assertEqual([p["coin"] for p in self.book.open_positions()], ["A"])


def hl_fetch(funding_upto: dict, perp=101.0):
    """Fake info endpoint: per coin, hourly funding rows up to a last hour."""
    def fetch(body):
        coin = body.get("coin") or body["req"]["coin"]
        last = funding_upto[coin]
        if body["type"] == "fundingHistory":
            start = body["startTime"] // 1000
            return [{"time": t * 1000 + 40, "fundingRate": str(RATE)}
                    for t in range((start // H + 1) * H, last + 1, H)][:500]
        if body["type"] == "candleSnapshot":
            s = body["req"]["startTime"] // 1000 // H * H
            return [{"t": t * 1000, "o": "1", "h": "1", "l": "1", "c": str(perp), "v": "1"}
                    for t in range(s, last + 1, H)]
        raise AssertionError(body)
    return fetch


def spot(_product):
    ts = [NOW_H - k * H for k in range(80, -1, -1)]
    return pd.DataFrame({"ts": ts, "close": 100.0})


NOW_H = 1_800_000_000 // H * H


class TestSettledHours(unittest.TestCase):
    def call(self, upto, since, now, **kw):
        return cp.settled_hours(list(upto), since_ts=since, fetch=hl_fetch(upto), spot_fetch=spot,
                                sleep=lambda s: None, now=now, **kw)

    def test_missed_hours_are_rebuilt_in_order(self):
        hours = self.call({"A": NOW_H, "B": NOW_H}, NOW_H - 5 * H, NOW_H + 60)
        self.assertEqual([t for t, _ in hours], [NOW_H - 4 * H + k * H for k in range(5)])
        ts, rows = hours[0]
        self.assertEqual(set(rows), {"A", "B"})
        self.assertAlmostEqual(rows["A"].f_ann, RATE * carry.HOURS_PER_YEAR)
        self.assertEqual((rows["A"].perp, rows["A"].spot), (101.0, 100.0))

    def test_backfill_is_capped(self):
        hours = self.call({"A": NOW_H}, NOW_H - 200 * H, NOW_H + 60, max_backfill_h=10)
        self.assertEqual(hours[0][0], NOW_H - 10 * H + H)    # (now - 10h, now]

    def test_a_lagging_coin_holds_the_newest_hour_back_until_the_grace_ends(self):
        upto = {"A": NOW_H, "B": NOW_H - H}
        early = self.call(upto, NOW_H - 2 * H, NOW_H + 60)
        self.assertEqual([t for t, _ in early], [NOW_H - H])
        late = self.call(upto, NOW_H - 2 * H, NOW_H + cp.PUBLISH_GRACE_S + 1)
        self.assertEqual([t for t, _ in late], [NOW_H - H, NOW_H])
        self.assertEqual(set(late[-1][1]), {"A"})

    def test_new_book_gets_only_the_latest_hour(self):
        hours = self.call({"A": NOW_H}, None, NOW_H + 60)
        self.assertEqual([t for t, _ in hours], [NOW_H])

    def test_book_credits_every_backfilled_hour_like_the_backtest(self):
        with tempfile.TemporaryDirectory() as d:
            book = cp.CarryBook(Path(d) / "c.db", costs="maker", initial=500.0)
            book.on_hour(NOW_H - 6 * H, {"A": crow()})
            qty = book.open_positions()[0]["qty_perp"]
            for ts, rows in self.call({"A": NOW_H}, book.last_ts(), NOW_H + 60):
                book.on_hour(ts, rows)
            self.assertEqual(book.last_ts(), NOW_H)
            self.assertAlmostEqual(book.open_positions()[0]["funding"], 6 * RATE * qty * 101.0)
            book.close()


class TestCarryLoop(unittest.TestCase):
    def run_step(self, state, hours, universe=("A",)):
        args = cli.build_parser().parse_args(["carry", "paper", "--costs", "maker", "--state", state])
        calls = []

        def fake_hours(coins, since_ts=None):
            calls.append((list(coins), since_ts))
            return hours

        with mock.patch.object(cp, "universe", return_value=list(universe)), \
                mock.patch.object(cp, "settled_hours", side_effect=fake_hours), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            cli._carry_loop(args)
        return calls, out.getvalue()

    def test_held_coins_are_fetched_and_every_hour_is_booked(self):
        with tempfile.TemporaryDirectory() as d:
            state = str(Path(d) / "c.db")
            b = cp.CarryBook(state, costs="maker")
            b.on_hour(NOW_H - 3 * H, {"GONE": crow()})
            b.close()
            hours = [(NOW_H - 2 * H, {"GONE": crow()}), (NOW_H - H, {"GONE": crow(f_ann=0.01)})]
            with mock.patch("time.time", return_value=NOW_H + 60):
                calls, out = self.run_step(state, hours)
            self.assertEqual(calls, [(["A", "GONE"], NOW_H - 3 * H)])
            self.assertIn("catching up 2 settled hours", out)
            b = cp.CarryBook(state, costs="maker")
            self.assertEqual(b.last_ts(), NOW_H - H)
            self.assertEqual(b.closed_positions()[0]["reason"], "funding_low")
            b.close()

    def test_no_fetch_before_the_next_settlement_is_due(self):
        with tempfile.TemporaryDirectory() as d:
            state = str(Path(d) / "c.db")
            b = cp.CarryBook(state, costs="maker")
            b.on_hour(NOW_H, {"A": crow()})
            b.close()
            with mock.patch("time.time", return_value=NOW_H + 1800):
                calls, out = self.run_step(state, [])
            self.assertEqual(calls, [])
            self.assertIn("booked", out)


if __name__ == "__main__":
    unittest.main()
