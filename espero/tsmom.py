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
    ts INTEGER PRIMARY KEY, cash REAL, units TEXT, equity REAL, weights TEXT, note TEXT,
    positions TEXT
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


def signals(series: Dict[str, pd.Series]) -> Dict[str, float]:
    out = {}
    for name, s in series.items():
        s = s.dropna()
        if len(s) > LOOKBACK:
            out[name] = float(s.iloc[-1] / s.iloc[-LOOKBACK - 1] - 1)
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

    def __post_init__(self):
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        cols = {r["name"] for r in self.db.execute("PRAGMA table_info(account)")}
        if "positions" not in cols:  # old databases
            self.db.execute("ALTER TABLE account ADD COLUMN positions TEXT")
            self.db.commit()
        row = self.db.execute("SELECT * FROM account ORDER BY ts DESC LIMIT 1").fetchone()
        if row:
            self.cash = row["cash"]
            self.units = json.loads(row["units"])

    def equity(self, prices: pd.Series) -> float:
        return self.cash + sum(u * float(prices[a]) for a, u in self.units.items())

    def rebalance(self, prices: pd.Series, weights: Dict[str, float]) -> float:
        total = self.equity(prices)
        traded = 0.0
        for a, w in weights.items():
            if a not in prices or not pd.notna(prices[a]):
                continue
            target = total * w
            current = self.units.get(a, 0.0) * float(prices[a])
            traded += abs(target - current)
            self.units[a] = target / float(prices[a])
        invested = sum(u * float(prices[a]) for a, u in self.units.items())
        self.cash = total - invested - traded * COST
        return traded

    def save(self, ts: int, equity: float, weights: Dict[str, float], note: str,
             positions: Optional[Dict[str, float]] = None) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO account(ts, cash, units, equity, weights, note, positions) "
            "VALUES (?,?,?,?,?,?,?)",
            (ts, self.cash, json.dumps(self.units), equity, json.dumps(weights), note,
             json.dumps(positions or {})),
        )
        self.db.commit()

    def history(self, limit: int = 400) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM account ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()


def first_trading_day(now: Optional[datetime] = None) -> bool:
    now = now or datetime.now(timezone.utc)
    return now.weekday() < 5 and now.day <= 3


def run(state: str, cash: float, force: bool = False, span: str = "2y") -> dict:
    series = load_series(span)
    px = closes(series)
    latest = px.iloc[-1]
    ts = int(px.index[-1].timestamp())
    acc = Account(Path(state))
    fresh = acc.cash == 0.0 and not acc.units
    if fresh:
        acc.cash = cash

    sig = signals(series)
    weights, cash_w = target_weights(sig)

    due = fresh or force or first_trading_day()
    traded = 0.0
    note = "mark"
    if due:
        traded = acc.rebalance(latest, weights)
        note = "init" if fresh and not force else "rebalance"

    equity = acc.equity(latest)
    marked = {a: u * float(latest[a]) for a, u in acc.units.items()}
    acc.save(ts, equity, weights, note, positions=marked)
    return {
        "ts": px.index[-1], "signals": sig, "weights": weights, "cash_weight": cash_w,
        "equity": equity, "traded": traded, "note": note,
        "positions": {a: u * float(latest[a]) for a, u in acc.units.items()},
        "account": acc,
    }


def format_report(res: dict) -> str:
    lines = [f"as of {res['ts'].date()}  equity ${res['equity']:.2f}  ({res['note']})", ""]
    lines.append(f"{'asset':6s} {'12m return':>11s} {'target':>8s} {'current $':>10s}")
    for a in res["signals"]:
        pos = res["positions"].get(a, 0.0)
        lines.append(f"{a:6s} {100*res['signals'][a]:+10.1f}% {100*res['weights'][a]:7.0f}% {pos:10.2f}")
    lines.append(f"{'cash':6s} {'':11s} {100*res['cash_weight']:7.0f}% {res['equity'] - sum(res['positions'].values()):10.2f}")
    if res["traded"]:
        lines.append(f"\ntraded ${res['traded']:.2f} at {COST*1e4:.0f} bps a side")
    return "\n".join(lines)
