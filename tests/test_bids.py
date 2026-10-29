"""#30's resting bid: it fills only when the price trades through it, at its own price,
never takes its profit inside the fill bar, pays maker or taker costs by how it exits,
rests one hour only, and is compared with #20's trade on the same event."""
from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from espero import bids as bd
from espero import liq as lq
from espero import lows as lw
from tests.test_liq import at, plant_up, quiet
from tests.test_lows import flipped

D0 = int(pd.Timestamp("2026-05-12", tz="UTC").timestamp())     # inside the window, not one of #18's days
T = at(10, day=D0)                                               # the trigger bar's open
DAY = "2026-05-12"


def planted():
    """#20's breakdown at bar T, then flat. Returns the bars, the trigger close and its ATR."""
    b = flipped(plant_up(quiet(day_start=D0), T))
    f = lq.triggers(b)
    assert f.loc[T, "down"]
    return b, float(f.loc[T, "close"]), float(f.loc[T, "atr"])


def path(b, bars, rest):
    """The bars after the trigger: `bars` as (open, high, low, close), then flat at `rest`."""
    b = b.copy()
    after = b.index[b.index > T]
    for t, ohlc in zip(after, bars):
        b.loc[t, ["open", "high", "low", "close"]] = ohlc
    for t in after[len(bars):]:
        b.loc[t, ["open", "high", "low", "close"]] = rest
    return b


def one(b, **kw):
    ev = bd.events(b, skip=set(), first=DAY, last=DAY, **kw)
    assert len(ev) == 1, ev
    return ev.iloc[0]


class TestFills(unittest.TestCase):
    def setUp(self):
        self.b, self.c, self.atr = planted()
        self.bid = self.c - self.atr

    def test_a_fill_then_the_target(self):
        c, bid = self.c, self.bid
        b = path(self.b, [(c, c, bid - 0.05, bid + 0.01), (bid + 0.01, c + 0.05, bid, c)], c)
        r = one(b)
        self.assertTrue(r["filled"])
        self.assertEqual(r["exit"], "target")
        self.assertAlmostEqual(r["gross"], c / bid - 1)
        self.assertAlmostEqual(r["net"], c / bid - 1 - 2 * bd.MAKER)
        self.assertAlmostEqual(r["value"], r["net"])

    def test_a_touch_is_not_a_fill(self):
        c, bid = self.c, self.bid
        b = path(self.b, [(c, c, bid * (1 - 0.00005), c)], c)       # half a bp through: the queue may not get there
        r = one(b)
        self.assertFalse(r["filled"])
        self.assertEqual(r["value"], 0.0)

    def test_never_the_target_inside_the_fill_bar(self):
        c, bid = self.c, self.bid
        mid = (bid + c) / 2
        b = path(self.b, [(c, c + 0.05, bid - 0.05, mid)], mid)       # through the bid and above the target, same bar
        r = one(b)
        self.assertEqual(r["exit"], "timeout")
        self.assertAlmostEqual(r["net"], mid / bid - 1 - (bd.MAKER + bd.TAKER + bd.SLIP))

    def test_the_target_needs_a_trade_through_too(self):
        c, bid = self.c, self.bid
        b = path(self.b, [(c, c, bid - 0.05, bid), (bid, c, bid, bid + 0.1)], bid + 0.1)   # reaches C, not past it
        self.assertEqual(one(b)["exit"], "timeout")

    def test_the_timeout_pays_a_taker(self):
        c, bid = self.c, self.bid
        b = path(self.b, [(c, c, bid - 0.05, bid - 0.5)], bid - 0.5)  # filled, then keeps falling
        r = one(b)
        self.assertEqual(r["exit"], "timeout")
        self.assertAlmostEqual(r["net"], (bid - 0.5) / bid - 1 - (bd.MAKER + bd.TAKER + bd.SLIP))
        self.assertLess(r["net"], 0)

    def test_the_bid_rests_one_hour_only(self):
        c, bid = self.c, self.bid
        bars = [(c, c, c, c)] * bd.LIFE + [(c, c, bid - 0.5, bid - 0.5)]   # through the bid in the 13th bar
        r = one(path(self.b, bars, bid - 0.5))
        self.assertFalse(r["filled"])

    def test_a_fill_on_the_last_bar_of_its_life(self):
        c, bid = self.c, self.bid
        bars = [(c, c, c, c)] * (bd.LIFE - 1) + [(c, c, bid - 0.05, bid)]
        self.assertTrue(one(path(self.b, bars, c))["filled"])

    def test_the_taker_baseline_is_20s_trade(self):
        c, bid = self.c, self.bid
        b = path(self.b, [(c - 0.2, c, bid - 0.05, bid)], c + 0.3)
        r = one(b)
        ref = lw.events(b, "down", skip=set(), first=DAY, last=DAY).iloc[0]
        self.assertAlmostEqual(r["r60"], ref["r60"])
        self.assertAlmostEqual(r["taker_net"], ref["r60"] - 2 * (bd.TAKER + bd.SLIP))

    def test_a_gap_drops_the_event(self):
        b = self.b.drop(T + 20 * bd.BAR_S)
        r = one(b)
        self.assertFalse(r["complete"])
        self.assertTrue(np.isnan(r["value"]))

    def test_the_depth_is_one_atr(self):
        self.assertAlmostEqual(one(self.b)["depth"], self.atr / self.c)


