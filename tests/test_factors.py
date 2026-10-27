"""Panel, factor zoo, evaluation: causal masks, fixed signs, honest splits."""
from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from espero import factor_eval as fe
from espero import factors, ops, panel


def fake_fetch(coins, n=500, seed=0, end="2026-10-26", drift=None):
    rng = np.random.default_rng(seed)
    drift = drift or {}

    def fetch(symbol, span):
        c = symbol.replace("-USD", "")
        if c not in coins:
            raise KeyError(symbol)
        idx = pd.date_range(end=end, periods=n, freq="D", tz="UTC")
        r = rng.normal(drift.get(c, 0.0), 0.03, size=n)
        close = 100 * np.exp(np.cumsum(r))
        return pd.DataFrame({"dt": idx, "ts": idx.astype("int64") // 10**9,
                             "open": close * (1 - 0.001), "high": close * 1.01, "low": close * 0.99,
                             "close": close, "volume": rng.uniform(1e4, 1e6, size=n)})
    return fetch


COINS = [f"C{i:02d}" for i in range(24)]


def make_panel(**kw) -> panel.MarketPanel:
    return panel.build(COINS, fetch=fake_fetch(COINS, **kw))


class TestPanel(unittest.TestCase):
    def test_build_aligns_on_one_calendar_and_records_failures(self):
        p = panel.build(COINS + ["DEAD"], fetch=fake_fetch(COINS))
        self.assertEqual(len(p.coins), len(COINS))
        self.assertIn("DEAD", p.errors)
        self.assertEqual(p.close.shape[0], 500)
        self.assertEqual(p.dollar_volume.shape, p.close.shape)

    def test_eligibility_is_dated_not_static(self):
        p = make_panel()
        m = panel.eligible(p, min_history=365, min_dollar_volume=0)
        self.assertFalse(m.iloc[:364].any().any())
        self.assertTrue(m.iloc[-1].all())

    def test_eligibility_excludes_the_illiquid(self):
        p = make_panel()
        m = panel.eligible(p, min_history=10, min_dollar_volume=1e12)
        self.assertFalse(m.iloc[-1].any())

    def test_round_trip_through_csv(self):
        import tempfile
        p = make_panel()
        with tempfile.TemporaryDirectory() as d:
            p.save(d)
            q = panel.MarketPanel.load(d)
            self.assertTrue((Path(d) / "universe.csv").exists())
        pd.testing.assert_frame_equal(p.close, q.close, check_freq=False)


class TestFactorSigns(unittest.TestCase):
    def test_momentum_ranks_the_trending_coin_first(self):
        p = make_panel(drift={"C00": 0.05})
        f = factors.mom_30(p)
        self.assertEqual(f.iloc[-1].idxmax(), "C00")

    def test_momentum_skips_the_last_day(self):
        p = make_panel()
        f = factors.momentum(p, 30, 1)
        c = p.close
        expected = c.iloc[-2] / c.iloc[-32] - 1
        pd.testing.assert_series_equal(f.iloc[-1], expected, check_names=False)

    def test_lowvol_prefers_the_calm_coin(self):
        p = make_panel()
        c = p.close.copy()
        c["C01"] = 100.0 + np.arange(len(c)) * 0.01   # nearly flat
        q = panel.MarketPanel(p.open, p.high, p.low, c, p.volume)
        self.assertEqual(factors.lowvol_30(q).iloc[-1].idxmax(), "C01")

    def test_every_zoo_factor_is_causal(self):
        p = make_panel()
        cut = 400
        head = p.slice(end=p.index[cut - 1])
        for name, fn in factors.ZOO.items():
            with self.subTest(factor=name):
                a = fn(p).iloc[cut - 1].to_numpy(dtype=float)
                b = fn(head).iloc[-1].to_numpy(dtype=float)
                np.testing.assert_allclose(a, b, rtol=1e-10, atol=1e-12, equal_nan=True)

    def test_composite_is_a_rank_average(self):
        p = make_panel()
        comp = factors.composite(p, ["mom_30", "rev_3"])
        last = comp.iloc[-1].dropna()
        self.assertTrue(((last > 0) & (last <= 1)).all())
        manual = (ops.cs_rank(ops.winsorize_mad(factors.mom_30(p)))
                  + ops.cs_rank(ops.winsorize_mad(factors.rev_3(p)))) / 2
        pd.testing.assert_series_equal(comp.iloc[-1], manual.iloc[-1], check_names=False)


class TestEvaluation(unittest.TestCase):
    def test_perfect_foresight_has_ic_one_and_noise_has_none(self):
        p = make_panel()
        fwd = fe.forward_returns(p.close, 5)
        ic = fe.ic_series(fwd, fwd)
        self.assertAlmostEqual(float(ic.mean()), 1.0)
        rng = np.random.default_rng(1)
        noise = pd.DataFrame(rng.normal(size=p.close.shape), index=p.index, columns=p.coins)
        s = fe.summarize(fe.ic_series(noise, fwd))
        self.assertLess(abs(s.t), 3.0)

    def test_quantile_spread_is_positive_for_a_real_signal(self):
        p = make_panel()
        fwd = fe.forward_returns(p.close, 1)
        rng = np.random.default_rng(2)
        signal = fwd + pd.DataFrame(rng.normal(0, 0.05, size=fwd.shape), index=fwd.index, columns=fwd.columns)
        qr = fe.quantile_returns(signal, fwd, q=5)
        self.assertGreater(float(fe.spread(qr).mean()), 0)
        self.assertEqual(list(qr.columns), [1, 2, 3, 4, 5])

    def test_purged_split_leaves_a_gap(self):
        idx = pd.date_range("2024-01-01", periods=400, freq="D")
        splits = fe.purged_walk_forward(idx, n_splits=3, horizon=5, embargo=5, min_train=100)
        self.assertEqual(len(splits), 3)
        for train, test in splits:
            self.assertLess(train[-1], test[0])
            self.assertGreaterEqual((test[0] - train[-1]).days, 10)
        # test blocks tile the post-training period without overlap
        tests = [t for _, t in splits]
        for a, b in zip(tests, tests[1:]):
            self.assertLess(a[-1], b[0])
        self.assertEqual(tests[-1][-1], idx[-1])

    def test_deflated_sharpe_falls_with_more_trials(self):
        a = fe.deflated_sharpe(0.1, n_trials=1, n_obs=500)
        b = fe.deflated_sharpe(0.1, n_trials=50, n_obs=500)
        self.assertGreater(a, b)
        self.assertGreater(a, 0.9)

    def test_evaluate_table_has_every_factor_and_the_hurdle(self):
        p = make_panel()
        mask = panel.eligible(p, min_history=100, min_dollar_volume=0)
        t = fe.evaluate(p, names=["mom_30", "rev_3", "lowvol_30"], horizon=5, mask=mask,
                        n_splits=3, embargo=3)
        self.assertEqual(set(t.index), {"mom_30", "rev_3", "lowvol_30"})
        self.assertIn("t_oos", t.columns)
        self.assertEqual(t.attrs["n_trials"], 3)
        text = fe.format_table(t)
        self.assertIn("Harvey-Liu-Zhu", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
