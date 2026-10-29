"""`espero` with no arguments: an interactive home screen.

Status panels on top, an arrow-key menu below, one action per choice. Every
action is something the plain CLI can also do; this is a front door, not a
second implementation. The real account databases are only written by the
actions that say so (run the daily job, deposit, pause).

Needs the `tui` extra:  pip install -e ".[tui]"   (rich + questionary)
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

try:
    import questionary
    from questionary import Style
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
except ImportError:  # pragma: no cover - the CLI explains how to install
    questionary = None  # type: ignore[assignment]

ACCENT = "#d97757"          # the orange of the pointer
MUTED = "grey58"

# the mascot: the Claude Code blob, stretched into a dog, looking right.
MASCOT = [
    "▗▄▄▄▄▄▄▄▐▛██▜▌ ",
    "▝▜██████▜████▛▘",
    "  ▘▘ ▝▝  ▘▘ ▝▝ ",
]
STYLE = None
if questionary is not None:
    STYLE = Style([
        ("qmark", f"fg:{ACCENT} bold"),
        ("question", "bold"),
        ("pointer", f"fg:{ACCENT} bold"),
        ("highlighted", f"fg:{ACCENT} bold"),
        ("selected", f"fg:{ACCENT}"),
        ("answer", f"fg:{ACCENT} bold"),
        ("instruction", "fg:#8b8f94"),
    ])


# ------------------------------------------------------------------ reading
def _latest(db: Path, table: str) -> Optional[dict]:
    if not db.exists():
        return None
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    try:
        row = con.execute(f"SELECT * FROM {table} ORDER BY ts DESC, id DESC LIMIT 1").fetchone()
    except sqlite3.OperationalError:
        row = None
    finally:
        con.close()
    return dict(row) if row else None


def _history(db: Path, table: str, limit: int = 15) -> List[dict]:
    if not db.exists():
        return []
    con = sqlite3.connect(f"file:{Path(db).resolve()}?mode=ro", uri=True)   # read-only
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(f"SELECT * FROM {table} ORDER BY ts DESC, id DESC LIMIT ?", (limit,)).fetchall()
    except sqlite3.OperationalError:
        rows = []
    finally:
        con.close()
    return [dict(r) for r in rows]


def _health(state: Path) -> dict:
    p = state / "health.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except ValueError:
        return {}


def _date(ts) -> str:
    try:
        return datetime.fromtimestamp(int(ts), timezone.utc).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError):
        return "-"


def _ago(iso: Optional[str]) -> str:
    if not iso:
        return "never"
    try:
        then = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    hours = (datetime.now(timezone.utc) - then).total_seconds() / 3600
    if hours < 1:
        return f"{int(hours * 60)} min ago"
    if hours < 48:
        return f"{hours:.0f} h ago"
    return f"{hours / 24:.0f} d ago"


BARS = "▁▂▃▄▅▆▇█"


def sparkline(values: List[float], width: int = 32) -> str:
    """Unicode bars for the last `width` values. Flat series renders as a line."""
    vals = [float(v) for v in values][-width:]
    if not vals:
        return ""
    lo, hi = min(vals), max(vals)
    if hi - lo < 1e-9:
        return BARS[3] * len(vals)
    return "".join(BARS[min(7, int((v - lo) / (hi - lo) * 7.999))] for v in vals)


def pnl_curve(rows: List[dict]) -> List[float]:
    """Equity minus cumulative contributions, oldest first: the curve the
    rules earned, not the one deposits drew."""
    out, cum = [], 0.0
    for r in sorted(rows, key=lambda r: (int(r["ts"]), int(r.get("id") or 0))):
        cum += float(r.get("deposit") or 0.0)
        out.append(float(r["equity"]) - cum)
    return out


def next_rebalance(state: Path, now: Optional[datetime] = None) -> Dict[str, str]:
    """Human text for when each rule next trades, from its own calendar."""
    from . import tsmom as tsm
    from . import xs as xsm
    now = now or datetime.now(timezone.utc)
    out = {}
    d = now
    for _ in range(8):
        if d.date() > now.date() and xsm.is_rebalance_day(d):
            break
        d = d + timedelta(days=1)
    days = (d.date() - now.date()).days
    out["xs"] = f"Monday {d.strftime('%b %-d')}" + (" (tomorrow)" if days == 1 else f" (in {days} d)")

    tdb = state / "tsmom.db"
    done = False
    if tdb.exists():
        try:
            done = tsm.Account(tdb).rebalanced_in_month(now.year, now.month)
        except Exception:  # noqa: BLE001 - a broken db must not break the header
            done = False
    d = now
    for _ in range(40):
        if d.date() > now.date() and tsm.first_trading_day(d) and not (
                done and (d.year, d.month) == (now.year, now.month)):
            break
        d = d + timedelta(days=1)
    days = (d.date() - now.date()).days
    out["tsmom"] = f"{d.strftime('%b %-d')}" + (" (tomorrow)" if days == 1 else f" (in {days} d)")
    return out


def costs_line(state: Path, which: str) -> str:
    from . import tca
    from . import tsmom as tsm
    from . import xs as xsm
    if which == "tsmom":
        t = tca.account_tca(state / "tsmom.db", "account", tsm.COST)
    else:
        t = tca.account_tca(state / "xs.db", "xs_account", xsm.COST)
    if not t.n:
        return "no trades yet"
    return (f"{t.n} trades · ${t.total_cost:,.2f} in costs · turnover {t.turnover_per_year:.1f}x/yr · "
            f"drag {100 * t.drag_per_year:.1f}%/yr")


# ----------------------------------------------------------------- rendering
def header(state: Path) -> Panel:
    h = _health(state)
    t = _latest(state / "tsmom.db", "account")
    x = _latest(state / "xs.db", "xs_account")
    m = _latest(state / "mf.db", "mf_account")
    mh = _latest(state / "mf-hl.db", "mf_account")
    total = sum(float(r["equity"]) for r in (t, x, m, mh) if r)
    paused = (state / "KILL").exists()

    line1 = Text()
    line1.append("espero", style="bold")
    line1.append("  paper accounts  ", style=MUTED)
    line1.append(f"${total:,.2f}", style=f"bold {ACCENT}")
    if paused:
        line1.append("   PAUSED (KILL file)", style="bold red")

    line2 = Text()
    if h:
        ok = h.get("ok")
        line2.append("last run ", style=MUTED)
        line2.append(_ago(h.get("last_run")))
        line2.append("  ·  ", style=MUTED)
        line2.append("ok" if ok else "FAILED", style="green" if ok else "bold red")
        line2.append("  ·  last success ", style=MUTED)
        line2.append(_ago(h.get("last_success")))
        bad = [k for k, v in (h.get("steps") or {}).items() if not v.get("ok")]
        if bad:
            line2.append(f"  ·  failing: {', '.join(bad)}", style="red")
    else:
        line2.append(f"no run recorded yet  ·  launchd runs daily at {daily_time()}", style=MUTED)
    line2.append(f"  ·  next run {daily_time()} local", style=MUTED)

    try:
        nxt = next_rebalance(state)
        line3 = Text()
        line3.append("rebalances  ", style=MUTED)
        line3.append(f"XS {nxt['xs']}")
        line3.append("  ·  ", style=MUTED)
        line3.append(f"TSMOM {nxt['tsmom']}")
    except Exception as exc:  # noqa: BLE001
        line3 = Text(f"rebalance calendar unavailable: {exc}", style=MUTED)

    art = Text("\n".join(MASCOT), style=f"bold {ACCENT}")
    body = Text.assemble(line1, "\n", line2, "\n", line3)
    grid = Table.grid(padding=(0, 2))
    grid.add_column(no_wrap=True)
    grid.add_column()
    grid.add_row(art, body)
    return Panel(grid, border_style=MUTED, padding=(0, 1))


def _account_row(rows: List[dict]) -> Tuple[str, Text, Text, str]:
    """equity, delta since the previous mark, P&L vs contributions, sparkline."""
    latest = rows[-1]
    eq = float(latest["equity"])
    curve = pnl_curve(rows)
    delta = Text("")
    if len(rows) >= 2:
        d = eq - float(rows[-2]["equity"]) - float(latest.get("deposit") or 0.0)
        delta = Text(f"{d:+,.2f}", style="green" if d > 0 else ("red" if d < 0 else MUTED))
    deposited = sum(float(r.get("deposit") or 0.0) for r in rows)
    pnl = eq - deposited
    pnl_t = Text(f"{pnl:+,.2f} ({100 * pnl / deposited:+.2f}%)" if deposited else f"{pnl:+,.2f}",
                 style="green" if pnl > 0 else ("red" if pnl < 0 else MUTED))
    return f"${eq:,.2f}", delta, pnl_t, sparkline(curve)


def accounts_table(state: Path) -> Table:
    tbl = Table(show_header=True, header_style=MUTED, box=None, padding=(0, 2), expand=False)
    for col, just in (("account", "left"), ("equity", "right"), ("day", "right"), ("P&L", "right"),
                      ("curve", "left"), ("holds", "left")):
        tbl.add_column(col, justify=just)

    rows = _history(state / "tsmom.db", "account", limit=400)
    if rows:
        rows = list(reversed(rows))
        t = rows[-1]
        pos = {k: v for k, v in json.loads(t.get("positions") or "{}").items() if v > 0}
        holds = ", ".join(sorted(pos)) or "all cash"
        cash_w = 1 - sum(pos.values()) / max(float(t["equity"]), 1e-9)
        eq, delta, pnl, spark = _account_row(rows)
        tbl.add_row("TSMOM  monthly trend", eq, delta, pnl, Text(spark, style=ACCENT),
                    f"{holds}  · cash {100 * cash_w:.0f}% in {t.get('vehicle') or 'USD'}")
    else:
        tbl.add_row("TSMOM  monthly trend", "-", "", "", "", "not started")

    rows = _history(state / "xs.db", "xs_account", limit=400)
    if rows:
        rows = list(reversed(rows))
        x = rows[-1]
        pos = {k: v for k, v in json.loads(x.get("positions") or "{}").items() if v > 0}
        holds = ", ".join(sorted(pos)) or "all cash"
        eq, delta, pnl, spark = _account_row(rows)
        tbl.add_row("XS     weekly top-10", eq, delta, pnl, Text(spark, style=ACCENT), holds)
    else:
        tbl.add_row("XS     weekly top-10", "-", "", "", "", "not started")

    for db, label in (("mf.db", "#8     multifactor fwd"), ("mf-hl.db", "#8 HL  shadow (info)")):
        rows = _history(state / db, "mf_account", limit=400)
        if rows:
            from . import mf
            rows = list(reversed(rows))
            pos = {k: v for k, v in json.loads(rows[-1].get("positions") or "{}").items() if v > 0}
            holds = ", ".join(sorted(pos)) or f"cash until its first fill {mf.FORWARD_START.date()}"
            eq, delta, pnl, spark = _account_row(rows)
            tbl.add_row(label, eq, delta, pnl, Text(spark, style=ACCENT), holds)
    return tbl


def decision_table(state: Path, which: str) -> Table:
    """The last decision, as the bot saw it: signal, target, current, action.
    Read from the stored row, never recomputed."""
    db, table = (("tsmom.db", "account") if which == "tsmom" else ("xs.db", "xs_account"))
    row = _latest(state / db, table)
    title = f"{which} · last decision"
    tbl = Table(title=title, box=None, header_style=MUTED, padding=(0, 2))
    for col, just in (("asset", "left"), ("signal", "right"), ("target", "right"), ("current $", "right"),
                      ("target $", "right"), ("action", "left")):
        tbl.add_column(col, justify=just)
    if not row:
        tbl.add_row("-", "", "", "", "", "no decision stored yet")
        return tbl
    sig = {k: float(v) for k, v in json.loads(row.get("signals") or "{}").items()}
    w = {k: float(v) for k, v in json.loads(row.get("weights") or "{}").items()}
    pos = {k: float(v) for k, v in json.loads(row.get("positions") or "{}").items()}
    equity = float(row["equity"])
    label = "52w" if which == "tsmom" else "7d"
    tbl.columns[1].header = label
    names = sorted(set(sig) | set(w) | set(pos), key=lambda a: (-(w.get(a, 0.0)), -sig.get(a, 0.0)))
    if which == "xs":
        names = [a for a in names if w.get(a, 0.0) > 0 or pos.get(a, 0.0) > 0][:15] or names[:15]
    for a in names:
        cur, tgt = pos.get(a, 0.0), w.get(a, 0.0) * equity
        delta = tgt - cur
        act = "hold" if abs(delta) < max(0.01 * equity, 0.5) else ("buy" if delta > 0 else "sell")
        style = "green" if act == "buy" else ("red" if act == "sell" else MUTED)
        tbl.add_row(a, f"{100 * sig[a]:+.1f}%" if a in sig else "",
                    f"{100 * w.get(a, 0.0):.0f}%", f"{cur:,.2f}", f"{tgt:,.2f}",
                    Text(f"{act} {abs(delta):,.2f}" if act != "hold" else "hold", style=style))
    cash = equity - sum(pos.values())
    tbl.add_row("cash", "", f"{100 * cash / max(equity, 1e-9):.0f}%", f"{cash:,.2f}", "", "")
    tbl.caption = (f"as of {_date(row['ts'])} · {row.get('note') or ''} · {costs_line(state, which)}")
    return tbl


def history_table(state: Path, which: str) -> Table:
    db, table = (("tsmom.db", "account") if which == "tsmom" else ("xs.db", "xs_account"))
    rows = _history(state / db, table)
    tbl = Table(title=f"{which} · last {len(rows)} rows", box=None, header_style=MUTED, padding=(0, 2))
    for col in ("date", "equity", "note", "deposit", "traded"):
        tbl.add_column(col, justify="right" if col in ("equity", "deposit", "traded") else "left")
    for r in rows:
        tbl.add_row(_date(r["ts"]), f"{float(r['equity']):,.2f}", r.get("note") or "",
                    f"{float(r.get('deposit') or 0):,.2f}", f"{float(r.get('traded') or 0):,.2f}")
    return tbl


# ------------------------------------------------------------------- actions
def _python() -> List[str]:
    return [sys.executable, "-m", "espero"]


def _run(console: "Console", args: List[str], cwd: Path) -> int:
    console.print(Text(f"$ espero {' '.join(args)}", style=MUTED))
    try:
        return subprocess.run(_python() + args, cwd=cwd).returncode
    except KeyboardInterrupt:
        console.print(Text("stopped", style=MUTED))
        return 130


def act_status(console, state):
    console.print(accounts_table(state))
    for which in ("tsmom", "xs"):
        console.print(Text(f"{which:6s} costs: {costs_line(state, which)}", style=MUTED))
    h = _health(state)
    if h.get("steps"):
        tbl = Table(title="last run", box=None, header_style=MUTED, padding=(0, 2))
        for col in ("step", "ok", "seconds", "note / error"):
            tbl.add_column(col)
        for k, v in h["steps"].items():
            tbl.add_row(k, Text("yes", style="green") if v.get("ok") else Text("NO", style="bold red"),
                        f"{v.get('seconds', 0):.1f}", v.get("error") or v.get("note") or "")
        console.print(tbl)


def act_dashboard(console, state):
    _run(console, ["dashboard", "-o", str(state / "dashboard.html"), "--tsmom-db", str(state / "tsmom.db"),
                   "--xs-db", str(state / "xs.db"), "--open"], state)


def act_daily(console, state):
    if not questionary.confirm("Run the daily job now? (writes a mark to the real accounts)",
                               default=False, style=STYLE).ask():
        return
    _run(console, ["daily", "--state-dir", str(state)], state)


def act_why(console, state):
    which = questionary.select("Which account?", choices=["tsmom", "xs"], style=STYLE,
                               pointer="❯").ask()
    if which:
        console.print(decision_table(state, which))


def act_history(console, state):
    which = questionary.select("Which account?", choices=["tsmom", "xs"], style=STYLE,
                               pointer="❯").ask()
    if which:
        console.print(history_table(state, which))


def act_preview(console, state):
    """What each rule would decide right now, without writing anything."""
    from . import tsmom as tsm
    from . import xs as xsm
    with console.status("fetching prices ...", spinner="dots"):
        series = tsm.load_series("2y")
        sig = tsm.signals(series)
        w, cash_w = tsm.target_weights(sig)
        prices, errors = xsm.load_prices()
        fresh, stale = xsm.split_stale(prices)
        xsig = xsm.signals(fresh)
        xw = xsm.targets(xsig)
    tbl = Table(title="TSMOM · if it rebalanced now", box=None, header_style=MUTED, padding=(0, 2))
    for col, just in (("asset", "left"), ("52w", "right"), ("target", "right")):
        tbl.add_column(col, justify=just)
    for a, v in sig.items():
        tbl.add_row(a, f"{100 * v:+.1f}%", f"{100 * w[a]:.0f}%")
    tbl.add_row("cash", "", f"{100 * cash_w:.0f}%")
    console.print(tbl)
    tbl = Table(title=f"XS · if it rebalanced now ({len(fresh)}/{len(xsm.UNIVERSE)} rankable)",
                box=None, header_style=MUTED, padding=(0, 2))
    for col, just in (("coin", "left"), ("7d", "right"), ("weight", "right")):
        tbl.add_column(col, justify=just)
    for c, v in sorted(xsig.items(), key=lambda kv: -kv[1])[:xsm.TOP]:
        tbl.add_row(c, f"{100 * v:+.1f}%", f"{100 * xw[c]:.0f}%")
    console.print(tbl)
    if errors or stale:
        console.print(Text(f"{len(errors)} coins failed to load, {len(stale)} stale", style="yellow"))
    console.print(Text("nothing was written", style=MUTED))


def act_pause(console, state):
    kill = state / "KILL"
    if kill.exists():
        if questionary.confirm("Resume? (remove the KILL file)", default=True, style=STYLE).ask():
            kill.unlink()
            console.print(Text("resumed", style="green"))
    else:
        if questionary.confirm("Pause everything? (create the KILL file)", default=False, style=STYLE).ask():
            kill.write_text("paused from espero ui\n")
            console.print(Text("paused", style="yellow"))


def act_deposit(console, state):
    which = questionary.select("Deposit into which account?", choices=["tsmom", "xs"], style=STYLE,
                               pointer="❯").ask()
    if not which:
        return
    amount = questionary.text("Amount in USD:", style=STYLE).ask()
    try:
        amt = float(amount)
    except (TypeError, ValueError):
        console.print(Text("not a number", style="red"))
        return
    if amt <= 0:
        return
    if questionary.confirm(f"Deposit ${amt:,.2f} into the REAL {which} paper account?", default=False,
                           style=STYLE).ask():
        _run(console, [which, "--state", str(state / f"{which}.db"), "--deposit", f"{amt}"], state)


def act_paper(console, state):
    product = questionary.text("Product:", default="BTC-USD", style=STYLE).ask() or "BTC-USD"
    console.print(Text("ctrl-c returns to the menu; state is kept in /tmp", style=MUTED))
    _run(console, ["paper", "--product", product, "--state", f"/tmp/paper-{product.lower()}.db",
                   "--loop", "--interval", "60"], state)


def act_board(console, state):
    _run(console, ["board", "--state-dir", str(state)], state)


def act_scan(console, state):
    _run(console, ["scan", "--state-dir", str(state)], state)


def act_fast(console, state):
    product = questionary.text("Product:", default="ETH-USD", style=STYLE).ask() or "ETH-USD"
    venue = questionary.select("Charge whose maker fee?", choices=["binanceus", "kraken", "coinbase"],
                               default="coinbase", style=STYLE, pointer="❯").ask() or "coinbase"
    console.print(Text("paper only · Enter places, n declines, k kills, q returns here", style=MUTED))
    _run(console, ["fast", "--product", product, "--venue", venue, "--state-dir", str(state)], state)


def daily_time(plist: Path = Path.home() / "Library" / "LaunchAgents" / "com.espero.daily.plist") -> str:
    """HH:MM of the installed daily job (its StartCalendarInterval), 07:30 if unreadable."""
    try:
        import plistlib
        with open(plist, "rb") as fh:
            cal = plistlib.load(fh).get("StartCalendarInterval") or {}
        if isinstance(cal, list):
            cal = cal[0] if cal else {}
        return f"{int(cal.get('Hour', 7)):02d}:{int(cal.get('Minute', 30)):02d}"
    except (OSError, ValueError, TypeError, AttributeError):
        return "07:30"


def act_degen(console, state):
    what = questionary.select("打板 — altcoins breaking out on volume (paper, hypothesis #10)",
                              choices=["scan: who is moving right now", "paper: run the 5m loop",
                                       "backtest: last 30 days"],
                              style=STYLE, pointer="❯").ask()
    if not what:
        return
    source = questionary.select("Coin list and prices from?", choices=["hyperliquid", "coinbase"],
                                default="hyperliquid", style=STYLE, pointer="❯").ask() or "hyperliquid"
    hl = source == "hyperliquid"
    venue = "hyperliquid" if hl else "binanceus"
    if not what.startswith("backtest"):         # the backtest replays every venue's fees side by side
        venue = questionary.select("Charge whose taker fee?",
                                   choices=["hyperliquid", "binanceus", "kraken", "coinbase", "perp"],
                                   default=venue, style=STYLE, pointer="❯").ask() or venue
    src = ["--source", source]
    if what.startswith("scan"):
        _run(console, ["degen", "scan", *src, "--venue", venue], state)
    elif what.startswith("paper"):
        # degen.db is the #10 forward test (Coinbase bars, Binance.US fees); every other
        # source and venue gets its own book
        if hl:
            db = "degen-hl.db" if venue == "hyperliquid" else f"degen-hl-{venue}.db"
        else:
            db = "degen.db" if venue == "binanceus" else f"degen-{venue}.db"
        console.print(Text(f"ctrl-c returns to the menu; state is kept in {db} here", style=MUTED))
        _run(console, ["degen", "paper", *src, "--venue", venue, "--state", str(state / db), "--loop"], state)
    else:
        console.print(Text("fetches 17 days of 5m Hyperliquid bars for 60 coins the first time (its 5,000-bar limit)"
                           if hl else "fetches 30 days of 5m candles for 60 coins the first time (about ten minutes)",
                           style=MUTED))
        _run(console, ["degen", "backtest", *src], state)


def act_factors(console, state):
    console.print(Text("builds or reuses data/panel, then evaluates the zoo (a minute or two)", style=MUTED))
    _run(console, ["factors"], state)


def act_tests(console, state):
    console.print(Text("$ python -m unittest discover -s tests -t .", style=MUTED))
    subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."], cwd=state)


def act_logs(console, state):
    log = Path(os.environ.get("ESPERO_LOG_DIR", Path.home() / "Library" / "Logs" / "espero")) / "daily.log"
    if not log.exists():
        console.print(Text(f"no log at {log}", style=MUTED))
        return
    lines = log.read_text().splitlines()[-30:]
    for ln in lines:
        style = "red" if " ERROR " in ln else ("yellow" if " WARNING " in ln else None)
        console.print(Text(ln, style=style))


MENU: List[Tuple[str, Callable]] = [
    ("Status & health", act_status),
    ("Open the dashboard", act_dashboard),
    ("Why: the last decision, as the bot saw it", act_why),
    ("Preview what each rule would do now (no writes)", act_preview),
    ("Signal board: 1/3/12-month trend, stocks to altcoins (scanner, no writes)", act_board),
    ("Account history", act_history),
    ("Run the daily job now", act_daily),
    ("Deposit paper capital", act_deposit),
    ("Pause / resume", act_pause),
    ("Show the log", act_logs),
    ("Scan: lead-lag signal across all coins, pick one to trade", act_scan),
    ("Fast screen: resting orders on the live book (semi-auto, paper)", act_fast),
    ("Watch the single-coin paper loop", act_paper),
    ("Degen altcoins: 打板 breakout scan, backtest, paper loop", act_degen),
    ("Factor IC table (research)", act_factors),
    ("Run the tests", act_tests),
    ("Quit", None),
]


def main(state: Optional[Path] = None) -> int:
    if questionary is None:
        print("the interactive screen needs the tui extra:  pip install -e '.[tui]'", file=sys.stderr)
        print("every action is also a plain command: espero --help", file=sys.stderr)
        return 2
    state = Path(state or ".").resolve()
    console = Console()
    empty = not any((state / name).exists() for name in ("tsmom.db", "xs.db", "mf.db", "health.json"))
    actions: Dict[str, Callable] = {label: fn for label, fn in MENU}
    while True:
        console.clear()
        console.print(header(state))
        console.print(accounts_table(state))
        if empty:
            console.print(Text(f"no accounts in {state}: start from the project folder or pass --state-dir",
                               style="bold yellow"))
        console.print()
        try:
            choice = questionary.select("What do you want to do?", choices=[m[0] for m in MENU],
                                        style=STYLE, pointer="❯", instruction="(↑↓ to move, enter to pick)",
                                        use_shortcuts=False).ask()
        except KeyboardInterrupt:
            return 0
        if choice is None or actions[choice] is None:
            return 0
        console.print()
        try:
            actions[choice](console, state)
        except KeyboardInterrupt:
            console.print(Text("stopped", style=MUTED))
        except Exception as exc:  # noqa: BLE001 - the menu must survive a broken action
            console.print(Text(f"{type(exc).__name__}: {exc}", style="bold red"))
        console.print()
        try:
            questionary.press_any_key_to_continue("press any key to return to the menu", style=STYLE).ask()
        except KeyboardInterrupt:
            return 0
