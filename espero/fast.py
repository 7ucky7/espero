"""The fast screen: one product, the live book, and proposals a human confirms.

Semi-automatic on purpose. The machine reads the book every second, keeps the
signal current, and when the signal says act it *proposes* a post-only order
with the evidence beside it: the signal's inputs, the measured edge against
the venue's cost, the regime, and whether the signal has been working lately.
Nothing is placed until Enter. The worst a bug can do is show a bad proposal.

    espero fast --product ETH-USD                  # paper, live book
    espero fast --product ETH-USD --record         # also record the book to data/book/
    espero fast --replay data/book/ETH-USD_....jsonl --speed 10

Keys while running:  Enter place · n decline · r reprice to the touch
                     c cancel resting · j journal note · k kill (cancel all, halt) · q quit
"""
from __future__ import annotations

import json
import math
import os
import select
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from . import data
from .book import BookSnapshot, CoinbaseBook, Recorder, replay
from .execution import Fill, PaperExchange
from .venues import VENUES

# Measured, not assumed: RESULTS_LEADLAG2.md, Q5-Q1 spread of the reversal/lead-lag
# family at a 3h horizon on Coinbase hourly data. Update when a new result lands.
MEASURED_EDGE_BPS = 3.7
MEASURED_EDGE_SOURCE = "research/RESULTS_LEADLAG2.md (rev_1 family, 3h, OOS)"
HORIZON_H = 3
MIN_EDGE_RATIO = 2.0          # below this the proposal defaults to "no"


@dataclass
class SignalState:
    value: Optional[float] = None       # beta * r_leader - r_coin over the last bar
    beta: Optional[float] = None
    r_leader: Optional[float] = None
    r_coin: Optional[float] = None
    rank_note: str = ""
    rolling_ic: Optional[float] = None  # time-series corr of signal vs 3h fwd, last 2 weeks
    vol_ratio: Optional[float] = None   # last-24h hourly vol / median hourly vol in window
    bars: int = 0
    updated: float = 0.0
    error: str = ""

    @property
    def cold(self) -> bool:
        return self.rolling_ic is not None and self.rolling_ic < 0


class CandleSignal:
    """beta-scaled lead-lag from closed hourly candles, refreshed each minute."""

    def __init__(self, product: str, leader: str = "BTC-USD", window: int = 168,
                 fetch=None):
        self.product, self.leader, self.window = product, leader, window
        self.fetch = fetch or data.recent_closed_bars
        self.state = SignalState()
        self._last = 0.0

    def update(self, now: Optional[float] = None) -> SignalState:
        now = now or time.time()
        if now - self._last < 60 and self.state.updated:
            return self.state
        self._last = now
        try:
            a = self.fetch(self.product, 3600, 300).set_index("ts")["close"]
            b = self.fetch(self.leader, 3600, 300).set_index("ts")["close"]
        except Exception as exc:  # noqa: BLE001 - the screen shows the error, keeps running
            self.state.error = f"{type(exc).__name__}: {exc}"
            return self.state
        self.state = compute_signal(a, b, self.window)
        self.state.updated = now
        return self.state


def compute_signal(coin: pd.Series, leader: pd.Series, window: int = 168,
                   horizon: int = HORIZON_H) -> SignalState:
    df = pd.concat({"c": coin, "l": leader}, axis=1).dropna()
    st = SignalState(bars=len(df))
    if len(df) < max(window, 30) + horizon + 5:
        st.error = f"only {len(df)} shared hourly bars; need {window + horizon + 5}"
        return st
    rc, rl = df["c"].pct_change(), df["l"].pct_change()
    cov = rc.rolling(window).cov(rl)
    var = rl.rolling(window).var()
    beta = cov / var.replace(0, np.nan)
    sig = beta * rl - rc
    st.value = float(sig.iloc[-1])
    st.beta = float(beta.iloc[-1])
    st.r_leader = float(rl.iloc[-1])
    st.r_coin = float(rc.iloc[-1])
    fwd = df["c"].shift(-horizon) / df["c"] - 1
    pair = pd.concat([sig, fwd], axis=1).dropna().iloc[-336:]       # two weeks
    if len(pair) >= 48:
        st.rolling_ic = float(np.corrcoef(pair.iloc[:, 0].rank(), pair.iloc[:, 1].rank())[0, 1])
    hourly_vol = rc.rolling(24).std()
    med = float(hourly_vol.median()) if hourly_vol.notna().any() else 0.0
    st.vol_ratio = float(hourly_vol.iloc[-1] / med) if med > 0 else None
    return st


