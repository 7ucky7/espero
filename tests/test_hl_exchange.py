"""Testnet-only signing: the guards, the rounding, the mirror. No key, no network."""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from espero import carry_paper as cp
from espero import hl_exchange as hx

GOOD = {"HL_NETWORK": "testnet", "ESPERO_ALLOW_HL_TESTNET": "1", "HL_PRIVATE_KEY": "0x" + "1" * 64}


class TestGuard(unittest.TestCase):
    def test_all_four_conditions(self):
        self.assertEqual(hx.guard(GOOD), GOOD["HL_PRIVATE_KEY"])
        for broken in ({**GOOD, "HL_NETWORK": "mainnet"}, {**GOOD, "HL_NETWORK": ""},
                       {**GOOD, "ESPERO_ALLOW_HL_TESTNET": ""}, {**GOOD, "ESPERO_ALLOW_HL_TESTNET": "yes"},
                       {**GOOD, "HL_PRIVATE_KEY": ""},
                       {**GOOD, "HL_API_URL": "https://api.hyperliquid.xyz"}):
            with self.assertRaises(hx.TestnetRefused):
                hx.guard(broken)

    def test_testnet_url_override_allowed(self):
        self.assertTrue(hx.guard({**GOOD, "HL_API_URL": "https://api.hyperliquid-testnet.xyz"}))

    def test_building_without_injection_reads_no_key_when_guard_fails(self):
        with self.assertRaises(hx.TestnetRefused):
            hx.TestnetExchange(env={"HL_NETWORK": "mainnet", "HL_PRIVATE_KEY": "x"})


class TestRounding(unittest.TestCase):
    def test_price_five_sig_figs_and_side_aware(self):
        self.assertEqual(hx.round_price(80752.123, 5, "sell"), 80753.0)
        self.assertEqual(hx.round_price(80752.123, 5, "buy"), 80752.0)
        self.assertEqual(hx.round_price(2344.5678, 4, "buy"), 2344.5)
        self.assertEqual(hx.round_price(0.0043537, 0, "sell"), 0.004354)   # 6 decimals cap
        self.assertEqual(hx.round_price(1.234567, 0, "buy"), 1.2345)

    def test_size_floors_to_sz_decimals(self):
        self.assertEqual(hx.round_size(0.0019, 3), 0.001)
        self.assertEqual(hx.round_size(12.3456, 1), 12.3)

    def test_parse_order_response(self):
        resting = {"status": "ok", "response": {"type": "order", "data": {"statuses": [{"resting": {"oid": 7}}]}}}
        self.assertEqual(hx.parse_order_response(resting)["status"], "resting")
        filled = {"filled": {"oid": 8, "totalSz": "0.5", "avgPx": "9"}}
        f = hx.parse_order_response({"status": "ok", "response": {"data": {"statuses": [filled]}}})
        self.assertEqual((f["status"], f["oid"], f["filled"], f["avg_px"]), ("filled", 8, 0.5, 9.0))
        e = hx.parse_order_response({"status": "ok", "response": {"data": {"statuses": [{"error": "Post only"}]}}})
        self.assertEqual((e["status"], e["error"]), ("error", "Post only"))
        self.assertEqual(hx.parse_order_response("garbage")["status"], "error")


class FakeExchange:
    """Records orders; `resting` unless told to fill."""

    def __init__(self, fill=False):
        self.orders, self.cancels, self.fill = [], [], fill
        self.base_url = hx.TESTNET_URL

    def order(self, name, is_buy, sz, px, order_type, reduce_only=False, **kw):
        self.orders.append((name, "buy" if is_buy else "sell", sz, px, order_type["limit"]["tif"], reduce_only))
        oid = len(self.orders)
        if self.fill:
            st = {"filled": {"oid": oid, "totalSz": str(sz), "avgPx": str(px)}}
        else:
            st = {"resting": {"oid": oid}}
            self.info.open.append({"oid": oid})         # the venue lists a resting order
        return {"status": "ok", "response": {"data": {"statuses": [st]}}}

    def cancel(self, name, oid):
        self.cancels.append((name, oid))
        self.info.open = [o for o in self.info.open if o["oid"] != oid]
        return {"status": "ok"}


class FakeInfo:
    def __init__(self):
        self.open, self.fills_ = [], []

    def meta(self):
        return {"universe": [{"name": "ETH", "szDecimals": 4}, {"name": "BTC", "szDecimals": 5}]}

    def open_orders(self, address):
        return self.open

    def user_fills(self, address):
        return self.fills_


def exchange(fill=False):
    info = FakeInfo()
    fake = FakeExchange(fill)
    fake.info = info
    return hx.TestnetExchange(exchange=fake, info=info, address="0xtest")


class TestExchange(unittest.TestCase):
    def test_limit_rounds_and_posts_alo(self):
        ex = exchange()
        r = ex.limit("ETH", "sell", 0.12345678, 2344.5678)
        self.assertEqual(ex.ex.orders[0], ("ETH", "sell", 0.1234, 2344.6, "Alo", False))
        self.assertEqual((r.status, r.oid), ("resting", 1))

    def test_unknown_coin_and_zero_size_refused(self):
        ex = exchange()
        with self.assertRaises(ValueError):
            ex.limit("DOGE", "sell", 1, 1)
        with self.assertRaises(ValueError):
            ex.limit("BTC", "sell", 0.000001, 80000)


