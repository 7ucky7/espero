"""打板: the scan ranks the planted breakout first, and the trader's exits are in ATR units."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

from espero import data
from espero import degen as dg
from espero.indicators import atr, true_range
from espero.journal import Journal

GRAN = dg.GRANULARITY
T0 = 1_700_000_000 - (1_700_000_000 % (8 * 3600))   # on a funding boundary


def bars(n: int = 120, price: float = 1.0, vol: float = 100.0, seed: int = 0, noise: float = 0.001) -> pd.DataFrame:
    """Flat, quiet bars: a market with nothing happening."""
    rng = np.random.default_rng(seed)
    close = price * np.exp(np.cumsum(rng.normal(0, noise, n)))
    df = pd.DataFrame({
        "ts": T0 + GRAN * np.arange(n), "open": close, "close": close,
        "high": close * (1 + noise), "low": close * (1 - noise), "volume": vol,
    })
    return df


def plant_breakout(df: pd.DataFrame, at: int = -1, jump: float = 0.03, vol_mult: float = 8.0) -> pd.DataFrame:
    """A new high on a volume spike at bar `at`, with the hour before drifting up."""
    df = df.copy()
    i = len(df) + at if at < 0 else at
    for k in range(i - dg.BURST_BARS + 1, i):
        df.loc[k, ["open", "close", "high", "low"]] *= 1 + jump / 4
    px = float(df.loc[i, "close"]) * (1 + jump)
    df.loc[i, ["close", "high"]] = px
    df.loc[i, "volume"] *= vol_mult
    return df


class TestATR(unittest.TestCase):
    def test_true_range_takes_the_gap_into_account(self):
        df = pd.DataFrame({"high": [10, 12], "low": [9, 11.5], "close": [9.5, 11.8]})
        tr = true_range(df)
        self.assertAlmostEqual(tr.iloc[0], 1.0)          # first bar: its own range
        self.assertAlmostEqual(tr.iloc[1], 12 - 9.5)     # gap from the prior close counts

    def test_atr_is_causal(self):
        df = bars(200, noise=0.01, seed=3)
        full = atr(df)
        head = atr(df.iloc[:150])
        self.assertAlmostEqual(float(full.iloc[149]), float(head.iloc[149]), places=12)


class TestUniverse(unittest.TestCase):
    PRODUCTS = [
        {"id": "SOL-USD", "base_currency": "SOL", "quote_currency": "USD", "status": "online"},
        {"id": "DOGE-USD", "base_currency": "DOGE", "quote_currency": "USD", "status": "online"},
        {"id": "BTC-USD", "base_currency": "BTC", "quote_currency": "USD", "status": "online"},
        {"id": "USDT-USD", "base_currency": "USDT", "quote_currency": "USD", "status": "online"},
        {"id": "XYZ-USD", "base_currency": "XYZ", "quote_currency": "USD", "status": "online", "fx_stablecoin": True},
        {"id": "OLD-USD", "base_currency": "OLD", "quote_currency": "USD", "status": "online",
         "trading_disabled": True},
        {"id": "DEL-USD", "base_currency": "DEL", "quote_currency": "USD", "status": "delisted"},
        {"id": "SOL-EUR", "base_currency": "SOL", "quote_currency": "EUR", "status": "online"},
    ]
    STATS = {"SOL-USD": {"last": "100", "volume": "1000"}, "DOGE-USD": {"last": "0.1", "volume": "5000000"}}

    def fetch(self, url):
        if url.endswith("/products"):
            return self.PRODUCTS
        p = url.split("/products/")[1].split("/")[0]
        if p not in self.STATS:
            raise data.FetchError("404")
        return self.STATS[p]

    def test_list_products_drops_majors_stables_and_dead_pairs(self):
        self.assertEqual(data.list_products(fetch=self.fetch), ["DOGE-USD", "SOL-USD"])

    def test_universe_is_ranked_by_dollar_volume(self):
        uni = data.degen_universe(top=5, fetch=self.fetch, pause=0)
        self.assertEqual([u["product"] for u in uni], ["DOGE-USD", "SOL-USD"])   # 500k > 100k
        self.assertAlmostEqual(uni[0]["dollar_volume"], 500_000.0)

    def test_a_failing_stats_call_is_skipped_not_fatal(self):
        uni = data.degen_universe(top=5, products=["SOL-USD", "GONE-USD"], fetch=self.fetch, pause=0)
        self.assertEqual([u["product"] for u in uni], ["SOL-USD"])

    def test_top_cuts_the_list(self):
        self.assertEqual(len(data.degen_universe(top=1, fetch=self.fetch, pause=0)), 1)


class TestScan(unittest.TestCase):
    def frames(self):
        return {
            "AAA-USD": plant_breakout(bars(seed=1)),
            "BBB-USD": bars(seed=2),
            "CCC-USD": plant_breakout(bars(seed=3), vol_mult=1.0),   # new high on normal volume
        }

    def fetch(self, product, granularity, limit):
        if product == "BAD-USD":
            raise OSError("404")
        return self.frames()[product]

    def universe(self, *products):
        return [{"product": p, "dollar_volume": 5e6} for p in products]

    def test_features_are_causal(self):
        df = plant_breakout(bars(seed=5), at=90)
        full, head = dg.features(df), dg.features(df.iloc[:91])
        for c in ("burst", "vol_z", "atr", "range_x"):
            self.assertAlmostEqual(float(full[c].iloc[90]), float(head[c].iloc[90]), places=10, msg=c)
        self.assertTrue(bool(full["breakout"].iloc[90]))

    def test_planted_breakout_ranks_first_and_is_the_only_candidate(self):
        rows = dg.scan(self.universe("BBB-USD", "CCC-USD", "AAA-USD", "BAD-USD"), fetch=self.fetch, pause=0)
        self.assertEqual(rows[0]["product"], "AAA-USD")
        self.assertEqual(rows[0]["status"], "BREAKOUT")
        self.assertEqual([r["status"] for r in rows if r["product"] == "CCC-USD"], [""])
        self.assertEqual(rows[-1]["product"], "BAD-USD")
        self.assertIn("404", rows[-1]["error"])

    def test_illiquid_breakout_is_flagged_not_a_candidate(self):
        uni = [{"product": "AAA-USD", "dollar_volume": 1e5}]
        rows = dg.scan(uni, fetch=self.fetch, pause=0)
        self.assertEqual(rows[0]["status"], "breakout (illiquid)")

    def test_too_little_history_is_an_error_row(self):
        rows = dg.scan(self.universe("AAA-USD"), fetch=lambda p, g, n: bars(10), pause=0)
        self.assertIn("only 10 bars", rows[0]["error"])


# ----------------------------------------------------------------- the trader
def row(product: str, ts: int, open_: float, high: float, low: float, close: float, atr_: float = 0.01,
        breakout: bool = False, vol_z: float = 0.0, burst: float = 0.0, dollar_volume: float = 5e6) -> dict:
    return {"product": product, "ts": ts, "open": open_, "high": high, "low": low, "close": close,
            "volume": 100.0, "atr": atr_, "range_x": (high - low) / atr_, "breakout": breakout, "near": False,
            "vol_z": vol_z, "burst": burst, "dollar_volume": dollar_volume}


def signal(product: str, ts: int, px: float = 1.0, atr_: float = 0.01) -> dict:
    return row(product, ts, px, px * 1.01, px * 0.99, px, atr_, breakout=True, vol_z=3.0, burst=0.02)


def quiet(product: str, ts: int, px: float = 1.0, atr_: float = 0.01) -> dict:
    return row(product, ts, px, px, px, px, atr_)


class TestTrader(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "degen.db"
        self.journal = Journal(self.path)
        self.cfg = dg.DegenConfig(venue="binanceus", initial=1000.0, fee=0.0, slippage=0.0)
        self.t = dg.DegenTrader(self.journal, self.cfg)

    def tearDown(self):
        self.journal.close()
        self.tmp.cleanup()

    def ts(self, i: int) -> int:
        return T0 + i * GRAN

    def enter(self, product="AAA-USD", px=1.0, atr_=0.01):
        """Signal at bar 0, fill at bar 1's open. Returns the position."""
        ev = self.t.on_cycle({product: signal(product, self.ts(0), px, atr_)})
        self.assertTrue(any("queued BUY" in e for e in ev), ev)
        ev = self.t.on_cycle({product: quiet(product, self.ts(1), px, atr_)})
        self.assertTrue(any("filled BUY" in e for e in ev), ev)
        return self.t.positions[product]

    def test_entry_fills_next_open_with_atr_stop_and_target(self):
        pos = self.enter(px=1.0, atr_=0.01)
        self.assertAlmostEqual(pos.entry_px, 1.0)
        self.assertAlmostEqual(pos.stop, 1.0 - dg.STOP_ATR * 0.01)
        self.assertAlmostEqual(pos.target, 1.0 + dg.TARGET_ATR * 0.01)
        # risk 1% of equity at a 2% stop -> 50% of equity, capped at 25%
        self.assertAlmostEqual(pos.size * pos.entry_px, 250.0, places=6)

    def test_a_wider_atr_means_a_smaller_position_and_a_wider_stop(self):
        pos = self.enter(px=1.0, atr_=0.05)    # 10% stop -> 1% / 10% = 10% of equity
        self.assertAlmostEqual(pos.size * pos.entry_px, 100.0, places=6)
        self.assertAlmostEqual(pos.stop, 0.90)

    def test_stop_fills_at_the_stop_price(self):
        pos = self.enter()
        ev = self.t.on_cycle({"AAA-USD": row("AAA-USD", self.ts(2), 1.0, 1.0, 0.97, 0.975)})
        self.assertTrue(any("exit stop" in e for e in ev), ev)
        self.assertNotIn("AAA-USD", self.t.positions)
        self.assertAlmostEqual(self.t.cash, 1000.0 + (pos.stop - 1.0) * pos.size)

    def test_gap_through_the_stop_fills_at_the_open(self):
        pos = self.enter()
        self.t.on_cycle({"AAA-USD": row("AAA-USD", self.ts(2), 0.95, 0.96, 0.94, 0.95)})
        closed = self.journal.closed_positions()[0]
        self.assertEqual(closed["reason"], "gap_stop")
        self.assertAlmostEqual(closed["exit_px"], 0.95)
        self.assertAlmostEqual(self.t.cash, 1000.0 + (0.95 - 1.0) * pos.size)

    def test_target_fills_at_the_target(self):
        self.enter()
        self.t.on_cycle({"AAA-USD": row("AAA-USD", self.ts(2), 1.0, 1.05, 1.0, 1.04)})
        closed = self.journal.closed_positions()[0]
        self.assertEqual(closed["reason"], "target")
        self.assertAlmostEqual(closed["exit_px"], 1.03)

    def test_trail_ratchets_up_only_and_survives_a_restart(self):
        pos = self.enter()
        self.t.on_cycle({"AAA-USD": row("AAA-USD", self.ts(2), 1.0, 1.02, 1.0, 1.02)})
        self.assertAlmostEqual(pos.stop, 1.02 - dg.TRAIL_ATR * 0.01)     # 0.995 > the 0.98 initial
        self.t.on_cycle({"AAA-USD": row("AAA-USD", self.ts(3), 1.02, 1.02, 1.0, 1.0)})
        self.assertAlmostEqual(pos.stop, 0.995)                           # a lower bar never lowers it
        again = dg.DegenTrader(self.journal, self.cfg)
        self.assertAlmostEqual(again.positions["AAA-USD"].stop, 0.995)
        self.assertAlmostEqual(again.high_water["AAA-USD"], 1.02)

    def test_time_stop_queues_a_sell_filled_at_the_next_open(self):
        self.enter()
        for i in range(2, 2 + dg.TIME_STOP_BARS):
            ev = self.t.on_cycle({"AAA-USD": quiet("AAA-USD", self.ts(i))})
        self.assertTrue(any("time stop" in e for e in ev), ev)
        self.assertIn("AAA-USD", self.t.positions)                        # still held until the next open
        ev = self.t.on_cycle({"AAA-USD": quiet("AAA-USD", self.ts(2 + dg.TIME_STOP_BARS), 1.004)})
        self.assertTrue(any("exit time" in e for e in ev), ev)
        self.assertAlmostEqual(self.journal.closed_positions()[0]["exit_px"], 1.004)

    def test_never_exits_on_the_entry_bar(self):
        self.t.on_cycle({"AAA-USD": signal("AAA-USD", self.ts(0))})
        self.t.on_cycle({"AAA-USD": row("AAA-USD", self.ts(1), 1.0, 1.0, 0.90, 0.95)})   # crash on the fill bar
        self.assertIn("AAA-USD", self.t.positions)

    def test_three_slots_then_no_more(self):
        coins = ["A-USD", "B-USD", "C-USD", "D-USD"]
        ev = self.t.on_cycle({c: signal(c, self.ts(0)) for c in coins})
        self.assertEqual(sum("queued BUY" in e for e in ev), 3)
        self.assertEqual(sum("no slot" in e for e in ev), 1)
        self.t.on_cycle({c: quiet(c, self.ts(1)) for c in coins})
        self.assertEqual(len(self.t.positions), 3)

    def test_no_double_entry_in_a_held_coin(self):
        self.enter()
        ev = self.t.on_cycle({"AAA-USD": signal("AAA-USD", self.ts(2))})
        self.assertFalse(any("queued BUY" in e for e in ev), ev)

    def test_duplicate_cycle_is_ignored(self):
        self.enter()
        self.assertEqual(self.t.on_cycle({"AAA-USD": quiet("AAA-USD", self.ts(1))}), [])

    def test_illiquid_breakout_is_not_traded(self):
        r = signal("AAA-USD", self.ts(0))
        r["dollar_volume"] = 1e5
        self.assertFalse(any("queued" in e for e in self.t.on_cycle({"AAA-USD": r})))

    def test_fees_are_charged_per_side(self):
        self.cfg.fee = 0.004
        self.t = dg.DegenTrader(self.journal, self.cfg)
        pos = self.enter()
        self.assertAlmostEqual(pos.entry_fee, 250.0 * 0.004)
        self.t.on_cycle({"AAA-USD": row("AAA-USD", self.ts(2), 1.0, 1.05, 1.0, 1.04)})
        closed = self.journal.closed_positions()[0]
        expect = (1.03 - 1.0) * pos.size - 1.03 * pos.size * 0.004 - pos.entry_fee
        self.assertAlmostEqual(closed["pnl"], expect)

    def test_perp_funding_is_charged_once_at_the_settlement(self):
        self.cfg.funding_8h = 0.0001
        self.t = dg.DegenTrader(self.journal, self.cfg)
        pos = self.enter()
        n = 8 * 3600 // GRAN                       # the bar that closes on the settlement
        with mock.patch.object(dg, "TIME_STOP_BARS", 10_000):   # hold through it
            for i in range(2, n):
                ev = self.t.on_cycle({"AAA-USD": quiet("AAA-USD", self.ts(i))})
                self.assertFalse(any("funding" in e for e in ev), (i, ev))
            ev = self.t.on_cycle({"AAA-USD": quiet("AAA-USD", self.ts(n))})
        self.assertTrue(any("funding paid" in e for e in ev), ev)
        self.assertAlmostEqual(pos.entry_fee, pos.size * 1.0 * 0.0001)

    def test_resume_picks_up_positions_and_pending_orders(self):
        self.t.on_cycle({"AAA-USD": signal("AAA-USD", self.ts(0))})
        again = dg.DegenTrader(self.journal, self.cfg)
        self.assertIn("AAA-USD", again.pending)
        again.on_cycle({"AAA-USD": quiet("AAA-USD", self.ts(1))})
        self.assertIn("AAA-USD", again.positions)
        third = dg.DegenTrader(self.journal, self.cfg)
        self.assertAlmostEqual(third.cash, again.cash)


