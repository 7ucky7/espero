"""The carry screen: launchd's view of the loops, the books read from copies,
funding against the bar, and the menu entry that replaced 打板."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from espero import carry
from espero import carry_paper as cp
from espero import carry_view as cv

HAVE_TUI = all(importlib.util.find_spec(m) for m in ("rich", "questionary"))
T0 = 1_793_246_400            # a settlement hour

RUNNING = """gui/501/com.espero.carry-taker = {
\tactive count = 1
\ttype = LaunchAgent
\tstate = running

\truns = 2
\tpid = 616
\tlast exit code = (never exited)
\tjetsam properties = {
\t\tstate = active
\t}
}
"""
CRASHED = "gui/501/com.espero.carry-maker = {\n\tstate = not running\n\truns = 3\n\tlast exit code = 1\n}\n"


class TestLoops(unittest.TestCase):
    def test_reads_the_jobs_own_fields_not_nested_ones(self):
        a = cv.parse_launchctl(RUNNING)
        self.assertEqual((a["state"], a["pid"], a["runs"], a["last_exit"]),
                         ("running", 616, 2, "(never exited)"))
        b = cv.parse_launchctl(CRASHED)
        self.assertEqual((b["state"], b["pid"], b["runs"], b["last_exit"]), ("not running", None, 3, "1"))

    def test_an_unknown_job_is_not_loaded(self):
        calls = []

        def run(args, **kw):
            calls.append(args)
            return subprocess.CompletedProcess(args, 113, stdout="", stderr="Could not find service")
        self.assertEqual(cv.agent("maker", run=run), {"loaded": False})
        self.assertTrue(calls[0][2].endswith("/com.espero.carry-maker"))


def make_book(path: Path, costs="maker", hours=2, mirror=False) -> None:
    b = cp.CarryBook(path, costs=costs)
    for k in range(hours):
        b.on_hour(T0 + 3600 * k, {"SOL": cp.Row(funding=0.0001, f_ann=0.30, perp=100.0, spot=100.0)})
    if mirror:
        from espero.hl_exchange import MIRROR_SCHEMA
        b.db.executescript(MIRROR_SCHEMA)
        b.db.execute("INSERT INTO testnet_mirror (position_id, coin, open_oid, open_status) "
                     "VALUES (1, 'SOL', 7, 'filled')")
        b.db.commit()
    b.close()


class TestBooks(unittest.TestCase):
    def test_a_book_is_read_from_a_copy(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "carry-maker.db"
            make_book(path, mirror=True)
            before = (path.read_bytes(), path.stat().st_mtime_ns, sorted(p.name for p in Path(d).iterdir()))
            s = cv.book(path)
            after = (path.read_bytes(), path.stat().st_mtime_ns, sorted(p.name for p in Path(d).iterdir()))
        self.assertEqual(before, after)
        self.assertEqual((s["costs"], s["open"], s["last_ts"]), ("maker", 1, T0 + 3600))
        self.assertEqual(s["open_positions"][0]["coin"], "SOL")
        self.assertGreater(s["funding"], 0)
        self.assertEqual(s["mirror"], {"placed": 1, "filled": 1, "part": 0, "resting": 0, "cancelled": 0})

    def test_no_book_and_no_mirror(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(cv.book(Path(d) / "carry-taker.db"))
            make_book(Path(d) / "carry-taker.db", costs="taker")
            self.assertIsNone(cv.book(Path(d) / "carry-taker.db")["mirror"])


def fake_hl(rates):
    """metaAndAssetCtxs and fundingHistory for coins with constant hourly `rates`
    (None: the coin errors; an int count: that many rows only)."""
    def post(body):
        if body["type"] == "metaAndAssetCtxs":
            names = list(rates)
            return [{"universe": [{"name": n} for n in names]},
                    [{"markPx": "1", "funding": "0.0000125", "openInterest": "1", "dayNtlVlm": "1"} for _ in names]]
        spec = rates[body["coin"]]
        if spec is None:
            raise RuntimeError("HTTP 500")
        if body["startTime"] > T0 * 1000:
            return []
        if isinstance(spec, list):                      # explicit rates, oldest first
            seq = spec
        else:
            rate, n = spec if isinstance(spec, tuple) else (spec, 200)
            seq = [rate] * n
        return [{"coin": body["coin"], "fundingRate": str(r), "time": (T0 - 3600 * (len(seq) - 1 - i)) * 1000}
                for i, r in enumerate(seq)]
    return post


class TestFunding(unittest.TestCase):
    def test_the_rule_reads_the_trailing_week(self):
        rates = {"HOT": 0.00002, "WARM": 0.000015, "IDLE": 0.0000125, "NEW": (0.001, 10), "BAD": None}
        rows = cv.funding(coins=list(rates), fetch=fake_hl(rates), now=T0 + 600)
        by = {r.coin: r for r in rows}
        self.assertAlmostEqual(by["HOT"].week, 0.00002 * carry.HOURS_PER_YEAR)
        self.assertEqual([by[c].state for c in ("HOT", "WARM", "IDLE", "NEW", "BAD")],
                         ["ENTER", "near", "", "new", "error"])
        self.assertAlmostEqual(by["IDLE"].now, 0.0000125 * carry.HOURS_PER_YEAR)   # this hour's rate
        self.assertEqual([r.coin for r in rows[:3]], ["HOT", "WARM", "IDLE"])         # highest week first

    def test_only_the_last_week_counts(self):
        rates = {"COOLED": [0.001] * 40 + [0.00001] * carry.LOOKBACK_H}     # hot a while ago, idle this week
        row = cv.funding(coins=["COOLED"], fetch=fake_hl(rates), now=T0 + 600)[0]
        self.assertAlmostEqual(row.week, 0.00001 * carry.HOURS_PER_YEAR)
        self.assertEqual(row.state, "")

    def test_near_starts_halfway_from_idle_to_the_bar(self):
        self.assertAlmostEqual(cv.NEAR, (0.1095 + carry.ENTER_ANN) / 2)
        self.assertEqual(cv.Funding("X", 0.1095, 0.1095).state, "")


def view(now=T0 + 1800, taker_last=T0, maker_running=True):
    def b(costs, equity, last):
        return {"costs": costs, "equity": equity, "pnl": equity - 500, "funding": 1.0, "fees": 0.2, "open": 1,
                "closed": 0, "first_ts": T0 - 86400, "last_ts": last, "mirror": None if costs == "taker" else
                {"placed": 0, "filled": 0, "part": 0, "resting": 0, "cancelled": 0},
                "open_positions": [{"coin": "SOL", "since": T0, "leg": 125.0, "funding": 1.0}], "events": []}
    return {"books": {"taker": b("taker", 500.0, taker_last), "maker": b("maker", 501.5, T0)},
            "agents": {"taker": {"loaded": True, "state": "running", "pid": 616, "runs": 2},
                       "maker": {"loaded": True, "state": "running", "pid": 617, "runs": 1} if maker_running
                       else {"loaded": False}},
            "funding": [cv.Funding("ZRO", 0.16, 0.11), cv.Funding("BTC", 0.103, 0.1095)],
            "funding_error": None, "with_funding": True, "now": now}


class TestScreen(unittest.TestCase):
    def test_the_plain_screen(self):
        text = cv.format_plain(view())
        for s in ("day 2 of 30", "running (pid 616)", "restarts", "maker - taker so far: +1.50",
                  "testnet mirror: no orders yet", "maker: SOL hedged since", "1 of 2 coins above the bar",
                  "+1.0 pts", "ENTER"):
            self.assertIn(s, text)
        self.assertNotIn("STALE", text)
        self.assertNotIn("a loop is stopped", text)

    def test_a_stale_book_and_a_stopped_loop_are_called_out(self):
        text = cv.format_plain(view(now=T0 + 3 * 3600, taker_last=T0 - 3600, maker_running=False))
        self.assertIn("STALE", text)
        self.assertIn("stopped", text)
        self.assertIn(f'start both with "{cv.INSTALLER}"', text)

    @unittest.skipUnless(HAVE_TUI, "tui extra not installed")
    def test_the_rich_screen_says_the_same(self):
        from rich.console import Console
        console = Console(record=True, width=100)
        for r in cv.renderables(view()):
            console.print(r)
        text = console.export_text()
        for s in ("the loops", "the books", "running (pid 616)", "funding now", "ENTER"):
            self.assertIn(s, text)

    def test_the_command_reads_the_books_without_the_network(self):
        from espero import cli
        with tempfile.TemporaryDirectory() as d:
            make_book(Path(d) / "carry-maker.db")
            out = io.StringIO()
            with mock.patch.object(cv, "agent", return_value={"loaded": False}), \
                    mock.patch.object(cv, "funding", side_effect=AssertionError("network")), \
                    mock.patch.dict("sys.modules", {"rich.console": None}), contextlib.redirect_stdout(out):
                self.assertEqual(cli.main(["carry", "screen", "--no-funding", "--state-dir", d]), 0)
        text = out.getvalue()
        self.assertIn("maker", text)
        self.assertIn("a loop is stopped", text)


@unittest.skipUnless(HAVE_TUI, "tui extra not installed")
class TestMenu(unittest.TestCase):
    def test_the_carry_action_shows_the_screen_and_offers_to_start_stopped_loops(self):
        from espero import ui
        ran, offered = [], []

        def select(title, choices, **kw):
            offered.append(choices)
            return mock.Mock(ask=lambda: "Back to the menu")
        with mock.patch.object(ui, "_run", side_effect=lambda c, args, cwd: ran.append(args) or 0), \
                mock.patch.object(ui.questionary, "select", side_effect=select), \
                mock.patch.object(cv, "agent", side_effect=lambda c: {"loaded": False} if c == "maker"
                                  else {"loaded": True, "pid": 1}):
            ui.act_carry(mock.Mock(), Path("/state"))
        self.assertEqual(ran, [["carry", "screen", "--state-dir", "/state"]])
        self.assertIn("Start the loops (maker stopped)", offered[0])
        self.assertIn("Follow the maker log", offered[0])

    def test_carry_replaced_the_breakout_entry(self):
        from espero import ui
        names = [name for name, _ in ui.MENU]
        self.assertTrue(any(n.startswith("Carry (#12)") for n in names))
        self.assertFalse(any("打板" in n for n in names))
        self.assertFalse(hasattr(ui, "act_degen"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
