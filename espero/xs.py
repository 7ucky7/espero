"""Weekly cross-sectional momentum: top-N of a crypto universe, equal weight.

Different from the TSMOM account in one important way: it holds many small
positions and rebalances weekly, so it generates ~500 bets a year instead of 60.
That is the only version of "breadth" a small account can actually buy.

    espero xs --cash 100 --deposit 500     # first run / deposit
    espero xs                              # weekly rebalance on Mondays, else mark
    espero xs --force                      # rebalance now

Data integrity rules, because the whole universe comes from one unofficial
endpoint:

* a coin whose last close is older than MAX_STALE_DAYS is not ranked
* if fewer than MIN_UNIVERSE coins are rankable the account marks but refuses
  to rebalance -- a shrunken universe would silently change the top-N
* a held coin that stops reporting is marked at its last known price, never
  dropped from equity
"""
from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

import pandas as pd

from . import data

log = logging.getLogger(__name__)

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
MIN_UNIVERSE = 30        # fewer rankable coins than this: mark, do not trade
MAX_STALE_DAYS = 2       # a close older than this is not a price, it is a memory

SCHEMA = """
CREATE TABLE IF NOT EXISTS xs_account (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL, cash REAL, units TEXT, equity REAL, weights TEXT,
    signals TEXT, positions TEXT, deposit REAL, note TEXT, last_px TEXT, traded REAL,
    UNIQUE(ts, note)
);
"""


def load_prices(span: str = "2y",
                fetch: Callable[[str, str], pd.DataFrame] = None,
                ) -> Tuple[Dict[str, pd.Series], Dict[str, str]]:
    """Daily closes per coin, plus a dict of the coins that could not be loaded
    and why. The caller decides whether the gaps are survivable."""
    fetch = fetch or data.yahoo_daily
    out: Dict[str, pd.Series] = {}
    errors: Dict[str, str] = {}
    for c in UNIVERSE:
        try:
            df = fetch(f"{c}-USD", span)
        except Exception as exc:  # noqa: BLE001 - recorded, then judged by run()
            errors[c] = f"{type(exc).__name__}: {exc}"
            continue
        if df.empty:
            errors[c] = "empty"
            continue
        df["dt"] = pd.to_datetime(df["dt"], utc=True).dt.tz_localize(None)
        s = df.set_index("dt")["close"].sort_index()
        if len(s) >= MIN_HISTORY:
            out[c] = s
        else:
            errors[c] = f"only {len(s)} closes"
    return out, errors


def split_stale(prices: Dict[str, pd.Series],
                max_stale_days: int = MAX_STALE_DAYS) -> Tuple[Dict[str, pd.Series], Dict[str, pd.Series]]:
    """(fresh, stale): a series is stale when its last close is older than the
    newest close in the universe by more than `max_stale_days`."""
    if not prices:
        return {}, {}
    newest = max(s.index[-1] for s in prices.values())
    cut = newest - pd.Timedelta(days=max_stale_days)
    fresh = {c: s for c, s in prices.items() if s.index[-1] >= cut}
    stale = {c: s for c, s in prices.items() if s.index[-1] < cut}
    return fresh, stale


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
    last_px: Dict[str, float] = field(default_factory=dict)

    def __post_init__(self):
        self.db = sqlite3.connect(self.path, timeout=5.0)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        cols = {r["name"] for r in self.db.execute("PRAGMA table_info(xs_account)")}
        for col, typ in (("last_px", "TEXT"), ("traded", "REAL")):  # pre-column databases
            if col not in cols:
                self.db.execute(f"ALTER TABLE xs_account ADD COLUMN {col} {typ}")
                self.db.commit()
        row = self.db.execute("SELECT * FROM xs_account ORDER BY ts DESC, id DESC LIMIT 1").fetchone()
        if row:
            self.cash = row["cash"]
            self.units = json.loads(row["units"])
            self.last_px = json.loads(row["last_px"] or "{}")

    def mark_prices(self, px: pd.Series) -> pd.Series:
        """Today's prices, falling back to the last known price for anything held
        that did not report. A position must never evaporate from equity."""
        merged = {c: float(v) for c, v in px.items() if pd.notna(v)}
        for c in self.units:
            if c not in merged:
                if c not in self.last_px:
                    raise ValueError(f"held {c} has no price today and no last known price")
                merged[c] = self.last_px[c]
        return pd.Series(merged, dtype=float)

    def equity(self, px: pd.Series) -> float:
        px = self.mark_prices(px)
        return self.cash + sum(u * float(px[c]) for c, u in self.units.items())

    def rebalance(self, px: pd.Series, weights: Dict[str, float]) -> float:
        """Two passes: estimate turnover, then size targets on the post-cost budget.

        A single pass invests the full equity and leaves cash negative by exactly
        the fees -- the first version did that, which is how an account with $600
        ends up owing the exchange $0.60.
        """
        px = self.mark_prices(px)
        total = self.equity(px)
        traded = sum(abs(total * w - self.units.get(c, 0.0) * float(px[c]))
                     for c, w in weights.items() if c in px and pd.notna(px[c]))
        budget = max(total - traded * COST, 0.0)
        for c, w in weights.items():
            if c not in px or not pd.notna(px[c]):
                continue
            self.units[c] = (budget * w) / float(px[c])
        self.units = {c: u for c, u in self.units.items() if u > 0}   # flat is absent, not zero
        invested = sum(u * float(px[c]) for c, u in self.units.items() if c in px)
        self.cash = budget - invested
        return traded

    def save(self, ts: int, equity: float, weights, sig, positions, deposit, note,
             last_px: Optional[Dict[str, float]] = None, traded: float = 0.0) -> None:
        if last_px is not None:
            self.last_px = {c: float(v) for c, v in last_px.items()}
        self.db.execute(
            "INSERT OR REPLACE INTO xs_account(ts, cash, units, equity, weights, signals,"
            " positions, deposit, note, last_px, traded) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (ts, self.cash, json.dumps(self.units), equity, json.dumps(weights),
             json.dumps(sig), json.dumps(positions), deposit, note, json.dumps(self.last_px), traded),
        )
        self.db.commit()


