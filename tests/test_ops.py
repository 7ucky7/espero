"""Every time-series operator is causal: its value on day t is identical when
the panel is cut off at day t. Every cross-sectional operator acts on one
row at a time."""
from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from espero import ops


def panel(n=120, k=6, seed=0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    px = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, size=(n, k)), axis=0))
    return pd.DataFrame(px, index=idx, columns=[f"A{i}" for i in range(k)])


class TestCausality(unittest.TestCase):
    def check(self, fn, *args, cut=80):
        full = fn(*args)
        head = fn(*(a.iloc[:cut] if isinstance(a, pd.DataFrame) else a for a in args))
        a = full.iloc[cut - 1].to_numpy(dtype=float)
        b = head.iloc[cut - 1].to_numpy(dtype=float)
        np.testing.assert_allclose(a, b, rtol=1e-12, atol=1e-12, equal_nan=True)
        self.assertFalse(np.isnan(b).all(), f"{fn.__name__} is all-NaN at the cut")

    def test_ts_operators_do_not_peek(self):
        p = panel()
        v = panel(seed=1)
        for fn, args in [
            (ops.ts_delay, (p, 3)), (ops.ts_delta, (p, 3)), (ops.ts_sum, (p, 5)),
            (ops.ts_mean, (p, 5)), (ops.ts_std, (p, 5)), (ops.ts_min, (p, 5)),
            (ops.ts_max, (p, 5)), (ops.ts_argmax, (p, 7)), (ops.ts_argmin, (p, 7)),
            (ops.ts_rank, (p, 10)), (ops.ts_zscore, (p, 10)), (ops.ts_corr, (p, v, 10)),
            (ops.ts_cov, (p, v, 10)), (ops.decay_linear, (p, 5)), (ops.returns, (p, 1)),
            (ops.log_returns, (p, 3)),
        ]:
            with self.subTest(op=fn.__name__):
                self.check(fn, *args)

    def test_windows_need_the_full_history(self):
        p = panel()
        self.assertTrue(ops.ts_mean(p, 20).iloc[:19].isna().all().all())
        self.assertFalse(ops.ts_mean(p, 20).iloc[19].isna().any())


class TestTimeSeriesSemantics(unittest.TestCase):
    def test_ts_rank_is_one_at_a_window_high(self):
        p = pd.DataFrame({"A": [1, 2, 3, 4, 5]}, index=pd.date_range("2024-01-01", periods=5))
        self.assertAlmostEqual(float(ops.ts_rank(p, 5).iloc[-1, 0]), 1.0)

    def test_decay_linear_weights_the_newest_most(self):
        p = pd.DataFrame({"A": [0, 0, 0, 1]}, index=pd.date_range("2024-01-01", periods=4))
        # weights 1,2,3,4 / 10 -> the last observation carries 0.4
        self.assertAlmostEqual(float(ops.decay_linear(p, 4).iloc[-1, 0]), 0.4)

    def test_ts_argmax_counts_days_since_the_high(self):
        p = pd.DataFrame({"A": [1, 9, 2, 3, 4]}, index=pd.date_range("2024-01-01", periods=5))
        self.assertEqual(float(ops.ts_argmax(p, 5).iloc[-1, 0]), 3.0)


class TestCrossSection(unittest.TestCase):
    def test_cs_rank_is_within_the_row(self):
        p = panel()
        r = ops.cs_rank(p)
        self.assertTrue(((r > 0) & (r <= 1)).all().all())
        row = p.iloc[10]
        self.assertEqual(r.iloc[10].idxmax(), row.idxmax())

    def test_cs_zscore_rows_have_zero_mean_unit_std(self):
        z = ops.cs_zscore(panel())
        np.testing.assert_allclose(z.mean(axis=1), 0, atol=1e-12)
        np.testing.assert_allclose(z.std(axis=1), 1, atol=1e-12)

    def test_cs_scale_sums_abs_to_one(self):
        s = ops.cs_scale(ops.cs_demean(panel()))
        np.testing.assert_allclose(s.abs().sum(axis=1), 1, atol=1e-12)

    def test_winsorize_clips_the_outlier_not_the_rest(self):
        p = pd.DataFrame([[1.0, 1.1, 0.9, 1.05, 0.95, 50.0]],
                         columns=list("ABCDEF"), index=[pd.Timestamp("2024-01-01")])
        w = ops.winsorize_mad(p, k=3)
        self.assertLess(float(w.loc[:, "F"].iloc[0]), 50.0)
        for c in "ABCDE":
            self.assertAlmostEqual(float(w.loc[:, c].iloc[0]), float(p.loc[:, c].iloc[0]))

    def test_neutralize_removes_the_explained_part(self):
        rng = np.random.default_rng(3)
        idx = pd.date_range("2024-01-01", periods=30, freq="D")
        cols = [f"A{i}" for i in range(20)]
        size = pd.DataFrame(rng.normal(size=(30, 20)), index=idx, columns=cols)
        noise = pd.DataFrame(rng.normal(size=(30, 20)), index=idx, columns=cols)
        factor = 2.0 * size + 0.1 * noise
        resid = ops.cs_neutralize(factor, size)
        # per-row correlation with the exposure is gone
        for dt in idx[:5]:
            c = np.corrcoef(resid.loc[dt], size.loc[dt])[0, 1]
            self.assertAlmostEqual(c, 0.0, places=8)

    def test_neutralize_leaves_missing_assets_missing(self):
        idx = pd.date_range("2024-01-01", periods=2, freq="D")
        f = pd.DataFrame([[1.0, 2.0, np.nan, 4.0], [1.0, 2.0, 3.0, 4.0]], index=idx, columns=list("ABCD"))
        e = pd.DataFrame([[1.0, 2.0, 3.0, 5.0], [2.0, 1.0, 4.0, 3.0]], index=idx, columns=list("ABCD"))
        r = ops.cs_neutralize(f, e)
        self.assertTrue(np.isnan(r.iloc[0]["C"]))
        self.assertFalse(np.isnan(r.iloc[1]["C"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
