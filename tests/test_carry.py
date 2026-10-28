"""Funding carry engine: the money is traceable, the rule is the pre-registered one."""
from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from espero import carry
from espero.paper import funding_due


def hours(n: int, start: str = "2025-01-01") -> pd.DatetimeIndex:
    return pd.date_range(start, periods=n, freq="h", tz="UTC")


def coin(n: int, rate: float, price: float = 100.0, basis: float = 0.0,
         drift: float = 0.0) -> carry.CoinData:
    idx = hours(n)
    px = price * (1 + drift) ** np.arange(n)
    return carry.CoinData(funding=pd.Series(rate, index=idx),
                          perp=pd.Series(px + basis, index=idx),
                          spot=pd.Series(px, index=idx))


HOURLY_20PCT = 0.20 / carry.HOURS_PER_YEAR


class TestRule(unittest.TestCase):
    def test_negative_funding_never_enters(self):
        res = carry.simulate({"A": coin(1000, -HOURLY_20PCT)})
        self.assertEqual(res.trades, [])
        self.assertAlmostEqual(res.equity.iloc[-1], 1.0)

    def test_idle_market_rate_does_not_qualify(self):
        # 0.01% per 8h ≈ 10.95% annualised, below the 15% entry threshold
        res = carry.simulate({"A": coin(1000, 0.0001 / 8)})
        self.assertEqual(res.trades, [])

    def test_enters_after_one_week_of_qualifying_funding(self):
        res = carry.simulate({"A": coin(500, HOURLY_20PCT)})
        self.assertEqual(len(res.trades), 1)
        t = res.trades[0]
        self.assertEqual(t["entry"], hours(500)[carry.LOOKBACK_H - 1])
        self.assertEqual(t["reason"], "end")

    def test_exits_when_funding_drops_below_five_percent(self):
        idx = hours(1000)
        rate = pd.Series(HOURLY_20PCT, index=idx)
        rate.iloc[400:] = 0.0
        cd = carry.CoinData(funding=rate, perp=pd.Series(100.0, index=idx),
                            spot=pd.Series(100.0, index=idx))
        res = carry.simulate({"A": cd})
        self.assertEqual(len(res.trades), 1)
        self.assertEqual(res.trades[0]["reason"], "funding_low")
        # trailing-week mean falls under 5% once 3/4 of the window is zero
        self.assertGreater(res.trades[0]["exit"], idx[400])
        self.assertLess(res.trades[0]["exit"], idx[400 + carry.LOOKBACK_H])

    def test_time_stop_at_thirty_days_then_requalifies(self):
        n = carry.LOOKBACK_H + 2 * carry.MAX_HOLD_H + 10
        res = carry.simulate({"A": coin(n, HOURLY_20PCT)})
        self.assertEqual([t["reason"] for t in res.trades][:2], ["time", "time"])
        self.assertEqual(res.trades[0]["hours"], carry.MAX_HOLD_H)

    def test_at_most_five_coins_the_highest_funding(self):
        coins = {f"C{k}": coin(400, HOURLY_20PCT * (1 + k / 10)) for k in range(8)}
        res = carry.simulate(coins)
        opened = {t["coin"] for t in res.trades}
        self.assertEqual(opened, {"C3", "C4", "C5", "C6", "C7"})


