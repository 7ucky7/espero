"""Cross-asset TSMOM, run as a paper account.

The pre-registered rule, applied to a real $100 balance and written to SQLite so
the track record exists independently of anyone's memory:

    at the first trading day of each month, hold equal weight in every asset
    whose 252-day return is positive (max 1/6 each); the rest stays in cash.

    espero tsmom --state tsmom.db --cash 100        # daily mark, rebalance when due
    espero tsmom --force                            # rebalance now regardless
    espero tsmom --report                           # history

Fills are simulated at the latest close with 10 bps per side. No keys, no orders.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

import pandas as pd

from . import cash as treasury
from . import data

UNIVERSE = {
    "SPY": "SPY", "TLT": "TLT", "GLD": "GLD",
    "USO": "USO", "BTC-USD": "BTC", "ETH-USD": "ETH",
}
LOOKBACK = 252
MAX_WEIGHT = 1 / 6
COST = 0.001

SCHEMA = """
CREATE TABLE IF NOT EXISTS account (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL, cash REAL, units TEXT, equity REAL, weights TEXT, note TEXT,
    positions TEXT, signals TEXT, deposit REAL, vehicle TEXT, carry REAL, traded REAL,
    UNIQUE(ts, note)   -- one mark per day, but a deposit and a mark can share a day
);
"""


def load_series(span: str = "2y") -> Dict[str, pd.Series]:
    """Each asset on its own calendar. Crypto trades weekends, ETFs do not, so a
    lookback must be counted in the asset's own rows or 252 rows silently becomes
    seven months."""
    out = {}
    for symbol, name in UNIVERSE.items():
        df = data.yahoo_daily(symbol, span)
        out[name] = df.set_index("dt")["close"].sort_index()
    return out


def closes(series: Dict[str, pd.Series]) -> pd.DataFrame:
    return pd.DataFrame(series).sort_index().ffill()


LOOKBACK_DAYS = 364   # 52 weeks: uniform across assets that trade 5 days and 7


def signals(series: Dict[str, pd.Series]) -> Dict[str, float]:
    """Look back 52 weeks on the calendar, not 252 rows.

    252 rows is a year for an ETF (5 sessions/week) and eight months for crypto
    (7 sessions/week). The backtest reindexed every asset to the SPY calendar,
    so it meant ~12 months; the live account must mean the same thing.
    """
    out = {}
    for name, s in series.items():
        s = s.dropna()
        if len(s) < 2:
            continue
        cutoff = s.index[-1] - pd.Timedelta(days=LOOKBACK_DAYS)
        past = s[s.index <= cutoff]
        if past.empty:
            continue
        out[name] = float(s.iloc[-1] / past.iloc[-1] - 1)
    return out


def target_weights(sig: Dict[str, float]) -> tuple[Dict[str, float], float]:
    picks = [a for a, v in sig.items() if v > 0]
    w = min(1.0 / len(picks), MAX_WEIGHT) if picks else 0.0
    weights = {a: (w if a in picks else 0.0) for a in sig}
    return weights, 1.0 - w * len(picks)


@dataclass
class Account:
    path: Path
    cash: float = 0.0
    units: Dict[str, float] = field(default_factory=dict)
    vehicle: str = "USD"
    carry_total: float = 0.0

    def __post_init__(self):
        self.db = sqlite3.connect(self.path, timeout=5.0)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        cols = {r["name"] for r in self.db.execute("PRAGMA table_info(account)")}
        for col in ("positions", "signals", "deposit", "vehicle", "carry", "traded"):  # old databases
            if col not in cols:
                self.db.execute(f"ALTER TABLE account ADD COLUMN {col} TEXT")
                self.db.commit()
        row = self.db.execute("SELECT * FROM account ORDER BY ts DESC, id DESC LIMIT 1").fetchone()
        if row:
            self.cash = row["cash"]
            self.units = json.loads(row["units"])
            self.vehicle = row["vehicle"] or "USD"
            self.carry_total = float(row["carry"] or 0.0)

    def last(self) -> Optional[dict]:
        row = self.db.execute("SELECT * FROM account ORDER BY ts DESC, id DESC LIMIT 1").fetchone()
        return dict(row) if row else None

    def equity(self, prices: pd.Series) -> float:
        return self.cash + sum(u * float(prices[a]) for a, u in self.units.items())

    def rebalance(self, prices: pd.Series, weights: Dict[str, float]) -> float:
        """Two passes: estimate turnover, then size targets on the post-cost budget.

        The one-pass version invested the full equity and then subtracted the
        fees from cash, so cash went negative by exactly the cost of the trade
        -- the same bug `xs.py` fixed. Pinned by `test_no_leverage`.
        """
        total = self.equity(prices)
        tradable = {a: w for a, w in weights.items() if a in prices and pd.notna(prices[a])}
        traded = sum(abs(total * w - self.units.get(a, 0.0) * float(prices[a]))
                     for a, w in tradable.items())
        budget = max(total - traded * COST, 0.0)
        for a, w in tradable.items():
            self.units[a] = (budget * w) / float(prices[a])
        invested = sum(u * float(prices[a]) for a, u in self.units.items())
        self.cash = budget - invested
        return traded

    def rebalanced_in_month(self, year: int, month: int) -> bool:
        """True when a rebalance (or the opening trade) already happened this month."""
        for row in self.db.execute(
            "SELECT ts FROM account WHERE note IN ('init', 'rebalance', 'deposit')"
            " ORDER BY ts DESC LIMIT 12"
        ):
            d = datetime.fromtimestamp(int(row["ts"]), timezone.utc)
            if (d.year, d.month) == (year, month):
                return True
        return False

    def save(self, ts: int, equity: float, weights: Dict[str, float], note: str,
             positions: Optional[Dict[str, float]] = None,
             signals: Optional[Dict[str, float]] = None,
             deposit: float = 0.0, carry_this: float = 0.0, traded: float = 0.0) -> None:
        """`signals` is what the bot SAW when it decided, kept separately from the
        weights so a later viewer can audit the decision instead of re-deriving it."""
        self.db.execute(
            "INSERT OR REPLACE INTO account(ts, cash, units, equity, weights, note, positions,"
            " signals, deposit, vehicle, carry, traded) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (ts, self.cash, json.dumps(self.units), equity, json.dumps(weights), note,
             json.dumps(positions or {}), json.dumps(signals or {}), deposit,
             self.vehicle, carry_this, traded),
        )
        self.db.commit()

    def history(self, limit: int = 400) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM account ORDER BY ts DESC, id DESC LIMIT ?", (limit,)).fetchall()


def first_trading_day(now: Optional[datetime] = None) -> bool:
    """A weekday in the first three calendar days: the window in which the
    monthly rebalance may happen. The account itself makes sure it happens
    once, via `rebalanced_in_month`, not once per day of the window."""
    now = now or datetime.now(timezone.utc)
    return now.weekday() < 5 and now.day <= 3


def rebalance_due(acc: Account, now: Optional[datetime] = None) -> bool:
    now = now or datetime.now(timezone.utc)
    return first_trading_day(now) and not acc.rebalanced_in_month(now.year, now.month)


def run(state: str, cash: float, force: bool = False, span: str = "2y",
        deposit: float = 0.0, now: Optional[datetime] = None) -> dict:
    series = load_series(span)
    px = closes(series)
    latest = px.iloc[-1]
    ts = int(px.index[-1].timestamp())
    acc = Account(Path(state))
    fresh = acc.cash == 0.0 and not acc.units
    if fresh:
        acc.cash = cash
        deposit += cash          # opening capital counts as contributed, not as profit
    elif deposit:
        acc.cash += deposit

    sig = signals(series)
    weights, cash_w = target_weights(sig)

    due = fresh or force or rebalance_due(acc, now) or deposit > 0
    traded = 0.0
    note = "mark"
    if due:
        traded = acc.rebalance(latest, weights)
        note = "init" if fresh else ("deposit" if deposit else "rebalance")
    else:
        # a mark must not rewrite the decision it is marking: keep the snapshot
        prev = acc.last()
        if prev:
            weights = json.loads(prev.get("weights") or "{}") or weights
        prev_sig = json.loads((prev or {}).get("signals") or "{}") if prev else {}
        if prev_sig:
            sig = prev_sig

    # accrue interest on idle cash for the time since the last run
    prev_row = acc.last()
    carry_this = 0.0
    if prev_row and prev_row.get("vehicle"):
        days = max(0.0, (ts - int(prev_row["ts"])) / 86400.0)
        apy = next((v.apy for v in treasury.DEFAULT_VEHICLES if v.name == prev_row["vehicle"]), 0.0)
        carry_this = treasury.carry(acc.cash, apy, days)
        acc.cash += carry_this
        acc.carry_total += carry_this

    # decide where the uninvested cash lives
    decision = treasury.choose(acc.cash)
    acc.vehicle = decision.vehicle

    equity = acc.equity(latest)
    marked = {a: u * float(latest[a]) for a, u in acc.units.items()}
    acc.save(ts, equity, weights, note, positions=marked, signals=sig, deposit=deposit,
             carry_this=carry_this, traded=traded)
    return {
        "ts": px.index[-1], "signals": sig, "weights": weights, "cash_weight": cash_w,
        "equity": equity, "traded": traded, "note": note,
        "positions": {a: u * float(latest[a]) for a, u in acc.units.items()},
        "account": acc, "cash_decision": decision, "carry_total": acc.carry_total,
    }


def format_report(res: dict) -> str:
    lines = [f"as of {res['ts'].date()}  equity ${res['equity']:.2f}  ({res['note']})", ""]
    lines.append(f"{'asset':6s} {'12m return':>11s} {'target':>8s} {'current $':>10s}")
    for a in res["signals"]:
        pos = res["positions"].get(a, 0.0)
        lines.append(f"{a:6s} {100*res['signals'][a]:+10.1f}% {100*res['weights'][a]:7.0f}% {pos:10.2f}")
    idle = res['equity'] - sum(res['positions'].values())
    lines.append(f"{'cash':6s} {'':11s} {100*res['cash_weight']:7.0f}% {idle:10.2f}")
    d = res.get("cash_decision")
    if d:
        lines.append(f"\ncash ${d.amount + d.reserve:,.2f}: keep ${d.reserve:,.2f} liquid, "
                     f"sweep ${d.amount:,.2f} -> {d.vehicle}  ({d.reason})")
    if res.get("carry_total"):
        lines.append(f"carry accrued to date: ${res['carry_total']:+.2f}")
    if res["traded"]:
        lines.append(f"traded ${res['traded']:.2f} at {COST*1e4:.0f} bps a side")
    return "\n".join(lines)
