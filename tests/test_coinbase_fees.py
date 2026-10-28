"""`espero fees`: signed, read-only, and never leaks a credential."""
from __future__ import annotations

import base64
import contextlib
import hashlib
import hmac
import io
import json
import unittest
import urllib.error
from unittest import mock

from espero import cli
from espero import coinbase_fees as cf

SECRET = base64.b64encode(b"not-a-real-secret").decode()
ENV = {"COINBASE_EXCHANGE_KEY": "key-123", "COINBASE_EXCHANGE_SECRET": SECRET,
       "COINBASE_EXCHANGE_PASSPHRASE": "pass-xyz"}


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestFees(unittest.TestCase):
    def test_signature_matches_the_documented_recipe(self):
        expected = base64.b64encode(hmac.new(b"not-a-real-secret", b"1700000000GET/fees",
                                             hashlib.sha256).digest()).decode()
        self.assertEqual(cf.sign(SECRET, "1700000000", "GET", "/fees"), expected)

    def test_fetch_sends_the_four_headers_and_parses(self):
        seen = {}

        def opener(req, timeout):
            seen.update({k.lower(): v for k, v in req.header_items()})
            seen["url"], seen["method"] = req.full_url, req.get_method()
            return Resp(json.dumps({"maker_fee_rate": "0.0040", "taker_fee_rate": "0.0060",
                                    "usd_volume": "12345.6"}).encode())

        f = cf.fetch(ENV, opener=opener, now=1_700_000_000)
        self.assertEqual((f.maker_bps, f.taker_bps, f.usd_volume), (40.0, 60.0, 12345.6))
        self.assertEqual((seen["url"], seen["method"]), ("https://api.exchange.coinbase.com/fees", "GET"))
        self.assertEqual(seen["cb-access-key"], "key-123")
        self.assertEqual(seen["cb-access-passphrase"], "pass-xyz")
        self.assertEqual(seen["cb-access-timestamp"], "1700000000")
        self.assertEqual(seen["cb-access-sign"], cf.sign(SECRET, "1700000000", "GET", "/fees"))

    def test_missing_credentials_name_the_variables_not_values(self):
        with self.assertRaises(cf.FeesError) as ctx:
            cf.fetch({"COINBASE_EXCHANGE_KEY": "key-123"})
        msg = str(ctx.exception)
        self.assertIn("COINBASE_EXCHANGE_SECRET", msg)
        self.assertNotIn("key-123", msg)

    def test_http_errors_carry_no_credential(self):
        def opener(req, timeout):
            raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, None)
        with self.assertRaises(cf.FeesError) as ctx:
            cf.fetch(ENV, opener=opener)
        msg = str(ctx.exception)
        self.assertIn("401", msg)
        for secret in ENV.values():
            self.assertNotIn(secret, msg)

    def test_unexpected_shape_is_an_error(self):
        with self.assertRaises(cf.FeesError):
            cf.parse({"maker": 1})


class TestFeesCommand(unittest.TestCase):
    def test_prints_rates_against_the_venue_table(self):
        args = cli.build_parser().parse_args(["fees"])
        with mock.patch.object(cf, "fetch", return_value=cf.Fees(0.006, 0.012, 50.0)), \
                mock.patch("espero.broker.load_env"), contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(args.func(args), 0)
        text = out.getvalue()
        self.assertIn("taker 1.2000% (120.0 bps)", text)
        self.assertIn("[matches]", text)
        self.assertIn("--fee-bps 120.0", text)

    def test_degen_paper_accepts_a_fee_override(self):
        args = cli.build_parser().parse_args(["degen", "paper", "--fee-bps", "40"])
        self.assertEqual(args.fee_bps, 40.0)


if __name__ == "__main__":
    unittest.main()
