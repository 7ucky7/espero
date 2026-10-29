"""`espero carry screen`: #12's forward test on one screen. Read-only.

Three parts, each answering a question the loops' logs make you dig for:

* **the loops**: is each launchd agent running, how often launchd has restarted
  it, and which hour its book booked last (scripts/install-carry-launchd.sh)
* **the books**: taker and maker side by side. Both see the same funding, so the
  gap between them is what maker execution has been worth, the forward test's
  question (research/PREREGISTRATION_CARRY2.md)
* **funding now**: every coin of the loops' universe against the 15% entry bar, on
  the trailing-week mean the rule enters and exits on, with this hour's rate beside it

The books are read from private copies (`board.copied`): the loops own the files.
"""
from __future__ import annotations

import datetime as dt
import os
import re
import sqlite3
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

import numpy as np

from . import board, carry
from . import carry_paper as cp
from . import hyperliquid as hl

BOOKS = ("taker", "maker")
FORWARD_DAYS = 30            # PREREGISTRATION_CARRY2.md: a 30-day forward paper test
IDLE_ANN = 0.1095            # 0.01% per 8 hours, an idle Hyperliquid market's funding
NEAR = (IDLE_ANN + carry.ENTER_ANN) / 2   # "near": past halfway from an idle market to the bar
STALE_S = 2 * 3600           # a book whose last hour is older than this has stopped booking
LOG_DIR = Path(os.environ.get("ESPERO_LOG_DIR", Path.home() / "Library" / "Logs" / "espero"))
INSTALLER = Path(__file__).resolve().parents[1] / "scripts" / "install-carry-launchd.sh"


def label(costs: str) -> str:
    return f"com.espero.carry-{costs}"


def log_path(costs: str, log_dir: Path = LOG_DIR) -> Path:
    return Path(log_dir) / f"carry-{costs}.log"


# ---------------------------------------------------------------- the loops
def parse_launchctl(text: str) -> dict:
    """The job's own fields from `launchctl print`, read from its top level only:
    nested sections repeat `state`."""
    found: Dict[str, str] = {}
    for key, val in re.findall(r"^\t(state|pid|runs|last exit code) = (.*)$", text, re.M):
        found.setdefault(key, val.strip())

    def num(k):
        v = found.get(k, "")
        return int(v) if v.isdigit() else None

    return {"loaded": True, "state": found.get("state", "?"), "pid": num("pid"), "runs": num("runs"),
            "last_exit": found.get("last exit code")}


