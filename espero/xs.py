"""Weekly cross-sectional momentum: top-N of a crypto universe, equal weight.

Different from the TSMOM account in one important way: it holds many small
positions and rebalances weekly, so it generates ~500 bets a year instead of 60.
That is the only version of "breadth" a small account can actually buy.

    espero xs --cash 100 --deposit 500     # first run / deposit
    espero xs                              # weekly rebalance on Mondays, else mark
    espero xs --force                      # rebalance now
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from . import data

UNIVERSE = [
    "BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "AVAX", "LINK", "DOT",
    "TRX", "SHIB", "LTC", "BCH", "ATOM", "ETC", "XLM", "NEAR", "ARB", "OP",
    "FIL", "INJ", "SEI", "TIA", "RUNE", "AAVE", "MKR", "CRV", "SNX", "SUSHI",
    "YFI", "ALGO", "XTZ", "EOS", "ZEC", "DASH", "KSM", "ICP", "HBAR", "VET",
    "THETA", "WLD",
]

TOP = 10
LOOKBACK_DAYS = 7
MIN_HISTORY = 180
COST = 0.0010

SCHEMA = """
CREATE TABLE IF NOT EXISTS xs_account (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL, cash REAL, units TEXT, equity REAL, weights TEXT,
    signals TEXT, positions TEXT, deposit REAL, note TEXT,
    UNIQUE(ts, note)
);
"""


def load_prices(span: str = "2y") -> Dict[str, pd.Series]:
    out = {}
    for c in UNIVERSE:
        try:
            df = data.yahoo_daily(f"{c}-USD", span)
        except Exception:
            continue
        df["dt"] = pd.to_datetime(df["dt"], utc=True).dt.tz_localize(None)
        s = df.set_index("dt")["close"].sort_index()
        if len(s) >= MIN_HISTORY:
            out[c] = s
    return out


def signals(prices: Dict[str, pd.Series], lookback_days: int = LOOKBACK_DAYS) -> Dict[str, float]:
    """Trailing return over `lookback_days` on the calendar, per coin."""
    out = {}
    for c, s in prices.items():
        s = s.dropna()
        ref = s[s.index <= s.index[-1] - pd.Timedelta(days=lookback_days)]
        if ref.empty or len(s) < MIN_HISTORY:
            continue
        out[c] = float(s.iloc[-1] / ref.iloc[-1] - 1)
    return out


def targets(sig: Dict[str, float], top: int = TOP) -> Dict[str, float]:
    picks = sorted(sig, key=sig.get, reverse=True)[:top]
    w = 1.0 / len(picks) if picks else 0.0
    return {c: (w if c in picks else 0.0) for c in sig}


def is_rebalance_day(now: Optional[datetime] = None) -> bool:
    now = now or datetime.now(timezone.utc)
    return now.weekday() == 0  # Monday


@dataclass
class XSAccount:
    path: Path
    cash: float = 0.0
    units: Dict[str, float] = field(default_factory=dict)

    def __post_init__(self):
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        row = self.db.execute("SELECT * FROM xs_account ORDER BY ts DESC, id DESC LIMIT 1").fetchone()
        if row:
            self.cash = row["cash"]
            self.units = json.loads(row["units"])

    def equity(self, px: pd.Series) -> float:
        return self.cash + sum(u * float(px[c]) for c, u in self.units.items() if c in px)

    def rebalance(self, px: pd.Series, weights: Dict[str, float]) -> float:
        """Two passes: estimate turnover, then size targets on the post-cost budget.

        A single pass invests the full equity and leaves cash negative by exactly
        the fees -- the first version did that, which is how an account with $600
        ends up owing the exchange $0.60.
        """
        total = self.equity(px)
        traded = sum(abs(total * w - self.units.get(c, 0.0) * float(px[c]))
                     for c, w in weights.items() if c in px and pd.notna(px[c]))
        budget = max(total - traded * COST, 0.0)
        for c, w in weights.items():
            if c not in px or not pd.notna(px[c]):
                continue
            self.units[c] = (budget * w) / float(px[c])
        invested = sum(u * float(px[c]) for c, u in self.units.items() if c in px)
        self.cash = budget - invested
        return traded

    def save(self, ts: int, equity: float, weights, sig, positions, deposit, note) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO xs_account(ts, cash, units, equity, weights, signals,"
            " positions, deposit, note) VALUES (?,?,?,?,?,?,?,?,?)",
            (ts, self.cash, json.dumps(self.units), equity, json.dumps(weights),
             json.dumps(sig), json.dumps(positions), deposit, note),
        )
        self.db.commit()


def run(state: str, cash: float, force: bool = False, deposit: float = 0.0) -> dict:
    prices = load_prices()
    latest = pd.Series({c: s.iloc[-1] for c, s in prices.items()})
    ts = int(max(s.index[-1] for s in prices.values()).timestamp())
    acc = XSAccount(Path(state))
    fresh = acc.cash == 0.0 and not acc.units
    if fresh:
        acc.cash = cash
        deposit += cash
    elif deposit:
        acc.cash += deposit

    sig = signals(prices)
    w = targets(sig)
    due = fresh or force or is_rebalance_day() or deposit > 0
    traded, note = 0.0, "mark"
    if due:
        traded = acc.rebalance(latest, w)
        note = "init" if fresh else ("deposit" if deposit else "rebalance")
    else:
        prev = acc.db.execute("SELECT weights, signals FROM xs_account ORDER BY ts DESC, id DESC LIMIT 1").fetchone()
        if prev:
            w = json.loads(prev["weights"]) or w
            sig = json.loads(prev["signals"]) or sig

    equity = acc.equity(latest)
    marked = {c: u * float(latest[c]) for c, u in acc.units.items() if c in latest}
    acc.save(ts, equity, w, sig, marked, deposit, note)
    return {"ts": ts, "sig": sig, "weights": w, "equity": equity, "traded": traded,
            "note": note, "account": acc, "positions": marked}


def format_report(res: dict) -> str:
    lines = [f"equity ${res['equity']:,.2f}  ({res['note']})", ""]
    held = [(c, w) for c, w in res["weights"].items() if w > 0]
    lines.append(f"{'coin':6s} {'7d':>8s} {'weight':>7s} {'value':>9s}")
    for c, w in sorted(held, key=lambda x: -x[1]):
        v = res["positions"].get(c, 0.0)
        lines.append(f"{c:6s} {100*res['sig'].get(c, 0):+7.1f}% {100*w:6.0f}% {v:9.2f}")
    cash = res["equity"] - sum(res["positions"].values())
    lines.append(f"{'cash':6s} {'':8s} {100*cash/max(res['equity'],1e-9):6.0f}% {cash:9.2f}")
    if res["traded"]:
        lines.append(f"\ntraded ${res['traded']:,.2f} at {COST*1e4:.0f} bps a side")
    return "\n".join(lines)
