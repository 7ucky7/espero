"""The numbers quoted in docs/AUDIT.md, pinned to the committed dataset.

If a change to the engine moves these, the audit's claims are no longer true
and either the change or the document is wrong. That is the point.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from espero import data
from espero.backtest import Config, run

ROOT = Path(__file__).resolve().parents[1]
CSV = ROOT / "data" / "BTCUSD_86400s.csv"


@unittest.skipUnless(CSV.exists(), "committed BTC-USD data missing")
class TestAuditNumbers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.df = data.load(CSV)

    def m(self, **kw):
        return run(self.df, Config(**kw)).metrics()

    def test_dataset_shape(self):
        self.assertGreater(len(self.df), 1400)
        self.assertEqual(self.df["dt"].is_monotonic_increasing, True)

    def test_look_ahead_helps_by_a_lot(self):
        coded = self.m(timing="same_bar", fee=0.001, sizing="full")
        honest = self.m(timing="next_bar", fee=0.001, sizing="full")
        self.assertGreater(coded["total_return_pct"] - honest["total_return_pct"], 20.0)

    def test_real_fees_turn_it_negative(self):
        honest_cheap = self.m(timing="next_bar", fee=0.001, sizing="full")
        honest_real = self.m(timing="next_bar", fee=0.006, sizing="full")
        self.assertGreater(honest_cheap["total_return_pct"], honest_real["total_return_pct"])
        self.assertLess(honest_real["total_return_pct"], 0.0)

    def test_published_figures(self):
        cases = {
            "as coded, 2% notional, 10bps": (
                dict(timing="same_bar", fee=0.001, sizing="risk2pct"), -0.15, 1.0),
            "honest, 100% size, 10bps": (
                dict(timing="next_bar", fee=0.001, sizing="full"), 5.23, 1.5),
            "as coded, 100% size, 10bps": (
                dict(timing="same_bar", fee=0.001, sizing="full"), 42.95, 1.5),
            "honest, 100% size, 60bps": (
                dict(timing="next_bar", fee=0.006, sizing="full"), -29.07, 2.0),
        }
        for label, (kw, expected, tol) in cases.items():
            with self.subTest(label):
                got = self.m(**kw)["total_return_pct"]
                self.assertAlmostEqual(got, expected, delta=tol,
                                       msg=f"{label}: got {got:.2f}%, expected {expected}%")


if __name__ == "__main__":
    unittest.main(verbosity=2)
