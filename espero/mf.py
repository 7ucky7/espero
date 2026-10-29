"""Hypothesis #8 as a weekly paper account: the six-month forward test.

The rule is frozen in research/PREREGISTRATION_MF.md and the forward test in
research/FORWARD_MF.md. This module is `research/multifactor.py`'s simulator
run one day at a time on live data, and a test holds it to that, day by day:

    decide at Sunday's close  ->  fill at Monday's open  ->  mark at every close

    espero mf                  # daily: mark, and fill a pending Sunday decision
    espero mf --cash 100       # the first run sets the starting cash

What the live account adds, all fixed in FORWARD_MF.md before it ran:

* nothing trades before FORWARD_START; the account holds cash until then
* a Monday the job missed is filled at the next run's latest price and noted
  `late` -- never at a historical open the account could not have traded at
* fewer than MIN_UNIVERSE coins loaded: mark only, the decision waits
* a held coin that stops reporting is marked at its last known price
"""
from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

import pandas as pd

from . import factors, panel
from . import portfolio as pf
from .xs import UNIVERSE

log = logging.getLogger(__name__)

# PREREGISTRATION_MF.md -- frozen; tests/test_mf.py checks them against research/multifactor.py
FACTORS = ["mom_30", "rev_3", "lowvol_30"]
TOP = 10
BUFFER = 2.0
TARGET_VOL = 0.20
MAX_SCALE = 2.0
COST = 0.0010
MIN_HISTORY = 365
MIN_DOLLAR_VOLUME = 1e6
VOL_WINDOW = 30

# FORWARD_MF.md
FORWARD_START = pd.Timestamp("2026-11-02")       # first Monday fill
FORWARD_END = pd.Timestamp("2027-05-03")
MIN_UNIVERSE = 30
SPAN = "2y"                                      # > MIN_HISTORY + VOL_WINDOW closes

SCHEMA = """
CREATE TABLE IF NOT EXISTS mf_account (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL, cash REAL, units TEXT, equity REAL, weights TEXT,
    decision TEXT, positions TEXT, deposit REAL, note TEXT, last_px TEXT, traded REAL,
    UNIQUE(ts, note)
);
"""


def decide(p: panel.MarketPanel, sunday: pd.Timestamp, held: List[str]) -> pd.Series:
    """Target weights from the closes up to and including `sunday`, nothing later."""
    q = p.slice(None, sunday)
    mask = panel.eligible(q, min_history=MIN_HISTORY, min_dollar_volume=MIN_DOLLAR_VOLUME)
    score = factors.composite(q, FACTORS, mask)
    s = score.loc[sunday].where(mask.loc[sunday])
    picks = pf.turnover_buffer(s, held, TOP, BUFFER)
    w = pf.equal_weight(picks, q.coins)
    vol = pf.realized_vol(q.close, VOL_WINDOW)
    return pf.vol_scaled(w, vol.loc[sunday], TARGET_VOL, 1.0, MAX_SCALE)


def last_sunday(index: pd.DatetimeIndex, today: pd.Timestamp) -> Optional[pd.Timestamp]:
    """The latest Sunday whose daily bar is complete, i.e. strictly before today's bar."""
    sundays = [d for d in index if d.weekday() == 6 and d < today]
    return sundays[-1] if sundays else None


@dataclass
class MFAccount:
    path: Path
    cash: float = 0.0
    units: Dict[str, float] = field(default_factory=dict)
    last_px: Dict[str, float] = field(default_factory=dict)
    decision: Optional[str] = None          # the last Sunday whose decision was filled

    def __post_init__(self):
        self.db = sqlite3.connect(self.path, timeout=5.0)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        row = self.db.execute("SELECT * FROM mf_account ORDER BY ts DESC, id DESC LIMIT 1").fetchone()
        if row:
            self.cash = row["cash"]
            self.units = json.loads(row["units"])
            self.last_px = json.loads(row["last_px"] or "{}")
            self.decision = row["decision"]

    @property
    def started(self) -> bool:
        return self.db.execute("SELECT 1 FROM mf_account LIMIT 1").fetchone() is not None

    def held(self) -> List[str]:
        return [c for c, u in self.units.items() if u > 0]

    def prices(self, px: pd.Series) -> pd.Series:
        """`px` where it has a price, the last known price for anything held that has none."""
        merged = {c: float(v) for c, v in px.items() if pd.notna(v)}
        for c in self.units:
            if c not in merged:
                if c not in self.last_px:
                    raise ValueError(f"held {c} has no price today and no last known price")
                merged[c] = self.last_px[c]
        return pd.Series(merged, dtype=float)

    def equity(self, px: pd.Series) -> float:
        px = self.prices(px)
        return self.cash + sum(u * float(px[c]) for c, u in self.units.items())

    def fill(self, px: pd.Series, weights: pd.Series) -> float:
        """The simulator's fill, unchanged: targets on the pre-fee value, the fee
        taken from cash. Gross is at most 100%, and in practice far less at a 20%
        vol target, so cash cannot go negative by the fee."""
        px = self.prices(px)
        value = self.equity(px)
        traded = 0.0
        for c, w in weights.items():
            if c not in px.index:
                continue                         # untradable today: keep what is held
            target = float(w) * value
            traded += abs(target - self.units.get(c, 0.0) * float(px[c]))
            self.units[c] = target / float(px[c])
        self.units = {c: u for c, u in self.units.items() if u > 0}
        self.cash = value - sum(u * float(px[c]) for c, u in self.units.items()) - traded * COST
        return traded

    def save(self, ts: int, equity: float, weights: Dict[str, float], positions: Dict[str, float],
             deposit: float, note: str, last_px: Dict[str, float], traded: float) -> None:
        self.last_px = {c: float(v) for c, v in last_px.items()}
        self.db.execute(
            "INSERT OR REPLACE INTO mf_account(ts, cash, units, equity, weights, decision,"
            " positions, deposit, note, last_px, traded) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (ts, self.cash, json.dumps(self.units), equity, json.dumps(weights), self.decision,
             json.dumps(positions), deposit, note, json.dumps(self.last_px), traded))
        self.db.commit()

    def close(self) -> None:
        self.db.close()


