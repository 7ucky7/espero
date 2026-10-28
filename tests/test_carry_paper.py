"""The live carry book must be the backtest engine, one hour at a time."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from espero import carry
from espero import carry_paper as cp

H = 3600
RATE20 = 0.20 / carry.HOURS_PER_YEAR


def synthetic(n: int = 900, seed: int = 7) -> dict:
    """Three coins with wandering prices, a persistent basis and funding that
    turns on and off, so every branch (enter, swap, funding_low, time) fires."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2025-01-01", periods=n, freq="h", tz="UTC")
    coins = {}
    for k, name in enumerate(("A", "B", "C")):
        spot = 100 * (1 + k) * np.exp(np.cumsum(rng.normal(0, 0.003, n)))
        perp = spot * (1 + 0.001 * (1 + 0.5 * np.sin(np.arange(n) / 50 + k)))
        rate = np.full(n, RATE20 * (1 + 0.6 * k))
        rate[300 + 100 * k: 450 + 100 * k] = 0.0          # funding dries up for a stretch
        rate[600:] = RATE20 * (3 - k)                      # ranks flip late
        coins[name] = carry.CoinData(pd.Series(rate, index=idx), pd.Series(perp, index=idx),
                                     pd.Series(spot, index=idx))
    return coins


def rows_at(coins: dict, i: int, idx: pd.DatetimeIndex, f_ann: pd.DataFrame) -> dict:
    return {name: cp.Row(funding=float(c.funding.iloc[i]), f_ann=float(f_ann[name].iloc[i]),
                         perp=float(c.perp.iloc[i]), spot=float(c.spot.iloc[i]))
            for name, c in coins.items()}


class TestEquivalence(unittest.TestCase):
    def replay(self, costs: str, max_coins: int = 2, **rule) -> tuple[list, list, list, list]:
        coins = synthetic()
        idx, fund, _, _ = carry.align(coins)
        f_ann = carry.annualised(fund)
        sim = carry.simulate(coins, initial=500.0, max_coins=max_coins, **cp.COSTS[costs], **rule)
        with tempfile.TemporaryDirectory() as d:
            book = cp.CarryBook(Path(d) / "b.db", costs=costs, initial=500.0, max_coins=max_coins,
                                swap_gap=rule.get("swap_gap", 0.0), min_hold=rule.get("min_hold", 0))
            live = []
            for i, t in enumerate(idx):
                book.on_hour(int(t.timestamp()), rows_at(coins, i, idx, f_ann))
                live.append(book.equity(rows_at(coins, i, idx, f_ann)))
            closed = book.closed_positions()
            book.close()
        return list(sim.equity.to_numpy()), live, sim.trades, closed

    def test_twelve_rule_maker_costs_match_to_the_cent(self):
        sim_eq, live_eq, sim_tr, live_tr = self.replay("maker", swap_gap=carry.SWAP_GAP,
                                                       min_hold=carry.MIN_HOLD_H)
        self.assertGreater(len(sim_tr), 3)
        # the engine closes everything at the end; the book leaves it open, so compare before that
        np.testing.assert_allclose(sim_eq[:-1], live_eq[:-1], atol=0.005)
        self.assertEqual([t["reason"] for t in sim_tr if t["reason"] != "end"],
                         [r["reason"] for r in live_tr])

    def test_eleven_rule_taker_costs_match_to_the_cent(self):
        sim_eq, live_eq, sim_tr, live_tr = self.replay("taker")
        self.assertIn("ranked_out", [t["reason"] for t in sim_tr])
        np.testing.assert_allclose(sim_eq[:-1], live_eq[:-1], atol=0.005)


