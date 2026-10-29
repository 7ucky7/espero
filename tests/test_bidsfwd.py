"""#31's forward ledger: #30's fill model with a 2-ATR bid and a 4-hour exit, rebuilt
from #24's recorded files, compared with #24's 4-hour trade, judged in its own halves."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from espero import bids as bd
from espero import bidsfwd as bf
from espero import liq as lq
from tests.test_liq import at, plant_up, quiet
from tests.test_lows import flipped
from tests.test_postclose import record

D1 = int(pd.Timestamp("2026-10-30", tz="UTC").timestamp())
T1 = at(10, day=D1)


def planted_path(fall_atr: float, back_to_close: bool):
    """#20's breakdown on the window's first day; then the price falls `fall_atr` ATRs under the
    close and either comes back above it or stays down."""
    b = flipped(plant_up(quiet(day_start=D1), T1))
    f = lq.triggers(b)
    c, a = float(f.loc[T1, "close"]), float(f.loc[T1, "atr"])
    low = c - fall_atr * a
    after = b.index[b.index > T1]
    b.loc[after[0], ["open", "high", "low", "close"]] = [c, c, low, low + 0.01]
    for k, t in enumerate(after[1:]):
        # back above the close at once, or a slow drift that stays under it (so 1 and 4 hours differ)
        b.loc[t, ["open", "high", "low", "close"]] = c + 0.2 if back_to_close else low + 0.01 + 0.001 * k
    return b, c, a


class TestLedger(unittest.TestCase):
    def test_a_deep_fill_from_recorded_files(self):
        b, c, a = planted_path(2.5, back_to_close=True)
        with tempfile.TemporaryDirectory() as tmp:
            record(Path(tmp) / "BTCUSDT", b)
            ev = bf.ledger(Path(tmp), coins=("BTC",))
        self.assertEqual(len(ev), 1)
        e = ev.iloc[0]
        self.assertEqual(e["day"], "2026-10-30")
        self.assertTrue(e["filled"])
        self.assertEqual(e["exit"], "target")
        bid = c - 2 * a
        self.assertAlmostEqual(e["net"], c / bid - 1 - 2 * bd.MAKER)
        self.assertAlmostEqual(e["depth"], 2 * a / c)

    def test_one_atr_down_does_not_reach_a_2_atr_bid(self):
        b, _, _ = planted_path(1.2, back_to_close=True)
        with tempfile.TemporaryDirectory() as tmp:
            record(Path(tmp) / "BTCUSDT", b)
            e = bf.ledger(Path(tmp), coins=("BTC",)).iloc[0]
        self.assertFalse(e["filled"])
        self.assertEqual(e["value"], 0.0)

    def test_held_four_hours_and_compared_with_24s_trade(self):
        b, c, a = planted_path(2.5, back_to_close=False)
        with tempfile.TemporaryDirectory() as tmp:
            record(Path(tmp) / "BTCUSDT", b)
            e = bf.ledger(Path(tmp), coins=("BTC",)).iloc[0]
        self.assertEqual(e["exit"], "timeout")
        f = lq.triggers(b)
        i = f.index.get_loc(T1)
        fill = f.index[i + 1]
        self.assertAlmostEqual(e["net"], f["close"].iloc[i + 1 + 48] / (c - 2 * a) - 1     # 48 bars: 4 hours
                               - (bd.MAKER + bd.TAKER + bd.SLIP))
        self.assertEqual(fill, T1 + bd.BAR_S)
        self.assertAlmostEqual(e["taker_net"], f["close"].iloc[i + 48] / f["open"].iloc[i + 1] - 1
                               - 2 * (bd.TAKER + bd.SLIP))

    def test_no_files_no_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(bf.ledger(Path(tmp)).empty)


class TestCriteria(unittest.TestCase):
    def test_its_own_halves(self):
        rng = np.random.default_rng(0)
        rows = []
        for d in pd.date_range(bf.FORWARD_FROM, bf.FORWARD_TO):
            for k in range(3):
                net = (0.002 if d.strftime("%Y-%m-%d") < bf.HALF else -0.002) + rng.normal(0, 0.0005)
                rows.append({"day": d.strftime("%Y-%m-%d"), "coin": f"C{k}", "complete": True, "filled": True,
                             "net": net, "value": net, "taker_net": -0.001})
        crit = bf.criteria(pd.DataFrame(rows))
        self.assertIn("(Oct-Dec)", crit[2]["actual"])
        self.assertIn("(Jan-Mar)", crit[2]["actual"])
        self.assertFalse(crit[2]["met"])


class TestRun(unittest.TestCase):
    def test_writes_the_ledger_and_says_it_decides_nothing(self):
        b, _, _ = planted_path(2.5, back_to_close=True)
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as state:
            record(Path(tmp) / "BTCUSDT", b)
            out = bf.run(Path(state), Path(tmp))
            self.assertTrue((Path(state) / bf.LEDGER).exists())
        self.assertIn("1 fills of 1 breakdowns", out["note"])
        self.assertIn("decides nothing", out["note"])
        self.assertIsNone(out["equity"])


if __name__ == "__main__":
    unittest.main()
