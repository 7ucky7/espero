"""The aggr exploration: aggr's bar format, the spike rule, and the seal that keeps
July-October out of it."""
from __future__ import annotations

import gzip
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def load():
    spec = importlib.util.spec_from_file_location("aggr_explore", ROOT / "research" / "aggr_explore.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestAggr(unittest.TestCase):
    def setUp(self):
        self.a = load()

    def test_point_format(self):
        cols = ["time", "cbuy", "close", "csell", "high", "lbuy", "low", "lsell", "market", "open", "vbuy", "vsell"]
        payload = {"format": "point", "columns": {k: i for i, k in enumerate(cols)},
                   "results": [[1793260800, 5, 80034.1, 4, 80115.4, 338083.3, 79808.9, 185191.9,
                                "BINANCE_FUTURES:btcusdt", 79820, 2.4e8, 1.6e8]]}
        df = self.a.parse(payload)
        r = df.iloc[0]
        self.assertEqual((r["market"], r["lbuy"], r["lsell"], r["close"]),
                         ("BINANCE_FUTURES:btcusdt", 338083.3, 185191.9, 80034.1))
        self.assertTrue(self.a.parse({"columns": {}, "results": []}).empty)

    def test_markets(self):
        self.assertEqual(self.a.COINS["BTC"]["price"], ["BINANCE_FUTURES:btcusdt"])
        self.assertEqual(self.a.COINS["BTC"]["all"],
                         ["BINANCE_FUTURES:btcusdt", "BYBIT:BTCUSDT", "OKEX:BTC-USDT-SWAP"])
        self.assertEqual(self.a.COINS["SHIB"]["price"], ["OKEX:SHIB-USDT-SWAP"])

    def test_one_spike_per_cascade(self):
        idx = pd.date_range("2026-04-01", periods=400, freq="h", tz="UTC")
        df = pd.DataFrame({"volume": 1e6, "long": 0.0, "short": 0.0}, index=idx)
        for h in (100, 101, 103, 200):                  # a 4-hour cascade, then a separate one
            df.iloc[h, df.columns.get_loc("long")] = 5e4
        s = self.a.spikes(df, "long")
        self.assertEqual(list(s), [idx[100], idx[200]])

    def test_a_held_out_hour_cannot_reach_the_exploration(self):
        with tempfile.TemporaryDirectory() as d:
            for m in self.a.EXPLORE:
                (Path(d) / "explore").mkdir(exist_ok=True)
                t = int(pd.Timestamp(f"{m}-02", tz="UTC").timestamp()) if m != "2026-06" else \
                    int(pd.Timestamp("2026-07-01 01:00", tz="UTC").timestamp())
                csv = "time,market,open,high,low,close,vbuy,vsell,cbuy,csell,lbuy,lsell\n" \
                      f"{t},BINANCE_FUTURES:btcusdt,1,1,1,1,1,1,1,1,0,0\n"
                (Path(d) / "explore" / f"{m}.csv.gz").write_bytes(gzip.compress(csv.encode()))
            with mock.patch.object(self.a, "DATA", Path(d)), self.assertRaises(RuntimeError):
                self.a.load_explore()

    def test_the_seal_hashes_every_held_out_file(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "holdout").mkdir()
            (Path(d) / "holdout" / "2026-07.csv.gz").write_bytes(b"x")
            manifest = Path(d) / "m.json"
            with mock.patch.object(self.a, "DATA", Path(d)), mock.patch.object(self.a, "MANIFEST", manifest):
                self.a.seal()
            text = manifest.read_text()
        self.assertIn("2026-07.csv.gz", text)
        self.assertIn("2d711642b726b04401627ca9fbac32f5c8530fb1903cc4db02258717921a4881", text)   # sha256 of "x"

    def test_quiet_hours_are_never_spikes(self):
        idx = pd.date_range("2026-04-01", periods=400, freq="h", tz="UTC")
        df = pd.DataFrame({"volume": 1e6, "long": 0.0, "short": 0.0}, index=idx)
        self.assertEqual(len(self.a.spikes(df, "long")), 0)

    def test_event_returns_are_measured_from_the_spike_hours_close(self):
        idx = pd.date_range("2026-04-01", periods=200, freq="h", tz="UTC")
        close = np.full(200, 100.0)
        close[51:] = 101.0                              # after the spike at hour 50, +1%
        df = pd.DataFrame({"open": 100.0, "close": close, "volume": 1e6, "long": 0.0, "short": 0.0}, index=idx)
        df.iloc[50, df.columns.get_loc("long")] = 9e5
        ev = self.a.event_table({"BTC": df})
        e = ev[ev["side"] == "long"].iloc[0]
        self.assertEqual(e["t"], idx[50])
        self.assertAlmostEqual(e["r1"], np.log(1.01))
        self.assertAlmostEqual(e["r0"], 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