class TestBook(unittest.TestCase):
    def rows(self, f_ann: float = 0.2, perp: float = 101.0, spot: float = 100.0) -> dict:
        return {"A": cp.Row(funding=RATE20, f_ann=f_ann, perp=perp, spot=spot)}

    def test_resume_and_idempotent_hours(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "b.db"
            b = cp.CarryBook(path, costs="maker", initial=500.0)
            ev = b.on_hour(10 * H, self.rows())
            self.assertEqual(len(ev), 1)
            self.assertEqual(b.on_hour(10 * H, self.rows()), [])        # repeat ignored
            cash = b.cash
            b.close()
            b2 = cp.CarryBook(path, costs="maker")
            self.assertEqual(b2.cash, cash)
            self.assertEqual(len(b2.open_positions()), 1)
            self.assertEqual(b2.last_ts(), 10 * H)
            b2.on_hour(11 * H, self.rows())
            self.assertAlmostEqual(b2.open_positions()[0]["funding"], RATE20 * 250.0 / 101.0 * 101.0, places=6)
            b2.close()

    def test_costs_mismatch_refused(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "b.db"
            cp.CarryBook(path, costs="maker").close()
            with self.assertRaises(ValueError):
                cp.CarryBook(path, costs="taker")

    def test_missing_coin_is_kept_and_marked_flat(self):
        with tempfile.TemporaryDirectory() as d:
            b = cp.CarryBook(Path(d) / "b.db", costs="maker", initial=500.0)
            b.on_hour(H, self.rows())
            eq_before = b.equity(self.rows())
            b.on_hour(2 * H, {})                                        # coin absent this hour
            self.assertEqual(len(b.open_positions()), 1)
            self.assertAlmostEqual(b.equity({}), eq_before, places=6)
            b.close()

    def test_summary_counts_funding_and_drawdown(self):
        with tempfile.TemporaryDirectory() as d:
            b = cp.CarryBook(Path(d) / "b.db", costs="taker", initial=500.0)
            b.on_hour(H, self.rows())
            b.on_hour(2 * H, self.rows(f_ann=0.01))                     # funding_low -> closed
            s = b.summary()
            self.assertEqual((s["open"], s["closed"], s["hours"]), (0, 1, 2))
            self.assertGreater(s["fees"], 0)
            self.assertGreater(s["funding"], 0)
            b.close()


class TestLiveRows(unittest.TestCase):
    def test_settled_rows_builds_one_row_per_coin_at_the_latest_hour(self):
        T = 1_800_000_000 // H * H

        def fetch(body):
            if body["type"] == "fundingHistory":
                return [{"time": (T - k * H) * 1000, "fundingRate": "0.00002"}
                        for k in range(carry.LOOKBACK_H + 2, -1, -1)]
            if body["type"] == "candleSnapshot":
                return [{"t": (T - k * H) * 1000, "o": "1", "h": "1", "l": "1", "c": str(100 + k), "v": "1"}
                        for k in range(5, -1, -1)]
            raise AssertionError(body)

        def spot_fetch(product):
            return pd.DataFrame({"ts": [T - 2 * H, T - H], "close": [50.0, 51.0]})

        ts, rows = cp.settled_rows(["A", "B"], fetch=fetch, spot_fetch=spot_fetch, sleep=lambda s: None)
        self.assertEqual(ts, T)
        self.assertEqual(set(rows), {"A", "B"})
        r = rows["A"]
        self.assertAlmostEqual(r.funding, 2e-5)
        self.assertAlmostEqual(r.f_ann, 2e-5 * carry.HOURS_PER_YEAR)
        self.assertEqual(r.perp, 100.0)      # the candle opening at T (k=0)
        self.assertEqual(r.spot, 51.0)       # latest closed spot bar at or before T

    def test_coin_with_error_is_skipped(self):
        def fetch(body):
            raise RuntimeError("down")
        ts, rows = cp.settled_rows(["A"], fetch=fetch, spot_fetch=lambda p: None, sleep=lambda s: None)
        self.assertIsNone(ts)
        self.assertEqual(rows, {})


if __name__ == "__main__":
    unittest.main()
