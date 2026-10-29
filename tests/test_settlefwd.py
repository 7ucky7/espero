"""#38: #33's measure at 00/08/16 UTC on recorded bars and archive funding (scaled to
8 hours), shorts-paying bucketed, and the criteria's signs."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from espero import settlefwd as sf
from tests.test_fundsplit import fake_get, month_zip
from tests.test_postclose import record

T0 = int(pd.Timestamp("2026-11-03", tz="UTC").timestamp())     # a Tuesday


def flat(first, last, price=100.0):
    ts = np.arange(int(pd.Timestamp(first, tz="UTC").timestamp()), int(pd.Timestamp(last, tz="UTC").timestamp()), 300)
    return pd.DataFrame({"open": price, "high": price, "low": price, "close": price, "volume": 1.0},
                        index=pd.Index(ts, name="ts"))


class TestLedger(unittest.TestCase):
    def test_a_fall_after_a_shorts_paying_08_00(self):
        b = flat("2026-11-02", "2026-11-05")
        b.loc[b.index >= T0 + 8 * 3600 + 600, ["open", "high", "low", "close"]] = 99.8     # -20 bps from 08:10
        rates = [(T0 + 8 * 3600 + 2, 8, -0.0007), (T0, 8, 0.0001), (T0 + 16 * 3600, 4, -0.0003)]
        with tempfile.TemporaryDirectory() as bars, tempfile.TemporaryDirectory() as fund:
            record(Path(bars) / "BTCUSDT", b)
            ev = sf.ledger(Path(bars), Path(fund), coins=("BTC",), now=pd.Timestamp("2026-11-20", tz="UTC"),
                           get=fake_get({"2026-11": month_zip(rates)}))
        ev = ev.set_index("hour")
        self.assertEqual(ev.loc[8, "bucket"], "shorts pay")
        self.assertAlmostEqual(ev.loc[8, "m30"], 99.8 / 100 - 1)
        self.assertEqual(ev.loc[0, "bucket"], "normal")
        self.assertEqual(ev.loc[16, "bucket"], "shorts pay")      # -0.03% a 4-hour period is -0.06% per 8 hours


def frame(sp, nm, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for d in pd.date_range(sf.FORWARD_FROM, sf.FORWARD_TO):
        for bucket, mu in (("shorts pay", sp), ("normal", nm), ("longs pay", 0.01)):
            rows.append({"day": d.strftime("%Y-%m-%d"), "bucket": bucket, "m30": mu + rng.normal(0, 0.001)})
    return pd.DataFrame(rows)


class TestCriteria(unittest.TestCase):
    def test_all_four(self):
        self.assertEqual([c["met"] for c in sf.criteria(frame(-0.003, 0.0))], [True, True, True, True])

    def test_real_but_small(self):
        self.assertEqual([c["met"] for c in sf.criteria(frame(-0.001, 0.0))], [True, True, True, False])

    def test_the_same_fall_everywhere(self):
        self.assertFalse(sf.criteria(frame(-0.003, -0.004))[1]["met"])


if __name__ == "__main__":
    unittest.main()
