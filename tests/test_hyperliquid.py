"""Hyperliquid info endpoint parsing, with the network replaced by a fake fetch."""
from __future__ import annotations

import unittest

from espero import hyperliquid as hl
from espero.venues import VENUES


def fake_ctxs(_body):
    meta = {"universe": [{"name": "BTC", "maxLeverage": 50}, {"name": "ETH", "maxLeverage": 50},
                         {"name": "OLD", "maxLeverage": 10, "isDelisted": True}]}
    ctxs = [{"markPx": "100000", "funding": "0.0000125", "openInterest": "1000", "dayNtlVlm": "5e9"},
            {"markPx": "3000", "funding": "-0.00001", "openInterest": "50000", "dayNtlVlm": "2e9"},
            {"markPx": "1", "funding": "0", "openInterest": "1", "dayNtlVlm": "1"}]
    return [meta, ctxs]


class TestContexts(unittest.TestCase):
    def test_rows_in_dollars_and_delisted_dropped(self):
        rows = hl.asset_contexts(fetch=fake_ctxs)
        self.assertEqual([r["coin"] for r in rows], ["BTC", "ETH"])
        self.assertAlmostEqual(rows[0]["open_interest"], 1000 * 100000)
        self.assertAlmostEqual(rows[1]["open_interest"], 50000 * 3000)
        self.assertAlmostEqual(rows[0]["funding"], 1.25e-5)

    def test_top_by_open_interest(self):
        rows = hl.asset_contexts(fetch=fake_ctxs)
        self.assertEqual(hl.top_by_open_interest(1, rows), ["ETH"])
        self.assertEqual(hl.top_by_open_interest(5, rows), ["ETH", "BTC"])


class TestFunding(unittest.TestCase):
    def test_pages_forward_and_dedups(self):
        calls = []

        def fetch(body):
            calls.append(body["startTime"])
            if body["startTime"] == 0:
                return [{"time": t * 3600_000, "fundingRate": "0.00001"} for t in range(500)]
            return [{"time": 499 * 3600_000, "fundingRate": "0.00001"},
                    {"time": 500 * 3600_000, "fundingRate": "0.00002"}]

        df = hl.funding_history("BTC", 0, fetch=fetch, sleep=lambda s: None)
        self.assertEqual(calls, [0, 499 * 3600_000 + 1])
        self.assertEqual(len(df), 501)
        self.assertEqual(df["ts"].iloc[-1], 500 * 3600)
        self.assertAlmostEqual(df["funding"].iloc[-1], 2e-5)

    def test_empty(self):
        df = hl.funding_history("X", 0, fetch=lambda b: [])
        self.assertTrue(df.empty)
        self.assertEqual(list(df.columns), ["ts", "funding"])


class TestCandles(unittest.TestCase):
    def test_paginates_under_cap_and_matches_data_frame(self):
        step = 3600_000
        calls = []

        def fetch(body):
            req = body["req"]
            calls.append((req["startTime"], req["endTime"]))
            t0 = req["startTime"]
            n = min(hl.CANDLE_LIMIT, (req["endTime"] - t0) // step)
            return [{"t": t0 + k * step, "o": "1", "h": "2", "l": "0.5", "c": "1.5", "v": "10"}
                    for k in range(n)]

        end = 6000 * step
        df = hl.candles("ETH", "1h", 0, end_ms=end, fetch=fetch, sleep=lambda s: None)
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(df), 6000)
        self.assertEqual(list(df.columns), ["time", "open", "high", "low", "close", "volume"])
        self.assertTrue(df["time"].iloc[0].startswith("1970-01-01T00:00:00"))
        self.assertEqual(df["close"].iloc[-1], 1.5)

    def test_stops_on_empty_page(self):
        df = hl.candles("ETH", "1h", 0, end_ms=10 * 3600_000, fetch=lambda b: [])
        self.assertTrue(df.empty)


class TestVenue(unittest.TestCase):
    def test_hyperliquid_row_settles_hourly(self):
        v = VENUES["hyperliquid"]
        self.assertEqual(v.kind, "perp")
        self.assertEqual(v.funding_period_s, 3600)
        self.assertEqual((v.maker_bps, v.taker_bps), (1.5, 4.5))
        self.assertEqual(VENUES["perp"].funding_period_s, 8 * 3600)


if __name__ == "__main__":
    unittest.main()
