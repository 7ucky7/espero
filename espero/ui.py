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
from datetime import datetime, timezone
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

# the mascot: a dog in profile, facing right. Ear up, nose forward, tail behind.
MASCOT = [
    r"         __     ",
    r"  (___()'`;     ",
    r"  /,    /`      ",
    "  " + "\\" * 2 + '"--' + "\\" * 2 + "      ",
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
    con = sqlite3.connect(db)
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


# ----------------------------------------------------------------- rendering
def header(state: Path) -> Panel:
    h = _health(state)
    t = _latest(state / "tsmom.db", "account")
    x = _latest(state / "xs.db", "xs_account")
    total = sum(float(r["equity"]) for r in (t, x) if r)
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
        line2.append("no run recorded yet  ·  launchd runs daily at 07:30", style=MUTED)
    line2.append("  ·  next 07:30 local", style=MUTED)

    art = Text("\n".join(MASCOT), style=f"bold {ACCENT}")
    body = Text.assemble(line1, "\n", line2)
    grid = Table.grid(padding=(0, 2))
    grid.add_column(no_wrap=True)
    grid.add_column()
    grid.add_row(art, Text.assemble("\n", body))
    return Panel(grid, border_style=MUTED, padding=(0, 1))


def accounts_table(state: Path) -> Table:
    tbl = Table(show_header=True, header_style=MUTED, box=None, padding=(0, 2), expand=False)
    tbl.add_column("account")
    tbl.add_column("equity", justify="right")
    tbl.add_column("as of")
    tbl.add_column("last action")
    tbl.add_column("holds")

    t = _latest(state / "tsmom.db", "account")
    if t:
        pos = {k: v for k, v in json.loads(t.get("positions") or "{}").items() if v > 0}
        holds = ", ".join(sorted(pos)) or "all cash"
        cash_w = 1 - sum(pos.values()) / max(float(t["equity"]), 1e-9)
        tbl.add_row("TSMOM  monthly trend", f"${float(t['equity']):,.2f}", _date(t["ts"]),
                    t.get("note") or "", f"{holds}  · cash {100 * cash_w:.0f}% in {t.get('vehicle') or 'USD'}")
    else:
        tbl.add_row("TSMOM  monthly trend", "-", "-", "not started", "")

    x = _latest(state / "xs.db", "xs_account")
    if x:
        pos = {k: v for k, v in json.loads(x.get("positions") or "{}").items() if v > 0}
        holds = ", ".join(sorted(pos)) or "all cash"
        tbl.add_row("XS     weekly top-10", f"${float(x['equity']):,.2f}", _date(x["ts"]),
                    x.get("note") or "", holds)
    else:
        tbl.add_row("XS     weekly top-10", "-", "-", "not started", "")
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


def act_factors(console, state):
    console.print(Text("builds or reuses data/panel, then evaluates the zoo (a minute or two)", style=MUTED))
    _run(console, ["factors"], state)


def act_tests(console, state):
    console.print(Text("$ python -m unittest discover -s tests -t .", style=MUTED))
    subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], cwd=state)


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
    ("Preview what each rule would do now (no writes)", act_preview),
    ("Account history", act_history),
    ("Run the daily job now", act_daily),
    ("Deposit paper capital", act_deposit),
    ("Pause / resume", act_pause),
    ("Show the log", act_logs),
    ("Watch the single-coin paper loop", act_paper),
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
    actions: Dict[str, Callable] = {label: fn for label, fn in MENU}
    while True:
        console.clear()
        console.print(header(state))
        console.print(accounts_table(state))
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