class TestMoney(unittest.TestCase):
    def test_hedged_position_earns_funding_minus_costs_only(self):
        # flat prices, constant 20% funding, one coin, held once (under the 30-day stop)
        n = 600
        res = carry.simulate({"A": coin(n, HOURLY_20PCT)}, initial=1.0)
        held_h = n - carry.LOOKBACK_H
        notional = 0.5   # equity / (2 × 1)
        expected_funding = notional * HOURLY_20PCT * held_h
        rt_cost = notional * 2 * (carry.SPOT_FEES["binanceus"] + carry.PERP_FEE + 2 * carry.SLIPPAGE)
        self.assertAlmostEqual(res.funding_received, expected_funding, places=6)
        self.assertAlmostEqual(res.fees, rt_cost, places=6)
        self.assertAlmostEqual(res.equity.iloc[-1], 1.0 + expected_funding - rt_cost, places=6)

    def test_price_moves_do_not_move_equity_when_basis_is_zero(self):
        res = carry.simulate({"A": coin(600, HOURLY_20PCT, drift=0.001)})
        t = res.trades[0]
        self.assertAlmostEqual(t["basis"], 0.0, places=9)

    def test_basis_narrowing_is_a_gain_for_the_short_perp(self):
        idx = hours(600)
        spot = pd.Series(100.0, index=idx)
        perp = pd.Series(101.0, index=idx)
        perp.iloc[300:] = 100.0            # premium collapses while held
        cd = carry.CoinData(funding=pd.Series(HOURLY_20PCT, index=idx), perp=perp, spot=spot)
        res = carry.simulate({"A": cd})
        self.assertGreater(res.trades[0]["basis"], 0)
        self.assertAlmostEqual(res.trades[0]["basis"], 0.5 / 101.0 * 1.0, places=6)

    def test_funding_paid_is_tracked_separately(self):
        idx = hours(600)
        rate = pd.Series(HOURLY_20PCT, index=idx)
        rate.iloc[300:320] = -HOURLY_20PCT   # 20 negative hours; trailing mean stays > 5%
        cd = carry.CoinData(funding=rate, perp=pd.Series(100.0, index=idx),
                            spot=pd.Series(100.0, index=idx))
        res = carry.simulate({"A": cd})
        self.assertAlmostEqual(res.funding_paid, 0.5 * HOURLY_20PCT * 20, places=9)
        self.assertEqual(len(res.trades), 1)

    def test_kraken_fees_cost_more(self):
        coins = {"A": coin(600, HOURLY_20PCT)}
        m = carry.evaluate(coins)
        self.assertLess(m["ann_return_kraken"], m["ann_return"])


class TestVerdict(unittest.TestCase):
    def test_all_five_or_fail(self):
        good = {"ann_return": 0.12, "max_dd": 0.01, "sharpe": 3.0, "paid_ratio": 0.1,
                "ann_return_kraken": 0.08}
        self.assertTrue(all(r["met"] for r in carry.verdict(good)))
        bad = dict(good, ann_return_kraken=0.03)
        self.assertEqual([r["met"] for r in carry.verdict(bad)], [True, True, True, True, False])

    def test_scan_annualises_hourly_funding(self):
        ctxs = [{"coin": "A", "mark": 1.0, "funding": 1e-5, "open_interest": 2e6, "day_volume": 1e6},
                {"coin": "B", "mark": 1.0, "funding": 2e-5, "open_interest": 1e6, "day_volume": 1e6}]
        df = carry.scan(ctxs, top=1)
        self.assertEqual(list(df["coin"]), ["A"])
        self.assertAlmostEqual(df["funding_ann"].iloc[0], 1e-5 * 8760)

    def test_from_frames_needs_ninety_days(self):
        f = pd.DataFrame({"ts": range(0, 3600 * 100, 3600), "funding": 0.0})
        self.assertIsNone(carry.from_frames(f, pd.DataFrame(), pd.DataFrame()))


class TestHourlyFunding(unittest.TestCase):
    def test_hourly_period_prorates_the_8h_rate(self):
        # one 8h window, rate 0.01% per 8h: eight hourly settlements sum to one 8h charge
        eight = funding_due(0, 8 * 3600, 0, 1000.0, 1e-4)
        hourly = funding_due(0, 8 * 3600, 0, 1000.0, 1e-4, period=3600)
        self.assertAlmostEqual(eight, hourly)
        self.assertAlmostEqual(funding_due(0, 3600, 0, 1000.0, 1e-4, period=3600), eight / 8)


if __name__ == "__main__":
    unittest.main()
