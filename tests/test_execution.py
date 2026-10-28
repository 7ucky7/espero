"""The book reads honestly and the paper exchange under-fills, never over-fills."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from espero import book as bk
from espero.execution import PaperExchange


def snap(ts=0.0, bid=100.0, ask=100.1, bid_size=2.0, ask_size=2.0, trades=()):
    s = bk.BookSnapshot(ts, "X-USD",
                        bids=[(bid, bid_size), (bid - 0.1, 5.0), (bid - 0.2, 5.0)],
                        asks=[(ask, ask_size), (ask + 0.1, 5.0), (ask + 0.2, 5.0)])
    s.trades = [bk.Trade(i, ts, side, px, size) for i, (side, px, size) in enumerate(trades)]
    return s


class TestSnapshot(unittest.TestCase):
    def test_mid_spread_depth_imbalance(self):
        s = snap()
        self.assertAlmostEqual(s.mid, 100.05)
        self.assertAlmostEqual(s.spread_bps, 1e4 * 0.1 / 100.05)
        self.assertAlmostEqual(s.depth_ahead("buy", 100.0), 2.0)       # joins the back at best bid
        self.assertAlmostEqual(s.depth_ahead("buy", 99.9), 7.0)        # better bids are ahead too
        self.assertAlmostEqual(s.depth_ahead("sell", 100.1), 2.0)
        self.assertAlmostEqual(s.imbalance(1), 0.0)
        self.assertGreater(snap(bid_size=6.0).imbalance(1), 0)

    def test_json_round_trip_and_replay(self):
        s = snap(trades=[("buy", 100.1, 0.5)])
        again = bk.BookSnapshot.from_json(s.to_json())
        self.assertEqual(again.bids[0], s.bids[0])
        self.assertEqual(again.trades[0].size, 0.5)
        with tempfile.TemporaryDirectory() as d:
            rec = bk.Recorder(Path(d) / "book.jsonl")
            rec.write(s)
            rec.write(snap(ts=1.0))
            rec.close()
            seen = list(bk.replay(Path(d) / "book.jsonl"))
        self.assertEqual([x.ts for x in seen], [0.0, 1.0])

    def test_time_parsing_handles_microseconds(self):
        self.assertAlmostEqual(bk._parse_time("2026-10-27T11:44:20.861618Z"),
                               bk._parse_time("2026-10-27T11:44:20.861Z"), places=2)


class TestPostOnly(unittest.TestCase):
    def test_crossing_orders_are_rejected(self):
        ex = PaperExchange(cash=1000.0)
        s = snap()
        self.assertEqual(ex.place_post_only(s, "buy", 100.1, 1.0).status, "rejected")   # at the ask
        self.assertEqual(ex.place_post_only(s, "buy", 100.0, 1.0).status, "resting")    # at the bid
        self.assertEqual(ex.resting()[0].queue_ahead, 2.0)

    def test_cannot_buy_more_than_cash_or_sell_what_you_lack(self):
        ex = PaperExchange(cash=50.0)
        s = snap()
        self.assertEqual(ex.place_post_only(s, "buy", 100.0, 1.0).status, "rejected")
        self.assertEqual(ex.place_post_only(s, "sell", 100.1, 1.0).status, "rejected")


class TestQueueAndFills(unittest.TestCase):
    def test_nothing_fills_until_the_queue_ahead_is_consumed(self):
        ex = PaperExchange(cash=1000.0, maker_fee=0.0)
        o = ex.place_post_only(snap(), "buy", 100.0, 1.0)      # 2.0 ahead of us
        self.assertEqual(ex.on_snapshot(snap(ts=1, trades=[("sell", 100.0, 1.5)])), [])
        self.assertAlmostEqual(o.queue_ahead, 0.5)
        fills = ex.on_snapshot(snap(ts=2, trades=[("sell", 100.0, 1.0)]))
        self.assertEqual(len(fills), 1)
        self.assertAlmostEqual(fills[0].size, 0.5)                  # 1.0 printed, 0.5 ate the queue
        self.assertEqual(o.status, "resting")
        self.assertAlmostEqual(o.remaining, 0.5)

    def test_a_touch_without_prints_does_not_fill(self):
        ex = PaperExchange(cash=1000.0)
        ex.place_post_only(snap(), "buy", 100.0, 1.0)
        self.assertEqual(ex.on_snapshot(snap(ts=1, bid=99.0, ask=99.1)), [])   # price fell through, no trades

    def test_trades_above_a_bid_do_not_fill_it(self):
        ex = PaperExchange(cash=1000.0)
        ex.place_post_only(snap(), "buy", 100.0, 1.0)
        self.assertEqual(ex.on_snapshot(snap(ts=1, trades=[("buy", 100.1, 5.0)])), [])

    def test_gap_fills_at_the_order_price_and_pays_the_maker_fee(self):
        ex = PaperExchange(cash=1000.0, maker_fee=0.0002)
        o = ex.place_post_only(snap(bid_size=0.0), "buy", 100.0, 1.0, decision_mid=100.05)
        fills = ex.on_snapshot(snap(ts=3, trades=[("sell", 99.5, 2.0)]))   # printed below us
        self.assertEqual(o.status, "filled")
        f = fills[0]
        self.assertAlmostEqual(f.price, 100.0)
        self.assertAlmostEqual(f.fee, 100.0 * 1.0 * 0.0002)
        self.assertAlmostEqual(f.delay_s, 3.0)
        self.assertAlmostEqual(f.slippage_bps, 1e4 * (100.0 - 100.05) / 100.05)   # negative: better than mid
        self.assertAlmostEqual(ex.cash, 1000.0 - 100.0 - f.fee)
        self.assertAlmostEqual(ex.inventory, 1.0)

    def test_round_trip_updates_cash_and_equity(self):
        ex = PaperExchange(cash=1000.0, maker_fee=0.0)
        ex.place_post_only(snap(bid_size=0.0), "buy", 100.0, 1.0)
        ex.on_snapshot(snap(ts=1, trades=[("sell", 100.0, 1.0)]))
        s2 = snap(ts=2, bid=101.0, ask=101.1, ask_size=0.0)
        ex.place_post_only(s2, "sell", 101.1, 1.0)
        ex.on_snapshot(snap(ts=3, bid=101.0, ask=101.1, trades=[("buy", 101.1, 1.0)]))
        self.assertAlmostEqual(ex.inventory, 0.0)
        self.assertAlmostEqual(ex.cash, 1001.1)
        self.assertEqual(len(ex.fills), 2)

    def test_cancel_removes_the_order(self):
        ex = PaperExchange(cash=1000.0)
        o = ex.place_post_only(snap(), "buy", 100.0, 1.0)
        ex.cancel(o.id)
        self.assertEqual(o.status, "cancelled")
        self.assertEqual(ex.resting(), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
