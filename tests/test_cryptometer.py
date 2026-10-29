"""Cryptometer: the key comes from the environment and never appears in an error."""
from __future__ import annotations

import io
import json
import unittest
import urllib.error

from espero import cryptometer as cm

KEY = "k-123-secret"


def answer(payload):
    def opener(req, timeout=None):
        assert KEY in req.full_url
        return io.BytesIO(json.dumps(payload).encode())
    return opener


class TestCryptometer(unittest.TestCase):
    def test_parses_24h_liquidations_by_exchange(self):
        payload = {"success": "true", "data": [{"binance_futures": {"longs": 1.5e6, "shorts": 2e5}, "time": 1}]}
        self.assertEqual(cm.liquidations("BTC", {"CRYPTOMETER_API_KEY": KEY}, answer(payload)),
                         {"binance_futures": {"longs": 1.5e6, "shorts": 2e5}})

    def test_a_refusal_is_reported_without_the_key(self):
        payload = {"success": "false", "error": f"This is a paid endpoint ({KEY})"}
        with self.assertRaises(cm.CryptometerError) as ctx:
            cm.liquidations("btc", {"CRYPTOMETER_API_KEY": KEY}, answer(payload))
        self.assertNotIn(KEY, str(ctx.exception))

    def test_network_errors_hide_the_key(self):
        def opener(req, timeout=None):
            raise urllib.error.URLError(f"failed {req.full_url}")
        with self.assertRaises(cm.CryptometerError) as ctx:
            cm.liquidations("btc", {"CRYPTOMETER_API_KEY": KEY}, opener)
        self.assertNotIn(KEY, str(ctx.exception))

    def test_no_key(self):
        with self.assertRaises(cm.CryptometerError):
            cm.liquidations("btc", {})


if __name__ == "__main__":
    unittest.main()