class TestMirrorGrace(unittest.TestCase):
    def test_just_placed_order_not_listed_yet_stays_resting(self):
        with tempfile.TemporaryDirectory() as d:
            book = cp.CarryBook(Path(d) / "b.db", costs="maker", initial=500.0, max_coins=1)
            ex = exchange()
            mirror = hx.TestnetMirror(book.db, ex)
            book.on_hour(3600, {"ETH": cp.Row(1e-5, 0.2, 2000.0, 1999.0)})
            mirror.sync(book.open_positions(), book.closed_positions(), {"ETH": 2000.0}, now=3600)
            ex.info.open = []                                   # venue lagging
            mirror.refresh(now=3601)
            self.assertEqual(mirror.rows()[0]["open_status"], "resting")
            mirror.refresh(now=3600 + 120)                      # past the grace: really gone
            self.assertEqual(mirror.rows()[0]["open_status"], "cancelled")
            book.close()


class TestMirror(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.book = cp.CarryBook(Path(self.tmp.name) / "b.db", costs="maker", initial=500.0, max_coins=1)
        self.ex = exchange()
        self.mirror = hx.TestnetMirror(self.book.db, self.ex)

    def tearDown(self):
        self.book.close()
        self.tmp.cleanup()

    def rows(self, f_ann=0.2, perp=2000.0):
        return {"ETH": cp.Row(funding=1e-5, f_ann=f_ann, perp=perp, spot=1999.0)}

    def test_new_paper_position_becomes_a_resting_short(self):
        self.book.on_hour(3600, self.rows())
        out = self.mirror.sync(self.book.open_positions(), self.book.closed_positions(), {"ETH": 2000.0}, now=3600)
        self.assertEqual(len(self.ex.ex.orders), 1)
        name, side, sz, px, tif, ro = self.ex.ex.orders[0]
        self.assertEqual((name, side, tif, ro), ("ETH", "sell", "Alo", False))
        self.assertAlmostEqual(sz, round(250.0 / 2000.0, 4))
        self.assertEqual(self.mirror.rows()[0]["open_status"], "resting")
        # a second sync places nothing new
        self.mirror.sync(self.book.open_positions(), self.book.closed_positions(), {"ETH": 2000.0}, now=3601)
        self.assertEqual(len(self.ex.ex.orders), 1)
        self.assertTrue(any("resting" in o for o in out))

    def test_unfilled_open_is_cancelled_when_paper_closes(self):
        self.book.on_hour(3600, self.rows())
        self.mirror.sync(self.book.open_positions(), self.book.closed_positions(), {"ETH": 2000.0}, now=3600)
        self.book.on_hour(7200, self.rows(f_ann=0.01))          # paper exits: funding_low
        self.mirror.sync(self.book.open_positions(), self.book.closed_positions(), {"ETH": 2000.0}, now=7200)
        self.assertEqual(self.ex.ex.cancels, [("ETH", 1)])
        self.assertEqual(self.mirror.rows()[0]["close_status"], "unfilled_open")
        self.assertEqual(len(self.ex.ex.orders), 1)              # no close order for nothing

    def test_filled_open_gets_a_reduce_only_close(self):
        self.ex.ex.fill = True
        self.book.on_hour(3600, self.rows())
        self.mirror.sync(self.book.open_positions(), self.book.closed_positions(), {"ETH": 2000.0}, now=3600)
        self.assertEqual(self.mirror.rows()[0]["open_status"], "filled")
        self.book.on_hour(7200, self.rows(f_ann=0.01))
        self.mirror.sync(self.book.open_positions(), self.book.closed_positions(), {"ETH": 2010.0}, now=7200)
        self.assertEqual(self.ex.ex.orders[1][:2], ("ETH", "buy"))
        self.assertTrue(self.ex.ex.orders[1][5])                  # reduce-only
        self.assertEqual(self.mirror.summary()["filled"], 1)

    def test_refresh_reads_fills_and_open_orders(self):
        self.book.on_hour(3600, self.rows())
        self.mirror.sync(self.book.open_positions(), self.book.closed_positions(), {"ETH": 2000.0}, now=3600)
        size = self.mirror.rows()[0]["open_size"]
        self.ex.info.fills_ = [{"oid": 1, "sz": str(size / 2), "time": 3600_000}]
        self.mirror.refresh(now=10_000)
        self.assertEqual(self.mirror.rows()[0]["open_status"], "part")
        self.ex.info.fills_.append({"oid": 1, "sz": str(size / 2), "time": 3601_000})
        self.mirror.refresh(now=10_000)
        self.assertEqual(self.mirror.rows()[0]["open_status"], "filled")

    def test_order_error_is_recorded_not_raised(self):
        err = {"status": "ok", "response": {"data": {"statuses": [{"error": "Post only would cross"}]}}}
        self.ex.ex.order = lambda *a, **k: err
        self.book.on_hour(3600, self.rows())
        out = self.mirror.sync(self.book.open_positions(), self.book.closed_positions(), {"ETH": 2000.0}, now=3600)
        self.assertEqual(self.mirror.rows()[0]["open_status"], "error")
        self.assertIn("Post only", out[0])
        self.assertEqual(self.mirror.summary()["errors"], 1)

    def test_mirror_survives_reopen(self):
        self.book.on_hour(3600, self.rows())
        self.mirror.sync(self.book.open_positions(), self.book.closed_positions(), {"ETH": 2000.0}, now=3600)
        db = sqlite3.connect(self.book.path)
        db.row_factory = sqlite3.Row
        again = hx.TestnetMirror(db, exchange())
        self.assertEqual(len(again.rows()), 1)
        db.close()


if __name__ == "__main__":
    unittest.main()
