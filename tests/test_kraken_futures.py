"""Kraken Futures fetchers, on synthetic payloads (no network)."""
from __future__ import annotations

import unittest

from espero import carry
from espero import kraken_futures as kf

T = 1_775_000_000 // 3600 * 3600


def iso(t: int) -> str:
    import datetime as dt
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


class TestSymbols(unittest.TestCase):
    def test_base_of_maps_kraken_aliases_and_drops_non_perps(self):
        self.assertEqual(kf.base_of("PF_XBTUSD"), "BTC")
        self.assertEqual(kf.base_of("PF_XDGUSD"), "DOGE")
        self.assertEqual(kf.base_of("PF_SOLUSD"), "SOL")
        self.assertIsNone(kf.base_of("PI_XBTUSD"))          # inverse
        self.assertIsNone(kf.base_of("FF_XBTUSD_260327"))    # dated future

    def test_open_interest_in_usd_ranks_the_universe(self):
        payload = {"tickers": [
            {"symbol": "PF_XBTUSD", "openInterest": 100, "markPrice": 60000},
            {"symbol": "PF_SOLUSD", "openInterest": 50000, "markPrice": 150},
            {"symbol": "PF_DEADUSD", "openInterest": 9e9, "markPrice": 1, "suspended": True},
            {"symbol": "PI_XBTUSD", "openInterest": 9e9, "markPrice": 60000},
            {"symbol": "PF_BADUSD", "openInterest": None, "markPrice": "x"},
        ]}
        perps = kf.perpetuals(fetch=lambda url: payload)
        top = kf.top_by_open_interest(2, perps)
        self.assertEqual([r["coin"] for r in top], ["SOL", "BTC"])     # 7.5M > 6M
        self.assertAlmostEqual(top[0]["open_interest_usd"], 7.5e6)


class TestFunding(unittest.TestCase):
    def test_history_parses_iso_times_and_relative_rate(self):
        payload = {"rates": [{"timestamp": iso(T + 3600), "fundingRate": 9.9, "relativeFundingRate": 2e-5},
                             {"timestamp": iso(T), "fundingRate": 9.9, "relativeFundingRate": 1e-5}]}
        df = kf.funding_history("PF_XBTUSD", fetch=lambda url: payload)
        self.assertEqual(df["ts"].tolist(), [T, T + 3600])
        self.assertEqual(df["rate"].tolist(), [1e-5, 2e-5])

    def test_an_hourly_rate_covers_every_hour_of_its_period_unchanged(self):
        import pandas as pd
        raw = pd.DataFrame({"ts": [T, T + 4 * 3600, T + 8 * 3600], "rate": [1e-5, 2e-5, 3e-5]})
        h = kf.hourly_funding(raw)
        self.assertEqual(h["ts"].tolist(), [T + k * 3600 for k in range(12)])
        self.assertEqual(h["funding"].tolist(), [1e-5] * 4 + [2e-5] * 4 + [3e-5] * 4)
        # not divided by the period: a 4-hour period earns 4 x the hourly rate
        self.assertAlmostEqual(h["funding"].iloc[:4].sum(), 4e-5)

    def test_hourly_series_is_left_alone(self):
        import pandas as pd
        raw = pd.DataFrame({"ts": [T + k * 3600 for k in range(5)], "rate": [1e-5] * 5})
        self.assertEqual(len(kf.hourly_funding(raw)), 5)

    def test_a_long_gap_stays_missing(self):
        import pandas as pd
        raw = pd.DataFrame({"ts": [T, T + 3600, T + 30 * 3600, T + 31 * 3600], "rate": [1e-5] * 4})
        h = kf.hourly_funding(raw)
        self.assertEqual(h["ts"].tolist(), [T, T + 3600, T + 30 * 3600, T + 31 * 3600])

    def test_feeds_the_carry_engine_on_the_same_scale_as_hyperliquid(self):
        import pandas as pd
        n = carry.MIN_HISTORY_H + 10
        raw = pd.DataFrame({"ts": [T + k * 4 * 3600 for k in range(n // 4 + 1)], "rate": [2e-5] * (n // 4 + 1)})
        f = kf.hourly_funding(raw)
        times = [iso(T + k * 3600) for k in range(len(f))]
        px = pd.DataFrame({"time": times, "close": [100.0] * len(f)})
        cd = carry.from_frames(f, px, px)
        self.assertIsNotNone(cd)
        ann = carry.annualised(pd.DataFrame({"X": cd.funding})).dropna()["X"].iloc[-1]
        self.assertAlmostEqual(ann, 2e-5 * carry.HOURS_PER_YEAR)


class TestCandles(unittest.TestCase):
    def test_paginates_forward_and_drops_the_open_hour(self):
        import time
        now = int(time.time()) // 3600 * 3600
        start = now - 6 * 3600
        calls = []

        def fetch(url):
            calls.append(url)
            frm = int(url.split("from=")[1].split("&")[0])
            ts = [t for t in range(frm, now + 3600, 3600)][:3]           # 3 per page, incl. the open hour
            return {"candles": [{"time": t * 1000, "open": "1", "high": "2", "low": "0.5", "close": str(t),
                                 "volume": "7"} for t in ts], "more_candles": True}

        df = kf.candles("PF_XBTUSD", start, fetch=fetch, sleep=lambda s: None)
        got = [int(pd_ts.timestamp()) for pd_ts in __import__("pandas").to_datetime(df["time"])]
        self.assertEqual(got, list(range(start, now, 3600)))             # the hour still open is not kept
        self.assertEqual(df["close"].iloc[0], float(start))
        self.assertGreater(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
