"""The #8 paper account must be research/multifactor.py's simulator, one day at a time."""
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from espero import mf
from espero import panel as pnl

ROOT = Path(__file__).resolve().parents[1]


def research_mf():
    spec = importlib.util.spec_from_file_location("multifactor", ROOT / "research" / "multifactor.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def synthetic(n_days: int = 560, n_coins: int = 16, seed: int = 3) -> pnl.MarketPanel:
    """Daily OHLCV with different vols and drifts, one coin listed late so the
    365-close eligibility rule bites, all liquid enough to be eligible."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2025-01-01", periods=n_days, freq="D")
    coins = [f"C{k:02d}" for k in range(n_coins)]
    vols = np.linspace(0.02, 0.07, n_coins)
    rets = rng.normal(0.0005, vols, size=(n_days, n_coins))
    close = pd.DataFrame(100 * np.exp(np.cumsum(rets, axis=0)), index=idx, columns=coins)
    open_ = close.shift(1) * np.exp(rng.normal(0, 0.003, size=close.shape))
    open_.iloc[0] = close.iloc[0]
    high = np.maximum(open_, close) * 1.01
    low = np.minimum(open_, close) * 0.99
    volume = pd.DataFrame(1e6, index=idx, columns=coins)
    late = coins[-1]
    for f in (close, open_, high, low, volume):
        f.loc[: idx[120], late] = np.nan
    return pnl.MarketPanel(open_, high, low, close, volume)


class TestFrozenRule(unittest.TestCase):
    def test_parameters_match_the_research_script(self):
        r = research_mf()
        self.assertEqual(mf.FACTORS, r.FACTORS)
        self.assertEqual((mf.TOP, mf.BUFFER, mf.TARGET_VOL, mf.MAX_SCALE, mf.COST),
                         (r.TOP, r.BUFFER, r.TARGET_VOL, r.MAX_SCALE, r.COST))

    def test_forward_window_is_26_mondays(self):
        self.assertEqual(mf.FORWARD_START.weekday(), 0)
        self.assertEqual(mf.FORWARD_END - mf.FORWARD_START, pd.Timedelta(weeks=26))


class TestEquivalence(unittest.TestCase):
    def test_day_by_day_matches_the_simulator(self):
        r = research_mf()
        p = synthetic()
        start, end = "2026-01-07", str(p.index[-1].date())   # a Wednesday: first fill is a Monday
        mask = pnl.eligible(p, min_history=365, min_dollar_volume=1e6)
        score = mf.factors.composite(p, mf.FACTORS, mask)
        sim, n_reb, _ = r.simulate(p, score, mask, start, end)
        self.assertGreater(n_reb, 20)

        with tempfile.TemporaryDirectory() as d:
            acc = mf.MFAccount(Path(d) / "mf.db", cash=1.0)
            live, fills = [], 0
            for day in sim.index:
                res = mf.step(acc, p.slice(None, day), start=pd.Timestamp(start), min_universe=0)
                fills += res["note"] == "rebalance"
                live.append(res["equity"])
            acc.close()
        self.assertEqual(fills, n_reb)
        np.testing.assert_allclose(live, sim.to_numpy(), rtol=1e-10)


class TestAccount(unittest.TestCase):
    def setUp(self):
        self.p = synthetic()
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "mf.db"

    def tearDown(self):
        self.dir.cleanup()

    def monday(self) -> pd.Timestamp:
        return [d for d in self.p.index if d.weekday() == 0][-3]

    def test_holds_cash_before_the_start(self):
        acc = mf.MFAccount(self.path, cash=100.0)
        res = mf.step(acc, self.p.slice(None, self.monday()), start=self.monday() + pd.Timedelta(days=7),
                      min_universe=0)
        self.assertEqual((res["note"], res["positions"], res["equity"]), ("mark", {}, 100.0))
        acc.close()

    def test_missed_monday_fills_late_at_the_latest_close(self):
        tuesday = self.monday() + pd.Timedelta(days=1)
        acc = mf.MFAccount(self.path, cash=100.0)
        res = mf.step(acc, self.p.slice(None, tuesday), start=self.monday(), min_universe=0)
        self.assertTrue(res["note"].startswith("rebalance (late"))
        self.assertEqual(res["decision"], str((self.monday() - pd.Timedelta(days=1)).date()))
        # filled at Tuesday's close, so the mark right after costs only the fee
        self.assertAlmostEqual(res["equity"], 100.0 - res["traded"] * mf.COST, places=9)
        again = mf.step(acc, self.p.slice(None, tuesday), start=self.monday(), min_universe=0)
        self.assertEqual((again["note"], again["traded"]), ("mark", 0.0))
        acc.close()

    def test_degraded_universe_does_not_trade(self):
        acc = mf.MFAccount(self.path, cash=100.0)
        res = mf.step(acc, self.p.slice(None, self.monday()), start=self.monday(), min_universe=30)
        self.assertTrue(res["note"].startswith("mark (degraded"))
        self.assertIsNone(res["decision"])
        acc.close()

    def test_vol_target_keeps_gross_under_100_and_resume(self):
        acc = mf.MFAccount(self.path, cash=100.0)
        res = mf.step(acc, self.p.slice(None, self.monday()), start=self.monday(), min_universe=0)
        self.assertEqual(res["note"], "rebalance")
        self.assertLessEqual(len(res["positions"]), mf.TOP)
        self.assertLessEqual(sum(res["weights"].values()), 1.0 + 1e-12)
        acc.save(res["ts"], res["equity"], res["weights"], res["positions"], 100.0, res["note"],
                 res["last_px"], res["traded"])
        acc.close()
        back = mf.MFAccount(self.path)
        self.assertEqual(back.decision, res["decision"])
        self.assertAlmostEqual(back.equity(pd.Series(res["last_px"])), res["equity"], places=9)
        back.close()

    def test_held_coin_without_a_price_is_marked_at_its_last(self):
        acc = mf.MFAccount(self.path, cash=0.0, units={"C01": 2.0}, last_px={"C01": 5.0})
        self.assertEqual(acc.equity(pd.Series({"C02": 1.0})), 10.0)
        acc.close()


if __name__ == "__main__":
    unittest.main()