# ------------------------------------------------------------------ the book
@dataclass
class Proposal:
    side: str
    price: float
    size: float
    reason: str
    edge_bps: float
    cost_bps: float
    created: float

    @property
    def ratio(self) -> float:
        return self.edge_bps / self.cost_bps if self.cost_bps > 0 else math.inf

    @property
    def advised(self) -> bool:
        return self.ratio >= MIN_EDGE_RATIO


@dataclass
class RiskLimits:
    max_notional: float = 100.0        # per order, quote currency
    max_inventory_notional: float = 200.0
    max_daily_loss: float = 10.0
    max_orders_per_hour: int = 20
    stale_feed_s: float = 15.0


@dataclass
class FastBook:
    """Everything except the terminal: state, proposals, risk, journal."""
    product: str
    exchange: PaperExchange
    venue: str = "coinbase"
    limits: RiskLimits = field(default_factory=RiskLimits)
    threshold: float = 0.003            # signal gap that triggers a proposal (not pre-registered)
    order_notional: float = 50.0
    journal_path: Optional[Path] = None
    snap: Optional[BookSnapshot] = None
    signal: SignalState = field(default_factory=SignalState)
    proposal: Optional[Proposal] = None
    halted: str = ""
    day_start_equity: Optional[float] = None
    day: Optional[str] = None
    placed_times: List[float] = field(default_factory=list)
    log: List[str] = field(default_factory=list)
    entry_ts: Optional[float] = None
    why_by_order: Dict[str, dict] = field(default_factory=dict)   # evidence as it stood at Enter

    def __post_init__(self):
        v = VENUES[self.venue]
        self.maker_bps, self.taker_bps = v.maker_bps, v.taker_bps
        self.exchange.maker_fee = v.maker_bps / 1e4
        self._db = None
        if self.journal_path:
            self._db = sqlite3.connect(self.journal_path)
            self._db.execute("""CREATE TABLE IF NOT EXISTS fast_fills (
                ts REAL, product TEXT, side TEXT, price REAL, size REAL, fee REAL,
                decision_mid REAL, delay_s REAL, slippage_bps REAL, why TEXT, note TEXT)""")
            self._db.execute("""CREATE TABLE IF NOT EXISTS fast_notes (ts REAL, product TEXT, note TEXT)""")
            self._db.commit()

    # ------------------------------------------------------------- a tick
    def on_snapshot(self, snap: BookSnapshot, signal: Optional[SignalState] = None) -> List[Fill]:
        self.snap = snap
        if signal is not None:
            self.signal = signal
        self._roll_day(snap)
        fills = self.exchange.on_snapshot(snap)
        for f in fills:
            self._record_fill(f)
            self.say(f"filled {f.side} {f.size:.6f} @ {f.price:.2f}  {f.slippage_bps:+.1f} bps vs mid, "
                     f"{f.delay_s:.0f}s")
            if self.exchange.inventory > 1e-12 and self.entry_ts is None:
                self.entry_ts = f.ts
            if self.exchange.inventory <= 1e-12:
                self.entry_ts = None
        self._check_risk(snap)
        if not self.halted and self.proposal is None and not self.exchange.resting():
            self.proposal = self._propose(snap)
        return fills

    def _roll_day(self, snap: BookSnapshot) -> None:
        day = datetime.fromtimestamp(snap.ts, timezone.utc).date().isoformat()
        if day != self.day:
            self.day = day
            self.day_start_equity = self.exchange.equity(snap)

    # ---------------------------------------------------------- proposals
    def cost_bps(self) -> float:
        return 2 * self.maker_bps + (self.snap.spread_bps or 0.0) / 2 if self.snap else 2 * self.maker_bps

    def _propose(self, snap: BookSnapshot) -> Optional[Proposal]:
        s = self.signal
        if s.value is None or snap.best_bid is None or snap.best_ask is None:
            return None
        inv = self.exchange.inventory
        mid = snap.mid
        # exit at the horizon regardless of signal
        if inv > 1e-12 and self.entry_ts and snap.ts - self.entry_ts >= HORIZON_H * 3600:
            return Proposal("sell", snap.best_ask, inv, f"held {HORIZON_H}h: exit at the touch",
                            MEASURED_EDGE_BPS, self.cost_bps(), snap.ts)
        if s.value >= self.threshold and inv <= 1e-12:
            size = min(self.order_notional, self.limits.max_notional) / mid
            return Proposal("buy", snap.best_bid, size,
                            f"lagged {self.leader_name()} by {1e4 * s.value:+.0f} bps (beta {s.beta:.2f})",
                            MEASURED_EDGE_BPS, self.cost_bps(), snap.ts)
        if s.value <= -self.threshold and inv > 1e-12:
            return Proposal("sell", snap.best_ask, inv,
                            f"overshot {self.leader_name()} by {-1e4 * s.value:+.0f} bps",
                            MEASURED_EDGE_BPS, self.cost_bps(), snap.ts)
        return None

    def leader_name(self) -> str:
        return "BTC"

    def accept(self) -> Optional[str]:
        """Enter: place the proposal post-only at its price."""
        p, snap = self.proposal, self.snap
        if p is None or snap is None or self.halted:
            return None
        if len([t for t in self.placed_times if snap.ts - t < 3600]) >= self.limits.max_orders_per_hour:
            self.halted = "max orders per hour"
            return self.halted
        order = self.exchange.place_post_only(snap, p.side, p.price, p.size, decision_mid=snap.mid)
        self.proposal = None
        if order.status == "rejected":
            self.say(f"rejected {p.side} {p.size:.6f} @ {p.price:.2f} (would cross or no funds)")
            return "rejected"
        self.placed_times.append(snap.ts)
        self.why_by_order[order.id] = self.why()
        self.say(f"resting {p.side} {p.size:.6f} @ {p.price:.2f}  queue ahead {order.queue_ahead:.4f}")
        return order.id

    def decline(self) -> None:
        if self.proposal:
            self.say(f"declined {self.proposal.side} ({self.proposal.reason})")
        self.proposal = None

    def reprice(self) -> None:
        """r: move every resting order to the current touch, keeping its side and remaining size."""
        snap = self.snap
        if snap is None:
            return
        for o in self.exchange.cancel_all():
            px = snap.best_bid if o.side == "buy" else snap.best_ask
            new = self.exchange.place_post_only(snap, o.side, px, o.remaining, decision_mid=o.decision_mid)
            if new.status == "resting":
                self.why_by_order[new.id] = self.why_by_order.get(o.id, self.why())
            self.say(f"repriced {o.side} {o.price:.2f} -> {px:.2f} [{new.status}]")

    def cancel(self) -> None:
        n = len(self.exchange.cancel_all())
        if n:
            self.say(f"cancelled {n} resting order(s)")

    def kill(self) -> None:
        self.cancel()
        self.proposal = None
        self.halted = "killed by operator"
        self.say("KILL: halted, nothing more will be proposed")

    # --------------------------------------------------------------- risk
    def day_pnl(self) -> float:
        if self.day_start_equity is None or self.snap is None:
            return 0.0
        return self.exchange.equity(self.snap) - self.day_start_equity

    def risk(self) -> Dict[str, tuple]:
        """name -> (value, limit, fraction used). The strip turns red above 0.8."""
        snap = self.snap
        mid = (snap.mid or 0.0) if snap else 0.0
        inv_notional = abs(self.exchange.inventory * mid)
        orders_hr = len([t for t in self.placed_times if snap and snap.ts - t < 3600])
        feed_age = (time.time() - snap.ts) if snap else math.inf
        loss = -min(0.0, self.day_pnl())
        return {
            "inventory $": (inv_notional, self.limits.max_inventory_notional,
                            inv_notional / self.limits.max_inventory_notional),
            "day loss $": (loss, self.limits.max_daily_loss, loss / self.limits.max_daily_loss),
            "orders/hr": (orders_hr, self.limits.max_orders_per_hour,
                          orders_hr / self.limits.max_orders_per_hour),
            "feed age s": (feed_age, self.limits.stale_feed_s, min(1.0, feed_age / self.limits.stale_feed_s)),
        }

    def _check_risk(self, snap: BookSnapshot) -> None:
        if self.halted:
            return
        if -self.day_pnl() >= self.limits.max_daily_loss:
            self.cancel()
            self.halted = f"daily loss limit ({self.day_pnl():+.2f})"
            self.say(f"HALT: {self.halted}")

    # ------------------------------------------------------------ journal
    def why(self) -> dict:
        s = self.signal
        return {"signal": s.value, "beta": s.beta, "r_leader": s.r_leader, "r_coin": s.r_coin,
                "rolling_ic": s.rolling_ic, "vol_ratio": s.vol_ratio,
                "edge_bps": MEASURED_EDGE_BPS, "cost_bps": self.cost_bps(),
                "mid": self.snap.mid if self.snap else None,
                "spread_bps": self.snap.spread_bps if self.snap else None,
                "imbalance": self.snap.imbalance() if self.snap else None}

    def _record_fill(self, f: Fill) -> None:
        if not self._db:
            return
        self._db.execute("INSERT INTO fast_fills VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                         (f.ts, self.product, f.side, f.price, f.size, f.fee, f.decision_mid, f.delay_s,
                          f.slippage_bps, json.dumps(self.why_by_order.get(f.order_id, self.why())), ""))
        self._db.commit()

    def note(self, text: str) -> None:
        if not text:
            return
        self.say(f"note: {text}")
        if self._db:
            self._db.execute("INSERT INTO fast_notes VALUES (?,?,?)",
                             (self.snap.ts if self.snap else time.time(), self.product, text))
            self._db.commit()

    def say(self, line: str) -> None:
        stamp = datetime.fromtimestamp(self.snap.ts if self.snap else time.time(), timezone.utc)
        self.log.append(f"{stamp:%H:%M:%S}  {line}")
        self.log = self.log[-12:]


