"""Transaction cost analysis for the paper accounts.

The accounts simulate fills at the close with a flat cost. TCA here answers
the only question that matters for a small book: how much of the return is
being paid away, and would it survive a worse venue.

Each trade row stores `traded` (dollar turnover) when the account wrote it;
older rows are estimated from the change in marked positions, which also
contains price drift and is labelled as an estimate.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

TRADE_NOTES = ("init", "rebalance", "deposit")


@dataclass
class Trade:
    ts: int
    note: str
    equity: float
    traded: float
    cost: float
    estimated: bool

    @property
    def bps(self) -> float:
        return 1e4 * self.cost / self.equity if self.equity else 0.0


@dataclass
class TCA:
    trades: List[Trade] = field(default_factory=list)
    span_days: float = 0.0
    cost_rate: float = 0.0

    @property
    def n(self) -> int:
        return len(self.trades)

    @property
    def total_cost(self) -> float:
        return sum(t.cost for t in self.trades)

    @property
    def avg_bps(self) -> float:
        return sum(t.bps for t in self.trades) / self.n if self.n else 0.0

    @property
    def turnover_per_year(self) -> float:
        """Dollar turnover as a multiple of equity, annualized."""
        if self.span_days <= 0 or not self.trades:
            return 0.0
        ratio = sum(t.traded / t.equity for t in self.trades if t.equity)
        return ratio * 365.0 / self.span_days

    @property
    def drag_per_year(self) -> float:
        """Fraction of equity paid in costs per year at the account's cost rate."""
        return self.turnover_per_year * self.cost_rate

    def drag_at(self, cost_rate: float) -> float:
        """The same book on a venue with a different per-side cost."""
        return self.turnover_per_year * cost_rate

    @property
    def any_estimated(self) -> bool:
        return any(t.estimated for t in self.trades)


def _estimate_traded(prev: Optional[dict], row: dict) -> float:
    if prev is None:
        return sum(json.loads(row.get("positions") or "{}").values())
    a = json.loads(prev.get("positions") or "{}")
    b = json.loads(row.get("positions") or "{}")
    return sum(abs(b.get(k, 0.0) - a.get(k, 0.0)) for k in set(a) | set(b))


def account_tca(db_path: Path, table: str, cost_rate: float) -> TCA:
    db_path = Path(db_path)
    if not db_path.exists():
        return TCA(cost_rate=cost_rate)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in con.execute(f"SELECT * FROM {table} ORDER BY ts, id")]
    except sqlite3.OperationalError:
        rows = []
    finally:
        con.close()
    if not rows:
        return TCA(cost_rate=cost_rate)
    out = TCA(cost_rate=cost_rate, span_days=max(0.0, (rows[-1]["ts"] - rows[0]["ts"]) / 86400.0))
    prev = None
    for r in rows:
        note = (r.get("note") or "").split(" ")[0]
        if note in TRADE_NOTES:
            stored = r.get("traded")
            estimated = stored is None
            traded = float(stored) if not estimated else _estimate_traded(prev, r)
            equity = float(r.get("equity") or 0.0)
            out.trades.append(Trade(int(r["ts"]), note, equity, traded, traded * cost_rate, estimated))
        prev = r
    return out


def format_line(t: TCA, venue_bps: float = 120.0) -> str:
    if not t.n:
        return "no trades yet"
    est = " (est.)" if t.any_estimated else ""
    return (f"{t.n} trades · ${t.total_cost:,.2f} paid{est} · {t.avg_bps:.0f} bps avg · "
            f"turnover {t.turnover_per_year:.1f}x/yr · drag {100 * t.drag_per_year:.1f}%/yr "
            f"(would be {100 * t.drag_at(venue_bps / 1e4):.1f}%/yr at {venue_bps:.0f} bps)")
