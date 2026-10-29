"""#29's forward ledger: #28's rows rebuilt from #24's recorded files on the window,
the reversal measured after 16:00 ET, and the four criteria's signs."""
from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from espero import levetf as lv
from espero import postclose as pc
from tests.test_lowsfwd import zipped

D = dt.date


def flat(first: str, last: str, price: float = 100.0) -> pd.DataFrame:
    ts = np.arange(int(pd.Timestamp(first, tz="UTC").timestamp()), int(pd.Timestamp(last, tz="UTC").timestamp()),
                   lv.BAR_S)
    return pd.DataFrame({"open": price, "high": price, "low": price, "close": price, "volume": 1.0},
                        index=pd.Index(ts, name="ts"))


def step(b: pd.DataFrame, t: int, price: float) -> None:
    b.loc[b.index >= t, ["open", "high", "low", "close"]] = price


def record(folder: Path, b: pd.DataFrame) -> None:
    """Save bars as #24's recorder does: one zip per UTC day."""
    folder.mkdir(parents=True)
    for day in sorted({pd.to_datetime(t, unit="s", utc=True).strftime("%Y-%m-%d") for t in b.index}):
        start = int(pd.Timestamp(day, tz="UTC").timestamp())
        (folder / f"{day}.zip").write_bytes(zipped(b[(b.index >= start) & (b.index < start + 86400)]))


class TestCalendar(unittest.TestCase):
    def test_2027_holidays_inside_the_window(self):
        for d in (D(2027, 1, 1), D(2027, 1, 18), D(2027, 2, 15), D(2027, 3, 26)):
            self.assertEqual(lv.kind(d), "closed", d)
        self.assertEqual(lv.kind(D(2027, 3, 31)), "trading")


class TestRows(unittest.TestCase):
    def test_a_reversal_after_the_close_from_recorded_files(self):
        d = D(2026, 10, 30)                       # a Friday, still summer time: 16:00 ET is 20:00 UTC
        b = flat("2026-10-29", "2026-11-01")
        step(b, lv.at(d, 12, 0), 101.0)
        step(b, lv.at(d, 16, 5), 100.5)           # gives back half the day after the close
        with tempfile.TemporaryDirectory() as tmp:
            record(Path(tmp) / "BTCUSDT", b)
            df = pc.rows(Path(tmp), coins=("BTC",))
        r = df[df["date"] == "2026-10-30"].iloc[0]
        self.assertEqual(r["kind"], "trading")
        self.assertAlmostEqual(r["r_post15"], 0.01)
        self.assertAlmostEqual(r["post15"], 100.5 / 101 - 1)
        self.assertEqual(df["date"].min(), "2026-10-30")      # the warm-up day is a reference only

    def test_no_files_no_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(pc.rows(Path(tmp)).empty)


def frame(post_tr: float, post_cl: float, post_big: float, seed: int = 0) -> pd.DataFrame:
    """BTC and ETH on the window: trading days at post_tr (post_big on every third date, |r| 3%),
    closed days at post_cl."""
    rng = np.random.default_rng(seed)
    out = []
    for coin in lv.PRIMARY:
        for d in lv.days(pc.FORWARD_FROM, pc.FORWARD_TO):
            k = lv.kind(d)
            if k == "early":
                continue
            big = k == "trading" and d.toordinal() % 3 == 0
            mu = post_big if big else (post_tr if k == "trading" else post_cl)
            out.append({"date": d.isoformat(), "coin": coin, "kind": k, "r_post15": 0.03 if big else 0.005,
                        "post15": mu + rng.normal(0, 0.0005)})
    return pd.DataFrame(out)


class TestCriteria(unittest.TestCase):
    def test_a_strong_reversal_passes(self):
        crit = pc.criteria(frame(-0.003, 0.0, -0.003))
        self.assertEqual([c["met"] for c in crit], [True, True, True, True])
        self.assertEqual(lv.verdict(crit), "PASS")

    def test_real_but_too_small(self):
        crit = pc.criteria(frame(-0.0006, 0.0, -0.0006))
        self.assertEqual([c["met"] for c in crit], [True, True, True, False])
        self.assertEqual(lv.verdict(crit), "real, not tradable after costs")

    def test_a_continuation_fails(self):
        crit = pc.criteria(frame(0.003, 0.0, 0.003))
        self.assertFalse(crit[0]["met"])
        self.assertEqual(lv.verdict(crit), "FAIL")

    def test_the_same_on_weekends_fails_criterion_2(self):
        self.assertFalse(pc.criteria(frame(-0.003, -0.004, -0.003))[1]["met"])

    def test_only_btc_and_eth_count(self):
        f = frame(-0.003, 0.0, -0.003)
        extra = f[f["coin"] == "BTC"].assign(coin="XRP", post15=0.05)
        self.assertEqual([c["actual"] for c in pc.criteria(pd.concat([f, extra]))],
                         [c["actual"] for c in pc.criteria(f)])

    def test_one_half_only_fails_criterion_3(self):
        f = frame(-0.003, 0.0, -0.003)
        f.loc[f["date"] >= pc.HALF, "post15"] = 0.001
        self.assertFalse(pc.criteria(f)[2]["met"])


class TestRun(unittest.TestCase):
    def test_writes_the_ledger_and_says_it_decides_nothing(self):
        d = D(2026, 10, 30)
        b = flat("2026-10-29", "2026-11-01")
        step(b, lv.at(d, 12, 0), 101.0)
        step(b, lv.at(d, 16, 5), 100.5)
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as state:
            record(Path(tmp) / "BTCUSDT", b)
            out = pc.run(Path(state), Path(tmp))
            self.assertTrue((Path(state) / pc.LEDGER).exists())
        self.assertIn("1 trading days", out["note"])
        self.assertIn("decides nothing", out["note"])
        self.assertIsNone(out["equity"])


if __name__ == "__main__":
    unittest.main()
