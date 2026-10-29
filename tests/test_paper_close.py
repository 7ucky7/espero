"""Manual close (take profit early): queued for the running loop and filled at the
next open as "manual", or closed at once when no loop holds the journal."""
from __future__ import annotations

import contextlib
import io
import unittest
from pathlib import Path

import espero.paper as paper_mod
from espero import cli
from espero.lock import JournalLock
from tests.test_paper import GRAN, PaperTestCase, ScriptedSignal, bar


class TestManualClose(PaperTestCase):
    def opened(self):
        t = self.trader()
        paper_mod.combine = ScriptedSignal(nth=1)
        self.prime(t)
        t.on_bar(bar(3, 100.0))                       # the BUY fills here
        self.assertIsNotNone(t.position)
        return t

    def test_queued_then_filled_at_the_next_open(self):
        t = self.opened()
        self.assertEqual(t.request_close(bar(3, 0)["ts"]), "queued manual SELL for the next open")
        self.assertIsNotNone(t.position, "nothing fills before the next bar")
        events = t.on_bar(bar(4, 108.0, 109.0))
        self.assertTrue(any("filled SELL (manual) @ 108.00" in e for e in events), events)
        self.assertIsNone(t.position)
        row = t.journal.closed_positions()[-1]
        self.assertEqual((row["reason"], row["exit_px"]), ("manual", 108.0))

    def test_nothing_to_close_and_no_double_sell(self):
        t = self.trader()
        self.assertEqual(t.request_close(1), "manual close: no open position")
        t = self.opened()
        t.request_close(bar(3, 0)["ts"])
        self.assertIn("already queued", t.request_close(bar(3, 0)["ts"]))

    def test_close_now_books_fee_and_slippage(self):
        self.cfg.fee, self.cfg.slippage = 0.001, 0.0005
        t = self.opened()
        entry = t.position
        event = t.close_now(110.0, bar(4, 0)["ts"])
        px = 110.0 * (1 - 0.0005)
        self.assertIn(f"exit manual @ {px:.2f}", event)
        row = t.journal.closed_positions()[-1]
        self.assertAlmostEqual(row["pnl"], (px - entry.entry_px) * entry.size - px * entry.size * 0.001
                               - entry.entry_fee)


class TestCommand(PaperTestCase):
    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["paper-close", "--state", str(self.db), *argv])
        return code, out.getvalue()

    def test_with_a_loop_running_it_leaves_a_request(self):
        t = TestManualClose.opened(self)
        t.journal.close()
        with JournalLock(self.db):                     # the running loop holds the journal
            code, text = self.run_cli()
        self.assertEqual(code, 0)
        self.assertIn("queued: it sells at the next bar's open", text)
        self.assertTrue(Path(str(self.db) + ".close").exists())

    def test_without_a_loop_it_closes_now_at_the_last_close(self):
        t = TestManualClose.opened(self)
        t.journal.close()
        code, text = self.run_cli()
        self.assertEqual(code, 0)
        self.assertIn("exit manual @ 99.95", text)                # the usual 5 bps slippage
        from espero.journal import Journal
        j = Journal(self.db)
        self.assertEqual(j.open_positions(), [])
        self.assertEqual(j.closed_positions()[-1]["reason"], "manual")
        j.close()

    def test_the_loop_picks_up_the_request(self):
        t = TestManualClose.opened(self)
        t.journal.close()
        Path(str(self.db) + ".close").write_text("x")
        args = cli.build_parser().parse_args(["paper", "--product", self.cfg.product, "--state", str(self.db),
                                              "--granularity", str(GRAN), "--fee-bps", "0"])
        from unittest import mock

        import pandas as pd
        nxt = bar(4, 105.0)
        df = pd.DataFrame([dict(nxt, dt=pd.Timestamp(nxt["ts"], unit="s", tz="UTC"))])
        with mock.patch("espero.data.recent_closed_bars", return_value=df), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            cli._paper_loop(args)
        self.assertIn("queued manual SELL", out.getvalue())
        self.assertIn("filled SELL (manual) @ 104.95", out.getvalue())   # next open less slippage
        self.assertFalse(Path(str(self.db) + ".close").exists())


if __name__ == "__main__":
    unittest.main()
