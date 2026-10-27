"""The home screen renders from the databases alone and never writes to them."""
from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from espero import tsmom, xs

try:
    from rich.console import Console

    from espero import ui
    HAVE_TUI = ui.questionary is not None
except ImportError:  # the tui extra is optional
    HAVE_TUI = False


@unittest.skipUnless(HAVE_TUI, "tui extra not installed")
class TestRender(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name)
        acc = tsmom.Account(self.state / "tsmom.db")
        acc.cash = 100.0
        px = pd.Series({"SPY": 10.0})
        acc.rebalance(px, {"SPY": 1 / 6})
        acc.save(1_700_000_000, acc.equity(px), {"SPY": 1 / 6}, "init", positions={"SPY": 16.6},
                 deposit=100.0, traded=16.6)
        x = xs.XSAccount(self.state / "xs.db")
        x.cash = 100.0
        x.rebalance(pd.Series({"A": 1.0, "B": 2.0}), {"A": 0.5, "B": 0.5})
        x.save(1_700_000_000, 99.9, {"A": 0.5, "B": 0.5}, {}, {"A": 49.95, "B": 49.95}, 100.0, "init")
        (self.state / "health.json").write_text(json.dumps({
            "last_run": "2026-10-27T09:45:38+00:00", "last_success": "2026-10-27T09:45:38+00:00",
            "ok": False, "steps": {"tsmom": {"ok": True, "seconds": 1.0, "note": "init"},
                                   "xs": {"ok": False, "seconds": 0.1, "error": "RuntimeError: x"}}}))

    def tearDown(self):
        self.tmp.cleanup()

    def render(self, *renderables) -> str:
        buf = io.StringIO()
        c = Console(file=buf, width=120, force_terminal=False)
        for r in renderables:
            c.print(r)
        return buf.getvalue()

    def test_header_shows_total_and_failing_step(self):
        out = self.render(ui.header(self.state))
        self.assertIn("$199.88", out.replace("\n", ""))
        self.assertIn("FAILED", out)
        self.assertIn("failing: xs", out)

    def test_paused_is_loud(self):
        (self.state / "KILL").write_text("")
        self.assertIn("PAUSED", self.render(ui.header(self.state)))

    def test_accounts_and_history_tables(self):
        out = self.render(ui.accounts_table(self.state), ui.history_table(self.state, "tsmom"),
                          ui.history_table(self.state, "xs"))
        self.assertIn("SPY", out)
        self.assertIn("2023-11-14", out)      # 1_700_000_000 as a date, not an epoch
        self.assertIn("init", out)

    def test_status_action_does_not_write(self):
        before = (self.state / "tsmom.db").read_bytes(), (self.state / "xs.db").read_bytes()
        c = Console(file=io.StringIO(), width=120)
        ui.act_status(c, self.state)
        ui.act_logs(c, self.state)
        after = (self.state / "tsmom.db").read_bytes(), (self.state / "xs.db").read_bytes()
        self.assertEqual(before, after)

    def test_empty_state_renders(self):
        with tempfile.TemporaryDirectory() as d:
            out = self.render(ui.header(Path(d)), ui.accounts_table(Path(d)))
        self.assertIn("not started", out)
        self.assertIn("no run recorded", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