def frame(fill_net: float, taker: float, coins: int = 10, seed: int = 0) -> pd.DataFrame:
    """Every day of the window, each coin one event: half filled at fill_net, half not."""
    rng = np.random.default_rng(seed)
    out = []
    for d in pd.date_range(bd.FIRST_DAY, bd.LAST_DAY):
        for k in range(coins):
            filled = (d.day + k) % 2 == 0
            net = fill_net + rng.normal(0, 0.0005) if filled else np.nan
            out.append({"day": d.strftime("%Y-%m-%d"), "coin": f"C{k}", "complete": True, "filled": filled,
                        "net": net, "value": net if filled else 0.0, "taker_net": taker + rng.normal(0, 0.0005)})
    return pd.DataFrame(out)


class TestCriteria(unittest.TestCase):
    def test_all_four(self):
        crit = bd.criteria(frame(0.002, -0.001))
        self.assertEqual([c["met"] for c in crit], [True, True, True, True])
        self.assertEqual(bd.verdict(crit), "PASS")

    def test_pays_but_no_better_than_taking(self):
        crit = bd.criteria(frame(0.002, 0.004))
        self.assertEqual([c["met"] for c in crit], [True, False, True, True])
        self.assertEqual(bd.verdict(crit), "FAIL (it pays, but no better than taking)")

    def test_under_the_floor_fails(self):
        crit = bd.criteria(frame(0.0003, -0.001))
        self.assertFalse(crit[0]["met"])
        self.assertEqual(bd.verdict(crit), "FAIL")

    def test_one_half_only(self):
        f = frame(0.002, -0.001)
        f.loc[(f["day"] >= bd.HALF) & f["filled"], "net"] = -0.002
        self.assertFalse(bd.criteria(f)[2]["met"])

    def test_one_coin_carrying_it(self):
        f = frame(-0.001, -0.002)
        f.loc[(f["coin"] == "C0") & f["filled"], "net"] = 0.05
        self.assertFalse(bd.criteria(f)[3]["met"])

    def test_incomplete_events_do_not_count(self):
        f = frame(0.002, -0.001)
        extra = f.iloc[:50].assign(complete=False, net=-1.0, value=-1.0)
        self.assertEqual([c["actual"] for c in bd.criteria(pd.concat([f, extra]))],
                         [c["actual"] for c in bd.criteria(f)])


if __name__ == "__main__":
    unittest.main()
