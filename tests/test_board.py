"""`espero board`: #15's trend readings as a read-only scanner."""
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from espero import board, mf, trend
from espero import carry_paper as cp

HAVE_RICH = importlib.util.find_spec("rich") is not None    # the tui extra is optional
WED = pd.Timestamp("2026-03-04")                             # a Wednesday: the week was read on Monday


def yahoo_like(dates, close) -> pd.DataFrame:
    """What data.yahoo_daily(adjusted=True) returns."""
    close = np.asarray(close, dtype=float)
    stamps = pd.DatetimeIndex(dates).tz_localize("UTC")
    return pd.DataFrame({"dt": stamps, "ts": [int(t.timestamp()) for t in stamps], "open": close,
                         "high": close, "low": close, "close": close, "volume": 1e9, "adj_close": close})


def series(kind, drift, start="2024-06-03", end="2026-03-03"):
    dates = pd.bdate_range(start, end) if kind == "etf" else pd.date_range(start, end, freq="D")
    i = np.arange(len(dates))
    return yahoo_like(dates, 100 * np.exp(drift * i + 0.004 * (-1.0) ** i))


class TestHelpers(unittest.TestCase):
    def test_week_and_next_reading(self):
        self.assertEqual(board.week_start(WED), pd.Timestamp("2026-03-02"))
        self.assertEqual(board.next_decision(WED), pd.Timestamp("2026-03-09"))
        self.assertEqual(board.next_decision(pd.Timestamp("2026-03-09 11:30")), pd.Timestamp("2026-03-09"))

    def test_change_labels(self):
        self.assertEqual(board.change(0.0, 1 / 3), "UP")
        self.assertEqual(board.change(2 / 3, 0.0), "DOWN")
        self.assertEqual(board.change(1 / 3, 1.0), "stronger")
        self.assertEqual(board.change(1.0, 2 / 3), "weaker")
        self.assertEqual(board.change(1.0, 1.0), "")
        self.assertEqual(board.change(None, 1.0), "")


class TestView(unittest.TestCase):
    def setUp(self):
        get = {"SPY": series("etf", 0.001), "TLT": series("etf", -0.001),
               "BTC-USD": series("coin", 0.002), "ADA-USD": series("coin", -0.002)}
        self.frames, self.errors = board.fetch_frames(
            ["SPY", "TLT", "BTC-USD", "ADA-USD", "QQQ"],
            fetch=lambda s: get[s] if s in get else (_ for _ in ()).throw(RuntimeError("no such symbol")))

    def test_fetch_keeps_failures_as_errors(self):
        self.assertEqual(set(self.frames), {"SPY", "TLT", "BTC-USD", "ADA-USD"})
        self.assertIn("QQQ", self.errors)

    def test_rows_show_trend_and_flip_but_no_size(self):
        v = board.view(self.frames, WED)
        rows = {ln.symbol: ln for ln in v["lines"]}
        self.assertEqual(rows["SPY"].arrows, "▲▲▲")
        self.assertEqual(rows["TLT"].arrows, "▽▽▽")
        self.assertEqual((rows["SPY"].today, rows["TLT"].today), ("3/3", "0/3"))
        self.assertTrue(rows["SPY"].flip.startswith(("1m ↓", "3m ↓", "12m ↓")))
        self.assertTrue(rows["TLT"].flip.startswith(("1m ↑", "3m ↑", "12m ↑")))
        self.assertEqual(rows["QQQ"].flip, "no data")
        self.assertEqual(rows["SPY"].change, "")                       # 3/3 on Monday and today
        self.assertEqual(rows[trend.ALTS].arrows, "0/1 up")            # ADA is eligible and falling
        self.assertNotIn("ADA-USD", rows)
        self.assertIn("ADA-USD", {ln.symbol for ln in board.view(self.frames, WED, alts=True)["lines"]})
        text = board.format_plain(v)
        self.assertIn("FAIL", text)
        self.assertIn("no sizes", text)
        self.assertNotIn("$", text)

    def test_a_coin_without_yesterdays_bar_says_stale(self):
        late = {s: df for s, df in self.frames.items()}
        for s in ("BTC-USD", "ADA-USD"):                                # Yahoo has not posted Tuesday yet
            late[s] = late[s].drop(WED - pd.Timedelta(days=1))
        rows = {ln.symbol: ln for ln in board.view(late, WED)["lines"]}
        self.assertEqual(rows["BTC-USD"].change, "stale")
        self.assertEqual((rows[trend.ALTS].arrows, rows[trend.ALTS].change), ("0/0 up", "1 stale"))

    def test_prices_read_like_prices(self):
        self.assertEqual([board.price(x) for x in (80810.4, 772.31, 0.000629, None)],
                         ["80,810", "772.31", "0.000629", "-"])

    @unittest.skipUnless(HAVE_RICH, "tui extra not installed")
    def test_rich_table_renders(self):
        import io

        from rich.console import Console
        buf = io.StringIO()
        Console(file=buf, width=160).print(board.table(board.view(self.frames, WED)))
        self.assertIn("SPY", buf.getvalue())


class TestContext(unittest.TestCase):
    def test_reads_the_running_tests_without_writing(self):
        with tempfile.TemporaryDirectory() as d:
            acc = mf.MFAccount(Path(d) / "mf.db", cash=100.0)
            acc.save(1, 100.0, {}, {}, 100.0, "init", {}, 0.0)
            acc.close()
            book = cp.CarryBook(Path(d) / "carry-maker.db", costs="maker", initial=500.0)
            book.on_hour(3600 * 10, {"A": cp.Row(funding=1e-5, f_ann=0.01, perp=101.0, spot=100.0)})
            book.close()
            before = {p.name: p.read_bytes() for p in Path(d).iterdir()}
            lines = board.context(Path(d))
            after = {p.name: p.read_bytes() for p in Path(d).iterdir()}
        self.assertEqual(before, after)                                   # read-only, byte for byte
        self.assertTrue(any(line.startswith("#8 multifactor") and "in cash" in line for line in lines))
        self.assertTrue(any(line.startswith("#12 carry maker") and "$500.00" in line for line in lines))
        self.assertFalse(any("taker" in line for line in lines))          # no file, no line

    def test_reads_a_database_a_writer_holds_open(self):
        with tempfile.TemporaryDirectory() as d:
            acc = mf.MFAccount(Path(d) / "mf.db", cash=100.0)       # WAL mode, connection kept open
            acc.save(1, 101.0, {"BTC": 0.1}, {}, 100.0, "rebalance", {}, 0.0)
            self.assertTrue((Path(d) / "mf.db-wal").exists())
            before = {p.name: p.read_bytes() for p in Path(d).iterdir()}
            lines = board.context(Path(d))
            after = {p.name: p.read_bytes() for p in Path(d).iterdir()}
            acc.close()
        self.assertEqual(before, after)
        self.assertIn("holding BTC", lines[0])                       # the committed row, from the WAL

    def test_missing_state_dir_is_quiet(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(board.context(Path(d) / "nowhere"), [])


if __name__ == "__main__":
    unittest.main()
