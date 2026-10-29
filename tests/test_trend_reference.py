"""#15's published numbers, pinned on the committed snapshot (data/trend/).

research/RESULTS_TREND.md reports the trend book from one pre-registered run.
This replays it offline: any later edit to espero/trend.py or the simulator
that moves those numbers fails here instead of quietly changing a result.
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "data" / "trend"


def research_trend():
    spec = importlib.util.spec_from_file_location("research_trend", ROOT / "research" / "trend.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@unittest.skipUnless((SNAPSHOT / "SPY.csv").exists(), "the #15 snapshot is not checked out")
class TestPublishedNumbers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = research_trend()
        cls.trend = cls.r.simulate(cls.r.load())

    def test_trend_book_headline(self):
        s = self.r.stats(self.trend)
        self.assertEqual(s["trades"], 3749)
        self.assertAlmostEqual(float(self.trend.equity.iloc[-1]), 1.75202378, places=7)
        self.assertAlmostEqual(s["cagr"], 0.065676, places=5)       # +6.57%
        self.assertAlmostEqual(s["sharpe"], 0.874365, places=5)     # 0.87
        self.assertAlmostEqual(s["maxdd"], -0.139348, places=5)     # -13.93%
        self.assertEqual(s["late"], 0)


if __name__ == "__main__":
    unittest.main()