def run(state: str, cash: float, force: bool = False, deposit: float = 0.0,
        now: Optional[datetime] = None,
        fetch: Callable[[str, str], pd.DataFrame] = None) -> dict:
    prices, errors = load_prices(fetch=fetch)
    fresh_px, stale_px = split_stale(prices)
    for c, why in errors.items():
        log.warning("xs: %s not loaded: %s", c, why)
    for c, s in stale_px.items():
        log.warning("xs: %s stale, last close %s", c, s.index[-1].date())
    if not prices:
        raise RuntimeError(f"xs: no prices loaded ({len(errors)} errors)")

    latest = pd.Series({c: s.iloc[-1] for c, s in prices.items()})
    ts = int(max(s.index[-1] for s in prices.values()).timestamp())
    acc = XSAccount(Path(state))
    fresh = acc.cash == 0.0 and not acc.units
    if fresh:
        acc.cash = cash
        deposit += cash
    elif deposit:
        acc.cash += deposit

    degraded = len(fresh_px) < MIN_UNIVERSE
    sig = signals(fresh_px)
    w = targets(sig)
    due = fresh or force or is_rebalance_day(now) or deposit > 0 or not acc.units
    traded, note = 0.0, "mark"
    if due and degraded:
        log.error("xs: only %d/%d coins rankable; refusing to rebalance",
                  len(fresh_px), len(UNIVERSE))
        note = f"mark (degraded {len(fresh_px)}/{len(UNIVERSE)})"
        due = False
    if due:
        traded = acc.rebalance(latest, w)
        note = "init" if fresh else ("deposit" if deposit else "rebalance")
    else:
        prev = acc.db.execute(
            "SELECT weights, signals FROM xs_account ORDER BY ts DESC, id DESC LIMIT 1").fetchone()
        if prev:
            w = json.loads(prev["weights"]) or w
            sig = json.loads(prev["signals"]) or sig

    mark_px = acc.mark_prices(latest)
    equity = acc.equity(latest)
    marked = {c: u * float(mark_px[c]) for c, u in acc.units.items()}
    acc.save(ts, equity, w, sig, marked, deposit, note, last_px=mark_px.to_dict(), traded=traded)
    return {"ts": ts, "sig": sig, "weights": w, "equity": equity, "traded": traded,
            "note": note, "account": acc, "positions": marked,
            "errors": errors, "stale": sorted(stale_px), "degraded": degraded}


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
    if res.get("errors") or res.get("stale"):
        lines.append(f"\ndata: {len(res.get('errors', {}))} coins failed to load, "
                     f"{len(res.get('stale', []))} stale"
                     + ("  -- DEGRADED, no rebalance" if res.get("degraded") else ""))
    return "\n".join(lines)