class TestRule13(unittest.TestCase):
    """#13: 1-hour bars, at most one entry per bar, and the coin must beat BTC."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.journal = Journal(Path(self.tmp.name) / "degen-1h.db")
        cfg = dg.DegenConfig.for_venue("binanceus", rule="13", initial=1000.0)
        cfg.fee = cfg.slippage = 0.0
        self.t = dg.DegenTrader(self.journal, cfg)

    def tearDown(self):
        self.journal.close()
        self.tmp.cleanup()

    def btc(self, ts: int, burst: float = 0.0) -> dict:
        return dict(quiet(dg.BENCHMARK, ts), burst=burst)

    def test_rule_table_sets_the_hour_and_both_filters(self):
        self.assertEqual(self.t.cfg.granularity, 3600)
        self.assertTrue(self.t.cfg.one_entry_per_bar and self.t.cfg.beat_benchmark)
        ten = dg.DegenConfig.for_venue("binanceus")
        self.assertEqual((ten.granularity, ten.one_entry_per_bar, ten.beat_benchmark), (300, False, False))

    def test_three_breakouts_on_one_bar_are_one_trade_the_best_scored(self):
        coins = {c: dict(signal(c, T0), burst=b) for c, b in (("A-USD", 0.01), ("B-USD", 0.05), ("C-USD", 0.03))}
        ev = self.t.on_cycle(coins, self.btc(T0))
        self.assertEqual(sum("queued BUY" in e for e in ev), 1)
        self.assertEqual(list(self.t.pending), ["B-USD"])

    def test_a_breakout_that_lags_btc_is_not_bought(self):
        ev = self.t.on_cycle({"A-USD": signal("A-USD", T0)}, self.btc(T0, burst=0.03))   # 0.02 < 0.03
        self.assertFalse(any("queued BUY" in e for e in ev))
        ev = self.t.on_cycle({"A-USD": signal("A-USD", T0 + 3600)}, self.btc(T0 + 3600, burst=0.01))
        self.assertTrue(any("queued BUY" in e for e in ev))

    def test_no_btc_bar_for_this_hour_means_no_entry(self):
        self.assertEqual(self.t.on_cycle({"A-USD": signal("A-USD", T0)}, None), [])
        stale = self.btc(T0 - 3600)
        self.assertEqual(self.t.on_cycle({"A-USD": signal("A-USD", T0 + 3600)}, stale), [])

    def test_control_rule_has_neither_filter(self):
        cfg = dg.DegenConfig.for_venue("binanceus", rule="13-control", initial=1000.0)
        t = dg.DegenTrader(self.journal, cfg)
        ev = t.on_cycle({c: signal(c, T0 + 7200) for c in ("A-USD", "B-USD")})
        self.assertEqual(sum("queued BUY" in e for e in ev), 2)


class TestReplay(unittest.TestCase):
    def frames(self):
        return {"AAA-USD": plant_breakout(bars(300, seed=11, noise=0.002), at=150, jump=0.06),
                "BBB-USD": bars(300, seed=12, noise=0.002)}

    def test_replay_trades_the_planted_breakout_and_rows_share_gross(self):
        rows = dg.compare_venues(self.frames(), ["binanceus", "coinbase"], initial=1000.0)
        self.assertEqual([r["venue"] for r in rows], ["binanceus", "coinbase"])
        self.assertGreaterEqual(rows[0]["trades"], 1)
        self.assertEqual(rows[0]["trades"], rows[1]["trades"])
        self.assertGreater(rows[1]["entry_fees"], rows[0]["entry_fees"])
        self.assertLess(rows[1]["pnl"], rows[0]["pnl"])

    def test_rule_13_replay_needs_the_benchmark(self):
        flat = bars(300, seed=13, noise=0.0005)
        with_btc = dg.replay(self.frames(), "binanceus", 1000.0, rule="13", benchmark=flat)
        without = dg.replay(self.frames(), "binanceus", 1000.0, rule="13")
        self.assertGreaterEqual(with_btc["trades"], 1)
        self.assertEqual(without["trades"], 0)

    def test_verdict_needs_all_five(self):
        good = {"venue": "binanceus", "trades": 40, "profit_factor": 1.5, "pnl": 10.0, "max_dd_pct": 0.05}
        kr = {"venue": "kraken", "pnl": 1.0}
        self.assertTrue(all(c["met"] for c in dg.verdict([good, kr])))
        kr["pnl"] = -1.0
        self.assertEqual([c["met"] for c in dg.verdict([good, kr])][-1], False)
        self.assertFalse(any(c["met"] for c in dg.verdict([kr])))


class TestCLI(unittest.TestCase):
    def test_scan_prints_a_table_without_writing(self):
        from espero.cli import main
        uni = [{"product": "AAA-USD", "dollar_volume": 5e6}]
        with mock.patch.object(data, "degen_universe", return_value=uni), \
             mock.patch.object(data, "recent_closed_bars", side_effect=lambda p, g, n: plant_breakout(bars())), \
             mock.patch("sys.stdout") as out:
            self.assertEqual(main(["degen", "scan", "--top", "1"]), 0)
        text = "".join(str(c.args[0]) for c in out.write.call_args_list)
        self.assertIn("AAA-USD", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
