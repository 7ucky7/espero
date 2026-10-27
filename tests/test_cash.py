"""The cash policy must be explicable, bounded, and boring."""
from __future__ import annotations

import unittest

from espero import cash


class TestChoice(unittest.TestCase):
    def test_treasuries_beat_usdc_after_the_risk_penalty(self):
        d = cash.choose(300.0)
        self.assertEqual(d.vehicle, "SGOV")
        self.assertAlmostEqual(d.reserve, 30.0)
        self.assertAlmostEqual(d.amount, 270.0)
        self.assertIn("3.80% net", d.reason)

    def test_small_balances_stay_in_usd(self):
        d = cash.choose(20.0)          # below every minimum ticket after reserve
        self.assertEqual(d.vehicle, "USD")
        self.assertEqual(d.amount, 0.0)

    def test_high_threshold_means_no_sweep(self):
        d = cash.choose(300.0, min_edge=0.10)
        self.assertEqual(d.vehicle, "USD")
        self.assertIn("threshold", d.reason)

    def test_choice_is_auditable(self):
        d = cash.choose(300.0)
        names = dict(d.candidates)
        self.assertIn("SGOV", names)
        self.assertIn("USDC", names)
        self.assertGreater(names["SGOV"], names["USDC"])

    def test_negative_cash_is_safe(self):
        d = cash.choose(-50.0)
        self.assertEqual(d.vehicle, "USD")
        self.assertEqual(d.amount, 0.0)


class TestCarry(unittest.TestCase):
    def test_simple_accrual(self):
        # $300 at 4.3% for 30 days
        self.assertAlmostEqual(cash.carry(300.0, 0.043, 30), 300 * 0.043 * 30 / 365, places=10)

    def test_zero_days_or_rate(self):
        self.assertEqual(cash.carry(300.0, 0.043, 0), 0.0)
        self.assertEqual(cash.carry(300.0, 0.0, 30), 0.0)

    def test_negative_values_do_not_earn(self):
        self.assertEqual(cash.carry(-100.0, 0.043, 30), 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
