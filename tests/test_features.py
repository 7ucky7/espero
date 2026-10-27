"""Features may not be clairvoyant."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from espero import features
from espero.indicators import add_indicators
from espero.signals import signals_at


def bars(ts_list):
    return pd.DataFrame({
        "ts": ts_list,
        "dt": pd.to_datetime(ts_list, unit="s", utc=True),
        "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1.0,
    })


class TestPointInTime(unittest.TestCase):
    def test_feature_cannot_be_used_before_it_existed(self):
        b = bars([0, 3600, 7200])
        f = pd.DataFrame({"ts": [3600], "funding": [0.0001]})
        out = features.attach(b, f, "funding", "funding", lag_seconds=3600)
        # the 3600 bar looks back to 0 -> the 3600 feature is not visible yet
        self.assertTrue(pd.isna(out.loc[out["ts"] == 3600, "funding"]).iloc[0])
        # the 7200 bar looks back to 3600 -> now it is
        self.assertAlmostEqual(float(out.loc[out["ts"] == 7200, "funding"].iloc[0]), 0.0001)

    def test_zero_lag_still_refuses_exact_matches(self):
        b = bars([3600])
        f = pd.DataFrame({"ts": [3600], "funding": [0.5]})
        out = features.attach(b, f, "funding", "funding", lag_seconds=0)
        self.assertTrue(pd.isna(out["funding"].iloc[0]))

    def test_zscore_does_not_peek(self):
        s = pd.DataFrame({"ts": range(200), "funding": np.sin(np.arange(200) / 7)})
        full = features.zscore(s, "funding", window=50)
        head = features.zscore(s.iloc[:150].copy(), "funding", window=50)
        self.assertAlmostEqual(float(full["funding_z"].iloc[149]),
                               float(head["funding_z"].iloc[149]), places=10)


class TestStore(unittest.TestCase):
    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "f.db"
            df = pd.DataFrame({"ts": [1, 2, 3], "funding": [0.1, 0.2, 0.3]})
            n = features.save(path, "test", df, "funding")
            self.assertEqual(n, 3)
            back = features.load(path, "test")
            self.assertEqual(len(back), 3)
            self.assertAlmostEqual(float(back["value"].iloc[-1]), 0.3)

    def test_missing_name_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(features.load(Path(tmp) / "f.db", "nope").empty)


class TestFundingSignal(unittest.TestCase):
    def _row(self, funding_z):
        n = 60  # sma50 must be finite or signals_at returns early
        base = add_indicators(pd.DataFrame({
            "dt": pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC"),
            "open": [100.0] * n, "high": [101.0] * n,
            "low": [99.0] * n, "close": [100.0] * n, "volume": [1.0] * n,
        }))
        base["funding_z"] = funding_z
        return base.iloc[-1], base.iloc[-2]

    def test_extreme_negative_funding_is_a_buy(self):
        row, prev = self._row(-2.5)
        sides = [(s.side, s.strategy) for s in signals_at(row, prev)]
        self.assertIn(("BUY", "funding"), sides)

    def test_extreme_positive_funding_is_a_sell(self):
        row, prev = self._row(2.5)
        sides = [(s.side, s.strategy) for s in signals_at(row, prev)]
        self.assertIn(("SELL", "funding"), sides)

    def test_without_the_column_nothing_changes(self):
        row, prev = self._row(np.nan)
        sides = [s.strategy for s in signals_at(row, prev)]
        self.assertNotIn("funding", sides)


if __name__ == "__main__":
    unittest.main(verbosity=2)
