"""The paper trader must obey the same rules as the backtest, plus survive restarts."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import espero.paper as paper_mod
from espero.journal import Journal
from espero.paper import PaperConfig, PaperTrader
from espero.signals import Signal

GRAN = 1000


def bar(i: int, open_px: float, close_px: float | None = None, high=None, low=None) -> dict:
    close_px = open_px if close_px is None else close_px
    return {
        "ts": 1_000_000 + i * GRAN,
        "open": open_px,
        "high": high if high is not None else max(open_px, close_px) * 1.001,
        "low": low if low is not None else min(open_px, close_px) * 0.999,
        "close": close_px,
        "volume": 1.0,
    }


class ScriptedSignal:
    """Emit one signal on the nth call of combine()."""

    def __init__(self, nth: int = 1, side: str = "BUY", confidence: float = 0.9):
        self.nth, self.calls, self.side, self.confidence = nth, 0, side, confidence

    def __call__(self, sigs):
        self.calls += 1
        if self.calls == self.nth:
            return Signal(self.side, self.confidence, "test")
        return None


class PaperTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "paper.db"
        self.orig_combine = paper_mod.combine
        self.cfg = PaperConfig(granularity=GRAN, initial=500.0, fee=0.0,
                               slippage=0.0, warmup=1, stop_pct=0.10, target_pct=0.20)

    def tearDown(self):
        paper_mod.combine = self.orig_combine
        self.tmp.cleanup()

    def trader(self) -> PaperTrader:
        self.journal = Journal(self.db)
        return PaperTrader(self.journal, self.cfg)

    def prime(self, t: PaperTrader, price: float = 100.0) -> None:
        """Three bars: warmup satisfied, signal fires on the third close."""
        for i in range(3):
            t.on_bar(bar(i, price))


class TestPaperFills(PaperTestCase):
    def test_signal_queues_instead_of_filling(self):
        t = self.trader()
        paper_mod.combine = ScriptedSignal(nth=1)
        self.prime(t)
        self.assertIsNotNone(t.pending)
        self.assertIsNone(t.position, "a signal must not fill on its own bar")

    def test_fill_happens_on_the_next_bar(self):
        t = self.trader()
        paper_mod.combine = ScriptedSignal(nth=1)
        self.prime(t)
        queued_at = t.pending.created_ts

        t.on_bar(bar(3, 103.0))
        self.assertIsNone(t.pending)
        self.assertIsNotNone(t.position)
        self.assertEqual(t.position.entry_ts, bar(3, 0)["ts"])
        self.assertGreater(t.position.entry_ts, queued_at)
        self.assertAlmostEqual(t.position.entry_px, 103.0)

    def test_duplicate_bar_is_ignored(self):
        t = self.trader()
        self.assertEqual(t.on_bar(bar(0, 100)), [])
        self.assertEqual(t.on_bar(bar(0, 100)), ["duplicate bar ignored"])
        self.assertEqual(t.journal.db.execute("SELECT COUNT(*) FROM bars").fetchone()[0], 1)

    def test_stop_exits_at_the_stop_price(self):
        t = self.trader()
        paper_mod.combine = ScriptedSignal(nth=1)
        self.prime(t)
        t.on_bar(bar(3, 100.0))                    # fill at 100, stop 90
        events = t.on_bar(bar(4, 100.0, low=85.0))  # trades through the stop
        self.assertTrue(any("stop" in e for e in events), events)
        self.assertIsNone(t.position)

    def test_stale_order_is_cancelled_not_filled(self):
        t = self.trader()
        paper_mod.combine = ScriptedSignal(nth=1)
        self.prime(t)
        self.assertIsNotNone(t.pending)
        t.on_bar(bar(10, 150.0))  # the bot was down for ten bars
        self.assertIsNone(t.position, "a stale order must not fill at a new price")
        status = t.journal.db.execute("SELECT status FROM orders").fetchone()["status"]
        self.assertEqual(status, "stale")


class TestRestart(PaperTestCase):
    def _open_position(self) -> PaperTrader:
        t = self.trader()
        paper_mod.combine = ScriptedSignal(nth=1)
        self.prime(t)
        t.on_bar(bar(3, 100.0))
        self.assertIsNotNone(t.position)
        return t

    def test_position_survives_a_restart(self):
        t = self._open_position()
        position_id, cash = t.position.id, t.cash
        self.journal.close()

        self.journal = Journal(self.db)  # new process, same file
        t2 = PaperTrader(self.journal, self.cfg)
        self.assertIsNotNone(t2.position)
        self.assertEqual(t2.position.id, position_id)
        self.assertAlmostEqual(t2.cash, cash)

    def test_equity_survives_a_restart(self):
        t = self._open_position()
        expected = t._equity(100.0)
        curve_len = len(t.journal.equity_curve())
        self.journal.close()

        j2 = Journal(self.db)
        cash, equity = j2.latest_equity()
        self.assertAlmostEqual(equity, expected, places=6)
        self.assertEqual(len(j2.equity_curve()), curve_len)
        self.assertGreater(cash, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
