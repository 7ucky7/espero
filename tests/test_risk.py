"""The risk gate is the last thing between a signal and money."""
from __future__ import annotations

import unittest

from espero.risk import RiskLimits, check_buy, check_sell, size_position


class TestSizing(unittest.TestCase):
    def test_risk_based_size_is_capped_by_position_limit(self):
        limits = RiskLimits(risk_per_trade=0.01, stop_pct=0.05, max_position_pct=0.25)
        # 1% of 500 = $5 risk -> $100 notional at a 5% stop
        self.assertAlmostEqual(size_position(500, 0.9, limits), 100.0)

    def test_position_cap_wins_when_stop_is_tight(self):
        limits = RiskLimits(risk_per_trade=0.05, stop_pct=0.01, max_position_pct=0.10)
        self.assertAlmostEqual(size_position(1_000, 0.9, limits), 100.0)

    def test_no_equity_no_size(self):
        self.assertEqual(size_position(0, 0.9, RiskLimits()), 0.0)


class TestGate(unittest.TestCase):
    def setUp(self):
        self.limits = RiskLimits()

    def test_blocks_second_position(self):
        d = check_buy(500, 500, open_positions=1, day_pnl=0, confidence=0.9,
                      limits=self.limits)
        self.assertFalse(d.allowed)
        self.assertIn("max open", d.reason)

    def test_blocks_after_daily_loss_cap(self):
        d = check_buy(500, 500, open_positions=0, day_pnl=-16.0, confidence=0.9,
                      limits=self.limits)
        self.assertFalse(d.allowed)
        self.assertIn("daily loss", d.reason)

    def test_allows_a_normal_trade(self):
        d = check_buy(500, 500, open_positions=0, day_pnl=0, confidence=0.9,
                      limits=self.limits)
        self.assertTrue(d.allowed)
        self.assertAlmostEqual(d.notional, 100.0)

    def test_blocks_when_cash_is_too_small(self):
        d = check_buy(500, 5, open_positions=0, day_pnl=0, confidence=0.9,
                      limits=self.limits)
        self.assertFalse(d.allowed)

    def test_sell_requires_a_position(self):
        self.assertFalse(check_sell(0).allowed)
        self.assertTrue(check_sell(1).allowed)


if __name__ == "__main__":
    unittest.main(verbosity=2)
