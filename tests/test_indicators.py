"""Indicators may not read the future."""
from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from espero.indicators import add_indicators, macd, rsi


def frame(n: int = 400, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    idx = pd.date_range("2023-01-01", periods=n, freq="D", tz="UTC")
    return pd.DataFrame({
        "dt": idx, "open": close, "high": close * 1.01,
        "low": close * 0.99, "close": close, "volume": 1.0,
    })


class TestCausality(unittest.TestCase):
    def test_rsi_is_bounded(self):
        r = rsi(frame()["close"])
        self.assertTrue(r.between(0, 100).all())
        self.assertFalse(r.isna().any())

    def test_sma_matches_rolling_mean(self):
        df = add_indicators(frame())
        expected = df["close"].rolling(20).mean()
        pd.testing.assert_series_equal(df["sma20"], expected, check_names=False)

    def test_no_indicator_peeks(self):
        """Values at bar i must be identical whether or not the future exists."""
        df = frame()
        full = add_indicators(df)
        for i in (120, 250, 399):
            head = add_indicators(df.iloc[: i + 1])
            for col in ("sma50", "rsi14", "bb_lo", "macd_hist"):
                a, b = full[col].iloc[i], head[col].iloc[i]
                if pd.isna(a) and pd.isna(b):
                    continue
                self.assertAlmostEqual(float(a), float(b), places=10, msg=f"{col} at {i}")

    def test_macd_hist_flips_sign(self):
        _, _, hist = macd(frame()["close"])
        self.assertTrue((hist > 0).any() and (hist < 0).any())


if __name__ == "__main__":
    unittest.main(verbosity=2)
