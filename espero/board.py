"""`espero board`: the daily look at #15's trend readings. Read-only.

For every asset in the trend rule (research/PREREGISTRATION_TREND.md): whether
it is above its close of 1, 3 and 12 months ago, how that compares with this
week's Monday reading, and the nearest price that would flip a lookback at the
next decision. Two context lines show the tests still running, #8 (mf.db) and
#12 (carry-*.db), opened read-only.

#15 FAILED its pre-registered test (research/RESULTS_TREND.md): the timing
added no return beyond sizing positions by volatility. So this is a scanner,
not a signal: it shows trends and the prices that would change them, never a
position size, and it sends no alerts.

It writes nothing: prices go to a temporary cache deleted on exit, and the
databases are read from copies, since SQLite writes a WAL database's side
files even when it is opened read-only.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional, Tuple

import pandas as pd

from . import data, trend

VERDICT = "FAIL — the timing added no return beyond volatility sizing (research/RESULTS_TREND.md)"
SPAN = "2y"                             # > 364 days of lookback plus 60 of volatility
WORKERS = 6
LABELS = dict(zip(trend.HORIZONS, ("1m", "3m", "12m")))


@dataclass
class Line:
    symbol: str
    cls: str
    last: Optional[float]               # raw close
    arrows: str                         # ▲/▽ for 1m 3m 12m
    week: str                           # share of lookbacks up at this week's Monday reading
    today: str                          # the same, if the week ended today
    change: str
    flip: str


def week_start(today) -> pd.Timestamp:
    d = trend.cutoff(today)
    return d - pd.Timedelta(days=d.weekday())


def next_decision(today) -> pd.Timestamp:
    d = trend.cutoff(today)
    return d + pd.Timedelta(days=(7 - d.weekday()) % 7)


def price(x: Optional[float]) -> str:
    if x is None:
        return "-"
    return f"{x:,.0f}" if x >= 1000 else f"{x:,.2f}" if x >= 1 else f"{x:.4g}"


def _share(f: Optional[float]) -> str:
    return "-" if f is None else f"{round(3 * f)}/3"


def change(before: Optional[float], after: Optional[float]) -> str:
    if before is None or after is None or before == after:
        return ""
    if before == 0:
        return "UP"
    if after == 0:
        return "DOWN"
    return "stronger" if after > before else "weaker"


def fetch_frames(symbols: List[str], fetch: Callable[[str], pd.DataFrame] = None,
                 workers: int = WORKERS) -> Tuple[Dict[str, pd.DataFrame], Dict[str, str]]:
    """Adjusted daily bars for `symbols`, fetched in parallel into a throwaway cache."""
    frames: Dict[str, pd.DataFrame] = {}
    errors: Dict[str, str] = {}
    with tempfile.TemporaryDirectory() as tmp:
        def default(sym: str) -> pd.DataFrame:
            if trend.kind(sym) == "crypto":          # coins from Hyperliquid's perps, ETFs from Yahoo
                from . import hyperliquid as hl
                return hl.daily(sym, SPAN)
            return data.yahoo_daily(sym, SPAN, cache_dir=Path(tmp), adjusted=True)
        get = fetch or default

        def one(sym: str):
            try:
                return sym, trend.to_frame(get(sym)), None
            except Exception as exc:  # noqa: BLE001 - one bad symbol is a row, not a crash
                return sym, None, f"{type(exc).__name__}: {exc}"

        with ThreadPoolExecutor(workers) as ex:
            for sym, df, err in ex.map(one, symbols):
                if df is not None and not df.empty:
                    frames[sym] = df
                else:
                    errors[sym] = err or "empty"
    return frames, errors


def nearest_flip(df: Optional[pd.DataFrame], today, sym: str, last: Optional[float]) -> str:
    """The closest price that would change a lookback at the next decision."""
    if df is None or last is None:
        return ""
    levels = trend.flip_levels(df, today, next_decision(today), trend.kind(sym))
    if not levels:
        return ""
    h, lvl = min(levels.items(), key=lambda kv: abs(kv[1] / last - 1))
    return f"{LABELS[h]} {'↓' if last > lvl else '↑'} {price(lvl)} ({100 * (lvl / last - 1):+.1f}%)"


def view(frames: Dict[str, pd.DataFrame], today, alts: bool = False) -> dict:
    """Everything the board prints, from complete bars only."""
    week = trend.decide(frames, week_start(today))
    now = trend.decide(frames, today)
    lines: List[Line] = []
    for sym, v in now.views.items():
        if v.member == trend.ALTS and not alts:
            continue
        if not v.refs:
            lines.append(Line(sym, v.cls, v.last_raw, "···", "-", "-", "", v.why or "no data"))
            continue
        arrows = "".join("▲" if v.last > v.refs[h] else "▽" for h in trend.HORIZONS)
        f0 = week.views[sym].f if sym in week.views else None
        lines.append(Line(sym, v.cls, v.last_raw, arrows, _share(f0), _share(v.f),
                          v.why or change(f0, v.f), nearest_flip(frames.get(sym), today, sym, v.last_raw)))
    if not alts:
        members = [v for v in now.views.values() if v.member == trend.ALTS]
        el = [v for v in members if v.eligible]
        stale = sum(1 for v in members if v.why == "stale")
        up = sum(1 for v in el if (v.f or 0) > 0)
        lines.append(Line(trend.ALTS, "crypto", None, f"{up}/{len(el)} up", "", "",
                          f"{stale} stale" if stale else "", "--alts lists them"))
    return {"today": trend.cutoff(today), "week": week.asof, "next": next_decision(today), "lines": lines}


# --------------------------------------------------------------- context rows
@contextmanager
def _copy(path: Path) -> Iterator[Optional[sqlite3.Connection]]:
    """A connection to a private copy of `path` (and its -wal, so committed rows not yet
    checkpointed are included). Opening the original, even with mode=ro, would let SQLite
    create or update its -wal/-shm files beside a database another process owns."""
    path = Path(path)
    if not path.exists():
        yield None
        return
    with tempfile.TemporaryDirectory() as tmp:
        dst = Path(tmp) / path.name
        shutil.copyfile(path, dst)
        wal = path.with_name(path.name + "-wal")
        if wal.exists():
            shutil.copyfile(wal, dst.with_name(dst.name + "-wal"))
        con = sqlite3.connect(dst, timeout=2.0)
        con.row_factory = sqlite3.Row
        try:
            yield con
        finally:
            con.close()


def context(state_dir: Path) -> List[str]:
    """One line each for the forward tests still running, read from copies."""
    out = []
    try:
        with _copy(Path(state_dir) / "mf.db") as con:
            row = con.execute("SELECT equity, note, weights FROM mf_account "
                              "ORDER BY ts DESC, id DESC LIMIT 1").fetchone() if con else None
        if row:
            held = sorted(json.loads(row["weights"] or "{}"))
            out.append(f"#8 multifactor alts (mf.db): ${row['equity']:,.2f} ({row['note']}); "
                       + (f"holding {', '.join(held)}" if held else "in cash until its first Monday"))
    except (sqlite3.Error, OSError) as exc:
        out.append(f"#8 mf.db unreadable: {exc}")
    for costs in ("taker", "maker"):
        try:
            with _copy(Path(state_dir) / f"carry-{costs}.db") as con:
                row = con.execute("SELECT ts, equity, open FROM hours ORDER BY ts DESC LIMIT 1").fetchone() \
                    if con else None
            if row:
                out.append(f"#12 carry {costs} (carry-{costs}.db): ${row['equity']:,.2f}, {row['open']} open, "
                           f"last hour {pd.Timestamp(row['ts'], unit='s'):%Y-%m-%d %H:%M} UTC")
        except (sqlite3.Error, OSError) as exc:
            out.append(f"#12 carry-{costs}.db unreadable: {exc}")
    return out


# ------------------------------------------------------------------- printing
def header(v: dict) -> List[str]:
    return [f"#15 multi-asset trend: {VERDICT}",
            "A scanner, not a signal: no sizes, no alerts.",
            f"bars through {(v['today'] - pd.Timedelta(days=1)).date()}; week read on {v['week'].date()}; "
            f"next reading {v['next'].date()}",
            "▲/▽: above/below the close 1, 3 and 12 months ago. Nearest flip: the close at the next reading "
            "that turns that lookback down (↓) or up (↑). ETFs: Yahoo, dividend-adjusted. Coins: Hyperliquid perps "
            "(a coin it does not list reads 'no data'). stale: no fresh bar yet."]


def format_plain(v: dict) -> str:
    out = header(v) + ["", f"{'class':<12}{'asset':<10}{'last':>12}  {'1m 3m 12m':<11}{'week':>5}{'today':>6}  "
                           f"{'change':<9}nearest flip"]
    for ln in v["lines"]:
        last = price(ln.last)
        out.append(f"{ln.cls:<12}{ln.symbol:<10}{last:>12}  {ln.arrows:<11}{ln.week:>5}{ln.today:>6}  "
                   f"{ln.change:<9}{ln.flip}")
    return "\n".join(out)


def table(v: dict):
    """The same content as a rich Table (rich is optional)."""
    from rich.table import Table

    head = header(v)
    t = Table(title=head[0], caption=" · ".join(head[1:]))
    for name, justify in (("class", "left"), ("asset", "left"), ("last", "right"), ("1m 3m 12m", "center"),
                          ("week", "right"), ("today", "right"), ("change", "left"), ("nearest flip", "left")):
        t.add_column(name, justify=justify)
    for ln in v["lines"]:
        t.add_row(ln.cls, ln.symbol, price(ln.last), ln.arrows,
                  ln.week, ln.today, ln.change, ln.flip)
    return t