# ------------------------------------------------------------------ screen
class Keys:
    """Non-blocking single keypresses from a POSIX terminal."""

    def __enter__(self):
        import termios
        import tty
        self.fd = sys.stdin.fileno()
        self.saved = termios.tcgetattr(self.fd)
        tty.setcbreak(self.fd)
        return self

    def __exit__(self, *exc):
        import termios
        termios.tcsetattr(self.fd, termios.TCSADRAIN, self.saved)
        return False

    def read(self) -> List[str]:
        out = []
        while select.select([sys.stdin], [], [], 0)[0]:
            out.append(os.read(self.fd, 1).decode(errors="ignore"))
        return out

    def line(self, prompt: str) -> str:
        import termios
        termios.tcsetattr(self.fd, termios.TCSADRAIN, self.saved)
        try:
            return input(prompt)
        finally:
            import tty
            tty.setcbreak(self.fd)


def _kv(pairs, muted="grey58"):
    """A two-column key/value grid, keys muted, values aligned."""
    from rich.table import Table
    g = Table.grid(padding=(0, 1))
    g.add_column(style=muted, justify="right")
    g.add_column()
    for k, v in pairs:
        g.add_row(k, v)
    return g


def render(fb: FastBook, mode: str):
    from rich.layout import Layout
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    from .ui import MASCOT

    ACCENT, MUTED = "#d97757", "grey58"
    s, snap = fb.signal, fb.snap
    mid = snap.mid if snap and snap.mid else None

    # ------------------------------------------------------------- header
    title = Text()
    title.append(f"{fb.product}", style="bold")
    title.append(f"   {mode}", style=MUTED)
    if fb.halted:
        title.append(f"   HALTED: {fb.halted}", style="bold red")
    market = Text()
    if mid:
        market.append("mid ", style=MUTED)
        market.append(f"{mid:,.2f}", style="bold")
        market.append("   spread ", style=MUTED)
        market.append(f"{snap.spread_bps:.2f} bps")
        imb = snap.imbalance() or 0.0
        market.append("   book ", style=MUTED)
        market.append(f"{imb:+.2f}", style="green" if imb > 0.1 else ("red" if imb < -0.1 else None))
        market.append(f"   {len(snap.trades)} prints", style=MUTED)
        age = time.time() - snap.ts
        market.append(f"   feed {age:.0f}s", style="red" if age > fb.limits.stale_feed_s else MUTED)
    else:
        market.append("waiting for the book ...", style=MUTED)
    account = Text()
    account.append("equity ", style=MUTED)
    account.append(f"${fb.exchange.equity(snap):,.2f}", style=f"bold {ACCENT}")
    pnl = fb.day_pnl()
    account.append(f"  {pnl:+,.2f} today", style="green" if pnl > 0 else ("red" if pnl < 0 else MUTED))
    account.append("   inventory ", style=MUTED)
    account.append(f"{fb.exchange.inventory:.6f}")
    if mid and fb.exchange.inventory:
        account.append(f" (${fb.exchange.inventory * mid:,.2f})", style=MUTED)
    art = Text("\n".join(MASCOT), style=ACCENT)
    head = Table.grid(padding=(0, 2))
    head.add_column(no_wrap=True)
    head.add_column()
    head.add_row(art, Text.assemble(title, "\n", market, "\n", account))

    # ---------------------------------------------------------------- why
    if s.error:
        why_rows = [("signal", Text(s.error, style="yellow"))]
    elif s.value is None:
        why_rows = [("signal", Text("warming up (needs 168 shared hourly bars)", style=MUTED))]
    else:
        gap = Text(f"{1e4 * s.value:+.0f} bps", style="bold green" if s.value >= fb.threshold
                   else ("bold red" if s.value <= -fb.threshold else "bold"))
        gap.append(f"  = beta {s.beta:.2f} × BTC {1e4 * s.r_leader:+.0f} − own {1e4 * s.r_coin:+.0f}"
                   f"   (acts at ±{1e4 * fb.threshold:.0f})", style=MUTED)
        ic = "n/a" if s.rolling_ic is None else f"{s.rolling_ic:+.3f}"
        working = Text(f"2-week IC {ic}", style="red" if s.cold else "green")
        if s.cold:
            working.append("   SIGNAL COLD", style="bold red")
        vr = "n/a" if s.vol_ratio is None else f"{s.vol_ratio:.2f}× median"
        hour = datetime.now(timezone.utc).hour
        nxt = (8 - hour % 8) % 8 or 8
        settle = ((hour // 8 + 1) * 8) % 24
        why_rows = [("signal", gap), ("working", working),
                    ("regime", Text(f"hourly vol {vr}   ·   funding settles in {nxt}h (UTC {settle:02d}:00)"))]
    cost = fb.cost_bps()
    ratio = MEASURED_EDGE_BPS / cost if cost > 0 else math.inf
    edge = Text(f"{MEASURED_EDGE_BPS:.1f} bps edge vs {cost:.1f} bps cost  →  ratio {ratio:.1f}",
                style="green" if ratio >= MIN_EDGE_RATIO else "red")
    if ratio < MIN_EDGE_RATIO:
        edge.append("   below 2: default no", style="bold red")
    why_rows.append(("budget", edge))
    why_rows.append(("source", Text(MEASURED_EDGE_SOURCE, style=MUTED)))
    why = Panel(_kv(why_rows), title="why", title_align="left", border_style=MUTED)

    # --------------------------------------------------------------- risk
    risk_rows = []
    for name, (val, lim, frac) in fb.risk().items():
        bar_n = int(min(1.0, max(0.0, frac)) * 12)
        style = "bold red" if frac >= 0.8 else ("yellow" if frac >= 0.5 else "green")
        cell = Text("█" * bar_n + "░" * (12 - bar_n) + f"  {val:,.1f} / {lim:,.0f}", style=style)
        risk_rows.append((name, cell))
    risk = Panel(_kv(risk_rows), title="risk", title_align="left", border_style=MUTED)

    # ------------------------------------------------------- orders, fills
    resting = Table(box=None, header_style=MUTED, padding=(0, 1), expand=True)
    for c, j in (("side", "left"), ("price", "right"), ("size", "right"), ("filled", "right"),
                 ("queue", "right"), ("age", "right")):
        resting.add_column(c, justify=j)
    for o in fb.exchange.resting():
        age = (snap.ts - o.placed_ts) if snap else 0
        resting.add_row(Text(o.side, style="green" if o.side == "buy" else "red"), f"{o.price:,.2f}",
                        f"{o.size:.5f}", f"{o.filled:.5f}", f"{o.queue_ahead:.3f}", f"{age:.0f}s")
    if not fb.exchange.resting():
        resting.add_row(Text("none", style=MUTED), "", "", "", "", "")
    resting_p = Panel(resting, title="resting", title_align="left", border_style=MUTED)

    fills = Table(box=None, header_style=MUTED, padding=(0, 1), expand=True)
    for c, j in (("time", "left"), ("side", "left"), ("price", "right"), ("size", "right"),
                 ("vs mid", "right"), ("delay", "right"), ("fee", "right")):
        fills.add_column(c, justify=j)
    for f in fb.exchange.fills[-6:]:
        slip = Text(f"{f.slippage_bps:+.1f} bps", style="green" if f.slippage_bps <= 0 else "red")
        fills.add_row(datetime.fromtimestamp(f.ts, timezone.utc).strftime("%H:%M:%S"),
                      Text(f.side, style="green" if f.side == "buy" else "red"), f"{f.price:,.2f}",
                      f"{f.size:.5f}", slip, f"{f.delay_s:.0f}s", f"{f.fee:.4f}")
    if not fb.exchange.fills:
        fills.add_row(Text("none yet", style=MUTED), "", "", "", "", "", "")
    fills_p = Panel(fills, title="fills · TCA vs mid at decision", title_align="left", border_style=MUTED)

    # ----------------------------------------------------------- proposal
    keys = Text("Enter place · n decline · r reprice · c cancel · j note · k kill · q quit", style=MUTED)
    if fb.proposal:
        p = fb.proposal
        body = Text()
        body.append(f"{p.side.upper()} {p.size:.5f} @ {p.price:,.2f}", style="bold")
        body.append("  post-only", style=MUTED)
        body.append(f"   {p.reason}\n")
        body.append(f"edge {p.edge_bps:.1f} vs cost {p.cost_bps:.1f} bps, ratio {p.ratio:.1f}  ",
                    style="green" if p.advised else "red")
        body.append("ADVISED" if p.advised else "NOT ADVISED", style="bold green" if p.advised else "bold red")
        body.append("\n")
        body.append(keys)
        prop = Panel(body, title="proposal", title_align="left", border_style=ACCENT)
    else:
        prop = Panel(Text.assemble(Text("no proposal   ", style=MUTED), keys), border_style=MUTED)

    log = Panel(Text("\n".join(fb.log[-4:]) or " ", style=MUTED), border_style=MUTED)

    layout = Layout()
    layout.split_column(
        Layout(Panel(head, border_style=MUTED), name="head", size=5),
        Layout(name="body"),
        Layout(prop, name="prop", size=5),
        Layout(log, name="log", size=6),
    )
    layout["body"].split_row(Layout(name="left"), Layout(name="right"))
    layout["left"].split_column(Layout(why, name="why", size=9), Layout(risk, name="risk"))
    layout["right"].split_column(Layout(resting_p, name="resting", size=9), Layout(fills_p, name="fills"))
    return layout


def run(product: str, cash: float = 500.0, venue: str = "coinbase", record: bool = False,
        replay_path: Optional[Path] = None, speed: float = 10.0, interval: float = 1.0,
        state_dir: Path = Path("."), threshold: float = 0.003, order_notional: float = 50.0) -> int:
    from rich.console import Console
    from rich.live import Live

    console = Console()
    ex = PaperExchange(cash=cash)
    fb = FastBook(product, ex, venue=venue, threshold=threshold, order_notional=order_notional,
                  journal_path=Path(state_dir) / "fast.db")
    mode = f"PAPER · {VENUES[venue].name} maker {VENUES[venue].maker_bps:.0f} bps"
    rec = None
    if replay_path:
        feed = replay(Path(replay_path))
        mode = f"REPLAY {speed:.0f}× · {Path(replay_path).name}"
        signal = CandleSignal(product)          # live candles still drive the signal in replay
    else:
        live_book = CoinbaseBook(product)
        feed = None
        signal = CandleSignal(product)
        if record:
            stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M")
            rec = Recorder(Path(state_dir) / "data" / "book" / f"{product}_{stamp}.jsonl")
            mode += f" · recording {rec.path.name}"

    fb.say("started; nothing is placed without Enter")
    try:
        with Keys() as keys, Live(render(fb, mode), console=console, refresh_per_second=4, screen=True,
                                  vertical_overflow="crop") as live:
            while True:
                try:
                    snap = next(feed) if feed is not None else live_book.read()
                except StopIteration:
                    fb.say("replay finished")
                    live.update(render(fb, mode))
                    time.sleep(2)
                    break
                except Exception as exc:  # noqa: BLE001
                    fb.say(f"feed error: {type(exc).__name__}: {exc}")
                    snap = fb.snap
                if snap is not None:
                    if rec:
                        rec.write(snap)
                    fb.on_snapshot(snap, signal.update())
                for k in keys.read():
                    if k in ("\r", "\n"):
                        fb.accept()
                    elif k == "n":
                        fb.decline()
                    elif k == "r":
                        fb.reprice()
                    elif k == "c":
                        fb.cancel()
                    elif k == "k":
                        fb.kill()
                    elif k == "j":
                        live.stop()
                        fb.note(keys.line("note> "))
                        live.start()
                    elif k == "q":
                        fb.cancel()
                        raise KeyboardInterrupt
                live.update(render(fb, mode))
                time.sleep(interval / speed if feed is not None else interval)
    except KeyboardInterrupt:
        pass
    finally:
        if rec:
            rec.close()
    console.print(f"stopped · equity ${ex.equity():,.2f} · {len(ex.fills)} fills · journal {fb.journal_path}")
    return 0
