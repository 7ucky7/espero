"""The data layer retries, then falls back to a fresh cache, then fails loudly."""
from __future__ import annotations

import io
import tempfile
import time
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from espero import data


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("http://x", code, "err", {}, io.BytesIO(b""))


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestHttpGet(unittest.TestCase):
    def test_retries_on_5xx_then_succeeds(self):
        calls = [_http_error(503), _http_error(502), FakeResponse(b"ok")]
        with mock.patch("urllib.request.urlopen", side_effect=calls) as m:
            out = data.http_get("http://x", retries=4, sleep=lambda s: None)
        self.assertEqual(out, b"ok")
        self.assertEqual(m.call_count, 3)

    def test_4xx_is_not_retried(self):
        with mock.patch("urllib.request.urlopen", side_effect=[_http_error(404)]) as m:
            with self.assertRaises(data.FetchError):
                data.http_get("http://x", retries=4, sleep=lambda s: None)
        self.assertEqual(m.call_count, 1)

    def test_429_is_retried(self):
        calls = [_http_error(429), FakeResponse(b"{}")]
        with mock.patch("urllib.request.urlopen", side_effect=calls):
            self.assertEqual(data.http_json("http://x", timeout=1), {})

    def test_gives_up_after_retries(self):
        with mock.patch("urllib.request.urlopen", side_effect=OSError("down")) as m:
            with self.assertRaises(data.FetchError):
                data.http_get("http://x", retries=3, sleep=lambda s: None)
        self.assertEqual(m.call_count, 3)


class TestYahooCache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _payload(self, n=5):
        ts = [1_700_000_000 + 86400 * i for i in range(n)]
        q = {k: [100.0 + i for i in range(n)] for k in ("open", "high", "low", "close")}
        q["volume"] = [1.0] * n
        return {"chart": {"result": [{"timestamp": ts, "indicators": {"quote": [q]}}]}}

    def test_success_writes_the_cache(self):
        with mock.patch.object(data, "http_json", return_value=self._payload()):
            df = data.yahoo_daily("BTC-USD", "1y", cache_dir=self.dir)
        self.assertEqual(len(df), 5)
        self.assertTrue(data.cache_path("BTC-USD", "1y", self.dir).exists())

    def test_failure_falls_back_to_a_fresh_cache(self):
        with mock.patch.object(data, "http_json", return_value=self._payload()):
            data.yahoo_daily("BTC-USD", "1y", cache_dir=self.dir)
        with mock.patch.object(data, "http_json", side_effect=data.FetchError("down")):
            df = data.yahoo_daily("BTC-USD", "1y", cache_dir=self.dir)
        self.assertEqual(len(df), 5)
        self.assertAlmostEqual(float(df["close"].iloc[-1]), 104.0)

    def test_failure_with_a_stale_cache_raises(self):
        with mock.patch.object(data, "http_json", return_value=self._payload()):
            data.yahoo_daily("BTC-USD", "1y", cache_dir=self.dir)
        p = data.cache_path("BTC-USD", "1y", self.dir)
        old = time.time() - 10 * 86400
        import os
        os.utime(p, (old, old))
        with mock.patch.object(data, "http_json", side_effect=data.FetchError("down")):
            with self.assertRaises(data.FetchError):
                data.yahoo_daily("BTC-USD", "1y", cache_dir=self.dir)

    def test_failure_with_no_cache_raises(self):
        with mock.patch.object(data, "http_json", side_effect=data.FetchError("down")):
            with self.assertRaises(data.FetchError):
                data.yahoo_daily("ETH-USD", "1y", cache_dir=self.dir)



class TestYahooAdjusted(unittest.TestCase):
    """`adjusted=True` is opt-in: the accounts that read raw closes must see no change."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _payload(self, n=5, adj=True):
        ts = [1_700_000_000 + 86400 * i for i in range(n)]
        q = {k: [100.0 + i for i in range(n)] for k in ("open", "high", "low", "close")}
        q["volume"] = [1.0] * n
        ind = {"quote": [q]}
        if adj:
            ind["adjclose"] = [{"adjclose": [90.0 + i for i in range(n - 1)] + [None]}]
        return {"chart": {"result": [{"timestamp": ts, "indicators": ind}]}}

    def test_default_request_columns_and_cache_are_unchanged(self):
        with mock.patch.object(data, "http_json", return_value=self._payload()) as get:
            df = data.yahoo_daily("TLT", "1y", cache_dir=self.dir)
        self.assertEqual(get.call_args[0][0],
                         "https://query1.finance.yahoo.com/v8/finance/chart/TLT?range=1y&interval=1d")
        self.assertEqual(list(df.columns), ["dt", "ts", "open", "high", "low", "close", "volume"])
        self.assertEqual(len(df), 5)                       # the adjclose gap does not drop a raw row
        self.assertEqual(sorted(f.name for f in self.dir.iterdir()), ["TLT_1y.csv"])

    def test_adjusted_reads_adjclose_into_its_own_cache(self):
        with mock.patch.object(data, "http_json", return_value=self._payload()) as get:
            df = data.yahoo_daily("TLT", "1y", cache_dir=self.dir, adjusted=True)
        self.assertIn("events=div%2Csplit", get.call_args[0][0])
        self.assertEqual(list(df["adj_close"]), [90.0, 91.0, 92.0, 93.0])   # the None row is dropped
        self.assertEqual(list(df["close"]), [100.0, 101.0, 102.0, 103.0])
        self.assertEqual(sorted(f.name for f in self.dir.iterdir()), ["TLT_1y_adj.csv"])
        with mock.patch.object(data, "http_json", side_effect=data.FetchError("down")):
            cached = data.yahoo_daily("TLT", "1y", cache_dir=self.dir, adjusted=True)
        self.assertEqual(list(cached["adj_close"]), [90.0, 91.0, 92.0, 93.0])

    def test_adjusted_never_falls_back_to_the_raw_cache(self):
        with mock.patch.object(data, "http_json", return_value=self._payload()):
            data.yahoo_daily("TLT", "1y", cache_dir=self.dir)
        with mock.patch.object(data, "http_json", side_effect=data.FetchError("down")):
            with self.assertRaises(data.FetchError):
                data.yahoo_daily("TLT", "1y", cache_dir=self.dir, adjusted=True)

    def test_a_payload_without_adjclose_is_an_error(self):
        with mock.patch.object(data, "http_json", return_value=self._payload(adj=False)):
            with self.assertRaises(data.FetchError):
                data.yahoo_daily("TLT", "1y", cache_dir=self.dir, adjusted=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestUnixSeconds(unittest.TestCase):
    def test_same_seconds_at_any_parse_resolution(self):
        import pandas as pd
        iso = ["2026-03-30T00:00:00+00:00", "2026-03-30T01:00:00+00:00"]
        self.assertEqual(data.unix_seconds(iso).tolist(), [1774828800, 1774832400])
        for unit in ("s", "ms", "us", "ns"):
            t = pd.to_datetime(pd.Series(iso), utc=True).astype(f"datetime64[{unit}, UTC]")
            self.assertEqual(data.unix_seconds(t).tolist(), [1774828800, 1774832400], unit)