def step(acc: MFAccount, p: panel.MarketPanel, start: pd.Timestamp = FORWARD_START,
         min_universe: int = MIN_UNIVERSE) -> dict:
    """One run on a panel whose last row is today (possibly a partial bar).

    Fills the latest complete Sunday's decision if it has not been filled and
    its Monday is on or after `start`; then marks at today's close.
    """
    today = p.index[-1]
    sunday = last_sunday(p.index, today)
    weights: Dict[str, float] = {}
    traded, note = 0.0, "mark"
    due = (sunday is not None and sunday + pd.Timedelta(days=1) >= start
           and acc.decision != str(sunday.date()))
    loaded = int(p.close.loc[:sunday].iloc[-1].notna().sum()) if sunday is not None else 0
    if due and loaded < min_universe:
        log.error("mf: only %d/%d coins have a close on %s; not trading", loaded, len(p.coins),
                  sunday.date())
        note = f"mark (degraded {loaded}/{len(p.coins)})"
        due = False
    if due:
        w = decide(p, sunday, acc.held())
        monday = sunday + pd.Timedelta(days=1)
        if today == monday:
            px = p.open.loc[today].where(p.open.loc[today].notna(), p.close.loc[today])
            note = "rebalance"
        else:
            px = p.close.loc[today]
            note = f"rebalance (late, decision {sunday.date()})"
        traded = acc.fill(px.dropna(), w)
        acc.decision = str(sunday.date())
        weights = {c: float(v) for c, v in w.items() if v > 0}
    elif acc.started:
        prev = acc.db.execute("SELECT weights FROM mf_account ORDER BY ts DESC, id DESC LIMIT 1").fetchone()
        weights = json.loads(prev["weights"]) if prev else {}

    close = p.close.loc[today].dropna()
    mark_px = acc.prices(close)
    equity = acc.equity(close)
    positions = {c: u * float(mark_px[c]) for c, u in acc.units.items()}
    return {"ts": int(today.timestamp()), "equity": equity, "traded": traded, "note": note,
            "weights": weights, "positions": positions, "decision": acc.decision,
            "last_px": mark_px.to_dict()}


def run(state: str, cash: float = 100.0, now: Optional[pd.Timestamp] = None,
        fetch: Callable[[str, str], pd.DataFrame] = None) -> dict:
    p = panel.build(UNIVERSE, span=SPAN, fetch=fetch)
    for c, why in p.errors.items():
        log.warning("mf: %s not loaded: %s", c, why)
    if now is not None:
        p = p.slice(None, pd.Timestamp(now).normalize())
    acc = MFAccount(Path(state))
    deposit = 0.0
    if not acc.started:
        acc.cash, deposit = cash, cash
    res = step(acc, p)
    note = "init" if deposit and res["note"] == "mark" else res["note"]
    acc.save(res["ts"], res["equity"], res["weights"], res["positions"], deposit, note,
             res["last_px"], res["traded"])
    acc.close()
    return {**res, "note": note, "errors": p.errors}


def format_report(res: dict) -> str:
    lines = [f"equity ${res['equity']:,.2f}  ({res['note']})"]
    if res["decision"] is None:
        lines.append(f"holding cash until the first fill on {FORWARD_START.date()}")
    else:
        lines.append(f"last decision: Sunday {res['decision']}")
    lines.append("")
    if res["positions"]:
        lines.append(f"{'coin':6s} {'weight':>7s} {'value':>9s}")
        for c, v in sorted(res["positions"].items(), key=lambda x: -x[1]):
            lines.append(f"{c:6s} {100 * res['weights'].get(c, 0):6.1f}% {v:9.2f}")
    cash = res["equity"] - sum(res["positions"].values())
    lines.append(f"{'cash':6s} {100 * cash / max(res['equity'], 1e-9):6.1f}% {cash:9.2f}")
    if res["traded"]:
        lines.append(f"\ntraded ${res['traded']:,.2f} at {COST * 1e4:.0f} bps a side")
    if res.get("errors"):
        lines.append(f"\ndata: {len(res['errors'])} coins failed to load: {', '.join(sorted(res['errors']))}")
    lines.append(f"\nforward test {FORWARD_START.date()} -> {FORWARD_END.date()} (research/FORWARD_MF.md)")
    return "\n".join(lines)
