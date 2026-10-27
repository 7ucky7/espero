"""Live execution must be boring: every order capped, every order tagged, no
order at all unless three separate things say yes."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

import espero.live as live_mod
from espero.broker import Ack, BrokerError, DryRunBroker, broker_from_env
from espero.journal import Journal
from espero.live import LiveConfig, LiveTrader
from espero.signals import Signal

GRAN = 1000


def bar(i: int, open_px: float, close_px: float | None = None, high=None, low=None) -> dict:
    close_px = open_px if close_px is None else close_px
    return {
        "ts": 1_000_000 + i * GRAN, "open": open_px,
        "high": high if high is not None else max(open_px, close_px) * 1.001,
        "low": low if low is not None else min(open_px, close_px) * 0.999,
        "close": close_px, "volume": 1.0,
    }


class FakeBroker:
    name = "fake"
    live = True

    def __init__(self, price: float = 100.0, cash: float = 500.0):
        self._price, self._cash = price, cash
        self.orders = []

    def price(self, product: str) -> float:
        return self._price

    def balance(self, currency: str) -> float:
        return self._cash

    def market_buy(self, product, notional, client_id):
        self.orders.append(("buy", notional, client_id))
        return Ack("o1", client_id, "filled", filled_px=self._price,
                   filled_size=notional / self._price)

    def market_sell(self, product, size, client_id):
        self.orders.append(("sell", size, client_id))
        return Ack("o2", client_id, "filled", filled_px=self._price, filled_size=size)


class ScriptedSignal:
    def __init__(self, nth: int = 1, side: str = "BUY", confidence: float = 0.9):
        self.nth, self.calls, self.side, self.confidence = nth, 0, side, confidence

    def __call__(self, sigs):
        self.calls += 1
        return Signal(self.side, self.confidence, "test") if self.calls == self.nth else None


class LiveTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.journal = Journal(self.dir / "live.db")
        self.orig = live_mod.combine
        self.cfg = LiveConfig(granularity=GRAN, warmup=1, max_notional=25.0)

    def tearDown(self):
        live_mod.combine = self.orig
        self.journal.close()
        self.tmp.cleanup()

    def prime(self, trader, n=3, price=100.0):
        for i in range(n):
            trader.on_bar(bar(i, price))


class TestLiveOrders(LiveTestCase):
    def test_signal_places_a_capped_order_with_a_client_id(self):
        broker = FakeBroker()
        trader = LiveTrader(self.journal, broker, self.cfg, kill_file=self.dir / "KILL")
        live_mod.combine = ScriptedSignal(nth=1)
        self.prime(trader)

        self.assertEqual(len(broker.orders), 1)
        side, notional, client_id = broker.orders[0]
        self.assertEqual(side, "buy")
        self.assertLessEqual(notional, self.cfg.max_notional)
        self.assertAlmostEqual(notional, 25.0)  # risk says 100, cap says 25
        self.assertTrue(client_id.startswith("buy-"))

    def test_position_is_recorded_with_the_bar_timestamp(self):
        broker = FakeBroker()
        trader = LiveTrader(self.journal, broker, self.cfg, kill_file=self.dir / "KILL")
        live_mod.combine = ScriptedSignal(nth=1)
        self.prime(trader)
        self.assertIsNotNone(trader.position)
        self.assertEqual(trader.position.entry_ts, bar(2, 0)["ts"])

    def test_kill_file_blocks_everything(self):
        (self.dir / "KILL").write_text("stop")
        broker = FakeBroker()
        trader = LiveTrader(self.journal, broker, self.cfg, kill_file=self.dir / "KILL")
        live_mod.combine = ScriptedSignal(nth=1)
        self.prime(trader)
        self.assertEqual(broker.orders, [])
        self.assertIn("halted", trader.on_bar(bar(9, 100))[0])

    def test_stop_sells_the_position(self):
        broker = FakeBroker()
        trader = LiveTrader(self.journal, broker, self.cfg, kill_file=self.dir / "KILL")
        live_mod.combine = ScriptedSignal(nth=1)
        self.prime(trader)
        trader.on_bar(bar(3, 100.0, low=80.0))
        self.assertEqual(broker.orders[-1][0], "sell")
        self.assertIsNone(trader.position)


class TestDryRun(unittest.TestCase):
    def test_dry_run_reads_but_never_sends(self):
        inner = FakeBroker()
        dry = DryRunBroker(inner)
        ack = dry.market_buy("BTC-USD", 20.0, "test-1")
        self.assertEqual(ack.status, "dry-run")
        self.assertEqual(inner.orders, [])
        self.assertFalse(dry.live)
        self.assertEqual(dry.price("BTC-USD"), 100.0)

    def test_live_requires_two_explicit_opt_ins(self):
        os.environ["COINBASE_API_KEY"] = "key"
        os.environ["COINBASE_API_SECRET"] = "secret"
        os.environ.pop("ESPERO_ALLOW_LIVE", None)
        try:
            with self.assertRaises(BrokerError) as ctx:
                broker_from_env(dry_run=False)
            self.assertIn("ESPERO_ALLOW_LIVE", str(ctx.exception))
            dry = broker_from_env(dry_run=True)
            self.assertFalse(dry.live)
        finally:
            os.environ.pop("COINBASE_API_KEY", None)
            os.environ.pop("COINBASE_API_SECRET", None)


if __name__ == "__main__":
    unittest.main(verbosity=2)
