"""#16 and #17's pieces: the leave-one-out peer basket, the leader-only push,
the Fama-MacBeth control, the past-window fetch and evaluate's minimum training."""
from __future__ import annotations

import datetime as dt
import importlib.util
import unittest
from unittest import mock

import numpy as np
import pandas as pd

from espero import data, factors, ops, panel
from espero import factor_eval as fe


def hourly_panel(n=400, coins=("BTC", "ETH", "A", "B", "C", "D", "E", "F"), seed=1, betas=None):
    """Coins driven by one common hourly factor, each at its own beta."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2025-01-01", periods=n, freq="h")
    common = rng.normal(0, 0.01, n)
    betas = betas or {c: 0.5 + 0.25 * i for i, c in enumerate(coins)}
    close = {c: 100 * np.exp(np.cumsum(betas[c] * common + rng.normal(0, 0.003, n))) for c in coins}
    close = pd.DataFrame(close, index=idx)
    vol = pd.DataFrame(1e4, index=idx, columns=close.columns)
    return panel.MarketPanel(open=close, high=close * 1.001, low=close * 0.999, close=close, volume=vol)


class TestPeerBasket(unittest.TestCase):
    def test_leave_one_out_mean_of_members_without_btc(self):
        p = hourly_panel(n=5)
        members = pd.DataFrame(True, index=p.index, columns=p.coins)
        members.loc[:, "F"] = False
        b = factors.peer_basket(p, members)
        r = ops.returns(p.close, 1)
        row = r.iloc[-1]
        inside = ["ETH", "A", "B", "C", "D", "E"]            # members, BTC excluded
        self.assertAlmostEqual(b.iloc[-1]["A"], row[[c for c in inside if c != "A"]].mean(), places=12)
        # a non-member and BTC are led by all the members
        self.assertAlmostEqual(b.iloc[-1]["F"], row[inside].mean(), places=12)
        self.assertAlmostEqual(b.iloc[-1]["BTC"], row[inside].mean(), places=12)
        self.assertTrue(b.iloc[0].isna().all())                # no return on the first bar

    def test_alone_in_the_basket_has_no_leader(self):
        p = hourly_panel(n=5)
        members = pd.DataFrame(False, index=p.index, columns=p.coins)
        members["A"] = True
        b = factors.peer_basket(p, members)
        self.assertTrue(np.isnan(b.iloc[-1]["A"]))
        self.assertAlmostEqual(b.iloc[-1]["B"], ops.returns(p.close, 1).iloc[-1]["A"], places=12)

    def test_unscaled_gap_ranks_exactly_as_reversal(self):
        p = hourly_panel()
        members = pd.DataFrame(True, index=p.index, columns=p.coins)
        gap = ops.where_valid(factors.gap_peers(p, members, scaled=False), members.assign(BTC=False))
        rev = ops.where_valid(factors.rev_1(p), members.assign(BTC=False))
        pd.testing.assert_frame_equal(ops.cs_rank(gap).iloc[1:], ops.cs_rank(rev).iloc[1:])


class TestPush(unittest.TestCase):
    def test_push_is_beta_times_the_leader_move(self):
        p = hourly_panel(n=300)
        r = ops.returns(p.close, 1)
        p.close["X"] = p.close["ETH"].iloc[0] * (1 + 2 * r["ETH"].fillna(0)).cumprod()   # exactly 2x ETH
        for f in ("open", "high", "low", "volume"):
            getattr(p, f)["X"] = p.close["X"] if f != "volume" else 1e4
        f = factors.push(p, 1, 168, "ETH")
        rx = ops.returns(p.close, 1)
        self.assertAlmostEqual(f.iloc[-1]["X"], 2 * rx.iloc[-1]["ETH"], places=10)
        self.assertTrue(f["ETH"].isna().all())
        self.assertTrue(f.iloc[:168]["X"].isna().all())         # no beta before a full window

    def test_push_peers_ranks_by_beta_after_an_up_hour(self):
        p = hourly_panel(n=400)
        members = pd.DataFrame(True, index=p.index, columns=p.coins)
        f = factors.push_peers(p, members)
        up = factors.peer_basket(p, members).iloc[200:]["A"] > 0
        row = f.iloc[200:][up.to_numpy()].iloc[-1].drop("BTC")
        # betas rise from A to F, so after an up hour the order is A < ... < F
        self.assertEqual(list(row.sort_values().index), ["ETH", "A", "B", "C", "D", "E", "F"])

    def test_peer_factors_are_causal(self):
        p = hourly_panel(n=400)
        members = pd.DataFrame(True, index=p.index, columns=p.coins)
        cut = p.slice(None, p.index[300])
        for fn in (lambda q, m: factors.push_peers(q, m), lambda q, m: factors.gap_peers(q, m),
                   lambda q, m: factors.push(q, 1, 168, "ETH")):
            full = fn(p, members).loc[:p.index[300]]
            part = fn(cut, members.loc[:p.index[300]])
            pd.testing.assert_frame_equal(full, part)


class TestFamaMacBeth(unittest.TestCase):
    def test_recovers_the_signal_and_ignores_the_noise(self):
        rng = np.random.default_rng(3)
        idx = pd.date_range("2025-01-01", periods=200, freq="h")
        cols = [f"c{i}" for i in range(20)]
        x = pd.DataFrame(rng.normal(size=(200, 20)), index=idx, columns=cols)
        z = pd.DataFrame(rng.normal(size=(200, 20)), index=idx, columns=cols)
        fwd = 0.5 * x + pd.DataFrame(rng.normal(size=(200, 20)), index=idx, columns=cols)
        coef = fe.fama_macbeth(fwd, {"x": x, "z": z})
        sx, sz = fe.summarize(coef["x"]), fe.summarize(coef["z"])
        self.assertGreater(sx.t, 20)
        self.assertLess(abs(sz.t), 3)

    def test_a_control_that_explains_everything_takes_the_credit(self):
        rng = np.random.default_rng(4)
        idx = pd.date_range("2025-01-01", periods=200, freq="h")
        cols = [f"c{i}" for i in range(20)]
        ctrl = pd.DataFrame(rng.normal(size=(200, 20)), index=idx, columns=cols)
        sig = ctrl + 0.3 * pd.DataFrame(rng.normal(size=(200, 20)), index=idx, columns=cols)
        fwd = ctrl.copy()
        coef = fe.fama_macbeth(fwd, {"sig": sig, "ctrl": ctrl})
        self.assertGreater(fe.summarize(coef["ctrl"]).mean, 0.9)
        self.assertLess(abs(fe.summarize(coef["sig"]).mean), 0.05)

    def test_thin_dates_are_skipped(self):
        idx = pd.date_range("2025-01-01", periods=3, freq="h")
        a = pd.DataFrame([[1.0, 2, 3, 4, 5, 6], [1, 2, np.nan, np.nan, np.nan, np.nan], [6, 5, 4, 3, 2, 1]],
                         index=idx)
        coef = fe.fama_macbeth(a, {"x": a})
        self.assertEqual(list(coef.index), [idx[0], idx[2]])


class TestPastWindow(unittest.TestCase):
    def test_fetch_ends_at_the_given_time_and_drops_the_bar_opening_there(self):
        end = dt.datetime(2025, 10, 27, tzinfo=dt.timezone.utc)
        calls = []

        def page(product, gran, start, stop):
            calls.append((start, stop))
            t0, t1 = int(start.timestamp()), int(stop.timestamp())
            return [[t, 1, 2, 1.5, 1.5, 10] for t in range(t0, t1 + 1, gran)]   # `end` inclusive, as Coinbase

        with mock.patch.object(data, "fetch_page", side_effect=page), mock.patch.object(data.time, "sleep"):
            df = data.fetch("ETH-USD", 2, 3600, end=end)
        self.assertEqual(calls[0][0], end - dt.timedelta(days=2))
        self.assertEqual(calls[-1][1], end)
        self.assertEqual(len(df), 48)
        self.assertEqual(pd.Timestamp(df["time"].iloc[-1]), pd.Timestamp("2025-10-26 23:00", tz="UTC"))


class TestMinTrain(unittest.TestCase):
    def test_evaluate_passes_min_train_to_the_split(self):
        p = hourly_panel(n=1200)
        t = fe.evaluate(p, names=["rev_1"], horizon=3, n_splits=4, embargo=24, min_train=720)
        first_test = pd.Timestamp(t.attrs["splits"][0][2])
        self.assertGreaterEqual(first_test, p.index[720].normalize())
        self.assertEqual(len(t.attrs["test_dates"]), 1200 - 720)


if __name__ == "__main__":
    unittest.main(verbosity=2)


HAVE_RICH = importlib.util.find_spec("rich") is not None


class TestScanSaysWhy(unittest.TestCase):
    @unittest.skipUnless(HAVE_RICH, "tui extra not installed")
    def test_the_scan_says_why_btc_is_its_only_leader(self):
        import contextlib
        import io

        from espero import cli
        from espero import fast as fst
        buf = io.StringIO()
        with mock.patch.object(fst, "scan", return_value=[]), \
                mock.patch.object(fst, "source_feed", return_value=(None, None)), \
                contextlib.redirect_stdout(buf):
            self.assertEqual(cli.main(["scan", "--products", "ETH", "--once"]), 0)
        text = " ".join(buf.getvalue().split())
        self.assertIn("RESULTS_PEERS.md", text)
        self.assertIn("BTC is the only leader", text)