def agent(costs: str, run: Callable = subprocess.run) -> dict:
    """The launchd agent of one book, or {"loaded": False}."""
    try:
        p = run(["launchctl", "print", f"gui/{os.getuid()}/{label(costs)}"],
                capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return {"loaded": False}
    return parse_launchctl(p.stdout) if p.returncode == 0 else {"loaded": False}


# ---------------------------------------------------------------- the books
def book(path: Path) -> Optional[dict]:
    """One book's summary, open hedges, testnet mirror counts and last events, read
    from a copy; None if there is no book."""
    with board.copied(Path(path)) as dst:
        if dst is None:
            return None
        with sqlite3.connect(dst) as probe:
            costs = probe.execute("SELECT value FROM meta WHERE key='costs'").fetchone()
        b = cp.CarryBook(dst, costs=costs[0] if costs else "maker")
        try:
            s = b.summary()
            s["last_ts"] = b.last_ts()
            s["open_positions"] = [{"coin": p["coin"], "since": p["entry_ts"],
                                    "leg": p["qty_spot"] * p["spot_entry"], "funding": p["funding"]}
                                   for p in b.open_positions()]
            try:
                rows = b.db.execute("SELECT open_oid, open_status FROM testnet_mirror").fetchall()
            except sqlite3.OperationalError:
                rows = None
            if rows is None:
                s["mirror"] = None
            else:
                placed = [r for r in rows if r["open_oid"]]
                s["mirror"] = {"placed": len(placed), **{k: sum(1 for r in placed if r["open_status"] == k)
                                                         for k in ("filled", "part", "resting", "cancelled")}}
            s["events"] = [dict(e) for e in b.events(3)]
        finally:
            b.close()
    return s


# -------------------------------------------------------------- funding now
@dataclass
class Funding:
    coin: str
    week: float          # trailing 168-hour mean, annualised: what the rule enters and exits on
    now: float           # this hour's rate, annualised
    error: str = ""

    @property
    def state(self) -> str:
        if self.error:
            return "error"
        if not np.isfinite(self.week):
            return "new"                     # under a week of history: the rule cannot rank it
        if self.week > carry.ENTER_ANN:
            return "ENTER"
        return "near" if self.week >= NEAR else ""


def funding(coins: Optional[List[str]] = None, top: int = 20, fetch=None, now: Optional[float] = None,
            workers: int = 4) -> List[Funding]:
    """Each coin of the loops' universe (`carry_paper.universe`: the top `top` perps by
    open interest with a Coinbase spot pair) with its trailing-week and current funding,
    annualised, highest week first. Always mainnet."""
    post = fetch or (lambda body: hl.post(body, hl.info_url(testnet=False)))
    coins = cp.universe(top, fetch=post) if coins is None else coins
    rate = {c["coin"]: c["funding"] for c in hl.asset_contexts(fetch=post)}
    now_s = int(time.time() if now is None else now)
    start_ms = (now_s - (carry.LOOKBACK_H + 4) * 3600) * 1000

    def one(coin: str) -> Funding:
        current = float(rate.get(coin, np.nan)) * carry.HOURS_PER_YEAR
        try:
            f = hl.funding_history(coin, start_ms, fetch=post, pages=2, sleep=lambda s: None)
        except Exception as exc:  # noqa: BLE001 - one coin's outage is a row, not a crash
            return Funding(coin, float("nan"), current, f"{type(exc).__name__}: {exc}")
        last = f["funding"].tail(carry.LOOKBACK_H) if len(f) else f
        week = float(last.mean() * carry.HOURS_PER_YEAR) if len(last) >= carry.LOOKBACK_H else float("nan")
        return Funding(coin, week, current)

    with ThreadPoolExecutor(workers) as ex:
        rows = list(ex.map(one, coins))
    return sorted(rows, key=lambda r: -r.week if np.isfinite(r.week) else np.inf)


# ---------------------------------------------------------------- the screen
def gather(state_dir: Path, top: int = 20, with_funding: bool = True, run: Callable = subprocess.run,
           fetch=None, now: Optional[float] = None) -> dict:
    fund: List[Funding] = []
    error = None
    if with_funding:
        try:
            fund = funding(top=top, fetch=fetch, now=now)
        except Exception as exc:  # noqa: BLE001 - the books still show without the market
            error = f"{type(exc).__name__}: {exc}"
    return {"books": {c: book(Path(state_dir) / f"carry-{c}.db") for c in BOOKS},
            "agents": {c: agent(c, run) for c in BOOKS}, "funding": fund, "funding_error": error,
            "with_funding": with_funding, "now": int(time.time() if now is None else now)}


def _date(ts: int) -> str:
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%d")


def _ago(seconds: float) -> str:
    m = int(max(seconds, 0) // 60)
    return f"{m} min ago" if m < 120 else f"{m // 60} h ago"


def header(v: dict) -> List[str]:
    firsts = [b["first_ts"] for b in v["books"].values() if b and b.get("first_ts")]
    lines = ["#12 funding carry: the forward test (paper; the maker book mirrors its short leg on the "
             "Hyperliquid testnet)"]
    if firsts:
        start = min(firsts)
        day = (v["now"] - start) // 86400 + 1
        lines.append(f"day {day} of {FORWARD_DAYS}: {_date(start)} -> {_date(start + FORWARD_DAYS * 86400)}")
    else:
        lines.append("no hour booked yet")
    return lines


def loop_rows(v: dict) -> List[List[str]]:
    """Per book: the launchd loop, its restarts, and the settlement hour it booked last
    (a healthy loop books each hour within about 20 minutes of it)."""
    rows = []
    for c in BOOKS:
        a, b = v["agents"][c], v["books"][c]
        if not a.get("loaded"):
            loop = "stopped"
        elif a.get("pid"):
            loop = f"running (pid {a['pid']})"
        else:
            loop = f"{a.get('state', '?')} (last exit {a.get('last_exit')})"
        restarts = "" if not a.get("runs") else str(a["runs"] - 1)
        last = (b or {}).get("last_ts")
        if b is None:
            when = "no book"
        elif last is None:
            when = "none yet"
        else:
            when = f"{cp.stamp(last)[11:]} UTC, {_ago(v['now'] - last)}"
            if v["now"] - last > STALE_S:
                when += " STALE"
        rows.append([c, loop, restarts, when])
    return rows


def book_rows(v: dict) -> List[List[str]]:
    rows = []
    for c in BOOKS:
        b = v["books"][c]
        if b is None:
            continue
        rows.append([c, f"${b['equity']:,.2f}", f"{b['pnl']:+,.2f}", f"{b['funding']:+,.2f}", f"{b['fees']:,.2f}",
                     str(b["open"]), str(b["closed"])])
    return rows


LOOP_HEADERS = ["book", "loop", "restarts", "last hour booked"]
BOOK_HEADERS = ["book", "equity", "P&L", "funding", "fees", "open", "closed"]
FUNDING_HEADERS = ["coin", "7-day avg (the rule)", "this hour", "to the 15% bar", "state"]


def notes(v: dict) -> List[str]:
    out = []
    t, m = v["books"]["taker"], v["books"]["maker"]
    if t and m:
        out.append(f"maker - taker so far: {m['equity'] - t['equity']:+,.2f}, what maker execution has been worth "
                   f"(the question the forward test answers)")
    if m and m.get("mirror") is not None:
        mi = m["mirror"]
        out.append("testnet mirror: no orders yet" if not mi["placed"] else
                   f"testnet mirror: {mi['placed']} shorts placed, {mi['filled']} filled, {mi['part']} partial, "
                   f"{mi['resting']} resting, {mi['cancelled']} cancelled")
    for c in BOOKS:
        for p in (v["books"][c] or {}).get("open_positions", []):
            out.append(f"{c}: {p['coin']} hedged since {cp.stamp(p['since'])} UTC, ${p['leg']:,.2f} a leg, "
                       f"funding {p['funding']:+,.2f}")
    if any(not v["agents"][c].get("loaded") for c in BOOKS):
        out.append(f"a loop is stopped: start both with \"{INSTALLER}\"")
    return out


def funding_rows(v: dict, limit: int = 10) -> List[List[str]]:
    rows = []
    for f in v["funding"][:limit]:
        week = "" if not np.isfinite(f.week) else f"{f.week:+.1%}"
        gap = "" if not np.isfinite(f.week) else f"{100 * (f.week - carry.ENTER_ANN):+.1f} pts"
        rows.append([f.coin, week, "" if not np.isfinite(f.now) else f"{f.now:+.1%}", gap,
                     f.state if not f.error else f"error: {f.error[:40]}"])
    return rows


def funding_note(v: dict) -> str:
    if v["funding_error"]:
        return f"funding unavailable: {v['funding_error']}"
    above = sum(1 for f in v["funding"] if f.state == "ENTER")
    return (f"{above} of {len(v['funding'])} coins above the bar. The rule opens a hedge when a coin's 7-day average "
            f"funding is above {carry.ENTER_ANN:.0%} a year and closes it below {carry.EXIT_ANN:.0%}; an idle "
            f"market pays {IDLE_ANN:.2%}.")


def _plain_table(headers: List[str], rows: List[List[str]]) -> List[str]:
    widths = [max(len(h), *(len(r[i]) for r in rows)) if rows else len(h) for i, h in enumerate(headers)]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    return [fmt.format(*headers)] + [fmt.format(*r) for r in rows]


def format_plain(v: dict) -> str:
    out = header(v) + [""] + _plain_table(LOOP_HEADERS, loop_rows(v)) + [""] + \
        _plain_table(BOOK_HEADERS, book_rows(v)) + [""] + notes(v)
    if v["with_funding"]:
        out += ["", "funding now, the loops' universe:"] + _plain_table(FUNDING_HEADERS, funding_rows(v))
        out.append(funding_note(v))
    return "\n".join(out)


def renderables(v: dict) -> list:
    """The same content as rich tables (rich is optional)."""
    from rich.table import Table
    from rich.text import Text

    muted = "grey58"
    out: list = [Text(header(v)[0], style="bold"), Text(header(v)[1], style=muted)]
    t = Table(title="the loops", title_style=muted, box=None, header_style=muted, padding=(0, 2))
    for h in LOOP_HEADERS:
        t.add_column(h, justify="right" if h == "restarts" else "left")
    for r in loop_rows(v):
        t.add_row(r[0], Text(r[1], style="green" if r[1].startswith("running") else "bold red"), r[2],
                  Text(r[3], style="bold red" if r[3].endswith("STALE") else ""))
    b = Table(title="the books", title_style=muted, box=None, header_style=muted, padding=(0, 2))
    for h in BOOK_HEADERS:
        b.add_column(h, justify="left" if h == "book" else "right")
    for r in book_rows(v):
        b.add_row(*r)
    out += [t, b]
    out += [Text(n, style="bold red" if n.startswith("a loop is stopped") else muted) for n in notes(v)]
    if v["with_funding"]:
        f = Table(title="funding now, the loops' universe", title_style=muted, box=None, header_style=muted,
                  padding=(0, 2))
        for h in FUNDING_HEADERS:
            f.add_column(h, justify="left" if h in ("coin", "state") else "right")
        for r in funding_rows(v):
            f.add_row(*r[:4], Text(r[4], style="bold green" if r[4] == "ENTER" else
                                   "yellow" if r[4] == "near" else muted))
        out += [f, Text(funding_note(v), style=muted)]
    return out
