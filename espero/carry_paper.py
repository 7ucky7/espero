"""The #12 forward paper book: funding carry on live Hyperliquid data, one hour at a time.

`CarryBook` is the stateful twin of `carry.simulate`: the same rule, the same
accounting, applied to one settled hour at a time and persisted in SQLite so a
restart resumes the open hedges. `tests/test_carry_paper.py` replays the same
synthetic series through both and requires the equity curves to agree to the
cent; that test is what makes the forward numbers comparable to the backtest.

Two books run side by side for the forward test (research/PREREGISTRATION_CARRY2.md):
`costs="taker"` charges #11's costs, `costs="maker"` charges #12's. Both see the
same funding, so the gap between them is what execution is worth.

Nothing here places an order anywhere.
"""
from __future__ import annotations

import datetime as dt
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

import numpy as np
import pandas as pd

from . import carry
from . import hyperliquid as hl

COSTS = {
    "taker": {"spot_fee": carry.SPOT_FEES["binanceus"], "perp_fee": carry.PERP_FEE,
              "slippage": carry.SLIPPAGE},
    "maker": {"spot_fee": carry.MAKER["spot"]["binanceus"], "perp_fee": carry.MAKER["perp"],
              "slippage": carry.MAKER["slippage"]},
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, coin TEXT NOT NULL, entry_ts INTEGER NOT NULL,
    qty_spot REAL, qty_perp REAL, perp_entry REAL, spot_entry REAL,
    fees REAL DEFAULT 0, funding REAL DEFAULT 0,
    exit_ts INTEGER, basis REAL, pnl REAL, reason TEXT
);
CREATE TABLE IF NOT EXISTS hours (
    ts INTEGER PRIMARY KEY, cash REAL, equity REAL, open INTEGER, coins INTEGER
);
CREATE TABLE IF NOT EXISTS events (ts INTEGER, text TEXT);
"""


@dataclass
class Row:
    """One coin's settled hour: hourly funding rate, trailing-week annualised
    funding (NaN until a full window exists), perp close, spot close."""
    funding: float
    f_ann: float
    perp: float
    spot: float


def usable(r: Row) -> bool:
    """Funding and both prices are finite, positive where they must be. `f_ann`
    may be NaN (a short history); the rule handles that itself."""
    return (np.isfinite(r.funding) and np.isfinite(r.perp) and np.isfinite(r.spot)
            and r.perp > 0 and r.spot > 0)


class CarryBook:
    def __init__(self, path: str | Path, costs: str = "maker", initial: float = 500.0,
                 swap_gap: float = carry.SWAP_GAP, min_hold: int = carry.MIN_HOLD_H,
                 enter: float = carry.ENTER_ANN, exit_: float = carry.EXIT_ANN,
                 max_coins: int = carry.MAX_COINS, max_hold: int = carry.MAX_HOLD_H):
        self.path = str(path)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.c = dict(COSTS[costs])
        self.costs = costs
        self.swap_gap, self.min_hold = swap_gap, min_hold
        self.enter, self.exit_, self.max_coins, self.max_hold = enter, exit_, max_coins, max_hold
        if self._meta("initial") is None:
            self._set("initial", initial)
            self._set("cash", initial)
            self._set("costs", costs)
            self.db.commit()
        elif self._meta("costs") not in (None, costs):
            raise ValueError(f"{self.path} was opened with costs={self._meta('costs')}, not {costs}")
        self.initial = float(self._meta("initial"))
        self.cash = float(self._meta("cash"))

    # ------------------------------------------------------------- persistence
    def _meta(self, key: str) -> Optional[str]:
        r = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return None if r is None else r["value"]

    def _set(self, key: str, value) -> None:
        self.db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, str(value)))

    def last_ts(self) -> Optional[int]:
        v = self._meta("last_ts")
        return None if v is None else int(v)

    def open_positions(self) -> List[sqlite3.Row]:
        return self.db.execute("SELECT * FROM positions WHERE exit_ts IS NULL ORDER BY entry_ts").fetchall()

    def closed_positions(self) -> List[sqlite3.Row]:
        return self.db.execute("SELECT * FROM positions WHERE exit_ts IS NOT NULL ORDER BY exit_ts").fetchall()

    def equity_curve(self) -> List[sqlite3.Row]:
        return self.db.execute("SELECT * FROM hours ORDER BY ts").fetchall()

    def events(self, limit: int = 20) -> List[sqlite3.Row]:
        return self.db.execute("SELECT * FROM events ORDER BY ts DESC, rowid DESC LIMIT ?", (limit,)).fetchall()

    def close(self) -> None:
        self.db.close()

    # --------------------------------------------------------------- accounting
    def equity(self, rows: Dict[str, Row]) -> float:
        v = self.cash
        for p in self.open_positions():
            r = rows.get(p["coin"])
            if r is None:
                # no fresh mark: value at entry (flat), rather than invent a price
                v += p["qty_spot"] * p["spot_entry"]
                continue
            v += p["qty_spot"] * r.spot + p["qty_perp"] * (p["perp_entry"] - r.perp)
        return v

    def _close(self, p: sqlite3.Row, ts: int, r: Row, reason: str, out: List[str]) -> None:
        spot_val = p["qty_spot"] * r.spot
        perp_val = p["qty_perp"] * r.perp
        fee = (spot_val * (self.c["spot_fee"] + self.c["slippage"])
               + perp_val * (self.c["perp_fee"] + self.c["slippage"]))
        self.cash += spot_val + p["qty_perp"] * (p["perp_entry"] - r.perp) - fee
        basis = p["qty_spot"] * (r.spot - p["spot_entry"]) - p["qty_perp"] * (r.perp - p["perp_entry"])
        fees = p["fees"] + fee
        pnl = p["funding"] + basis - fees
        self.db.execute("UPDATE positions SET exit_ts=?, fees=?, basis=?, pnl=?, reason=? WHERE id=?",
                        (ts, fees, basis, pnl, reason, p["id"]))
        out.append(f"{p['coin']}: exit {reason}  funding {p['funding']:+.2f}  basis {basis:+.2f}  "
                   f"fees {fees:.2f}  pnl {pnl:+.2f}")

    def _open(self, coin: str, ts: int, r: Row, notional: float, out: List[str]) -> None:
        fee = (notional * (self.c["spot_fee"] + self.c["slippage"])
               + notional * (self.c["perp_fee"] + self.c["slippage"]))
        self.cash -= notional + fee
        self.db.execute(
            "INSERT INTO positions (coin, entry_ts, qty_spot, qty_perp, perp_entry, spot_entry, fees) "
            "VALUES (?,?,?,?,?,?,?)", (coin, ts, notional / r.spot, notional / r.perp, r.perp, r.spot, fee))
        out.append(f"{coin}: short perp @ {r.perp:.6g}, long spot @ {r.spot:.6g}, "
                   f"{notional:.2f} a leg, funding {r.f_ann:+.1%} ann, fee {fee:.2f}")

    # ------------------------------------------------------------------- cycle
    def on_hour(self, ts: int, rows: Dict[str, Row], universe: Optional[List[str]] = None) -> List[str]:
        """One settled hour. Same order as carry.simulate: funding, exits, swaps
        and entries, mark. Idempotent on `ts`: a repeated hour is ignored.

        One hour is one transaction: if anything raises, its writes are rolled
        back, cash is reloaded and the error propagates. A coin whose funding,
        perp or spot is not a finite number is treated as missing this hour
        (kept, marked flat), never allowed near cash. `universe`, when given,
        limits new entries to those coins: rows for held coins outside it are
        there so the hedge is still managed, not so it can be re-entered."""
        try:
            return self._on_hour(ts, rows, universe)
        except Exception:
            self.db.rollback()
            self.cash = float(self._meta("cash"))
            raise

    def _on_hour(self, ts: int, rows: Dict[str, Row], universe: Optional[List[str]] = None) -> List[str]:
        last = self.last_ts()
        if last is not None and ts <= last:
            return []
        rows = {c: r for c, r in rows.items() if usable(r)}
        out: List[str] = []
        held = {p["coin"]: p for p in self.open_positions()}

        # 1. funding on every open short
        for coin, p in held.items():
            r = rows.get(coin)
            if r is None or np.isnan(r.funding):
                continue
            credit = r.funding * p["qty_perp"] * r.perp
            self.cash += credit
            self.db.execute("UPDATE positions SET funding = funding + ? WHERE id=?", (credit, p["id"]))

        held = {p["coin"]: p for p in self.open_positions()}

        # 2. exits
        for coin, p in list(held.items()):
            r = rows.get(coin)
            if r is None:
                continue                     # no data this hour: keep, mark flat
            reason = None
            if np.isnan(r.f_ann) or np.isnan(r.perp) or np.isnan(r.spot):
                reason = "no_data"
            elif r.f_ann < self.exit_:
                reason = "funding_low"
            elif (ts - p["entry_ts"]) // 3600 >= self.max_hold:
                reason = "time"
            if reason:
                self._close(p, ts, r, reason, out)
                del held[coin]

        # 3. swaps and entries
        allowed = set(rows) if universe is None else set(universe)
        cands = [c for c, r in rows.items() if c not in held and c in allowed and not np.isnan(r.f_ann)
                 and r.f_ann > self.enter and not np.isnan(r.perp) and not np.isnan(r.spot)]
        if cands:
            cands.sort(key=lambda c: -rows[c].f_ann)
            ranked = list(held)
            free = self.max_coins - len(ranked)
            ranked += cands[:free]
            for cand in cands[free:]:
                swappable = [c for c in ranked if c in held and c in rows
                             and (ts - held[c]["entry_ts"]) // 3600 >= self.min_hold]
                if not swappable:
                    break
                weakest = min(swappable, key=lambda c: rows[c].f_ann)
                if rows[cand].f_ann - rows[weakest].f_ann < max(self.swap_gap, 1e-12):
                    break
                self._close(held[weakest], ts, rows[weakest], "ranked_out", out)
                del held[weakest]
                ranked[ranked.index(weakest)] = cand
            equity_now = self.equity(rows)
            for coin in ranked:
                if coin in held:
                    continue
                self._open(coin, ts, rows[coin], equity_now / (2 * len(ranked)), out)

        eq = self.equity(rows)
        self.db.execute("INSERT OR REPLACE INTO hours VALUES (?,?,?,?,?)",
                        (ts, self.cash, eq, len(self.open_positions()), len(rows)))
        for text in out:
            self.db.execute("INSERT INTO events VALUES (?,?)", (ts, text))
        self._set("cash", self.cash)
        self._set("last_ts", ts)
        self.db.commit()
        return out

    def summary(self) -> dict:
        curve = self.equity_curve()
        closed = self.closed_positions()
        eq = [r["equity"] for r in curve]
        peak, dd = -np.inf, 0.0
        for v in eq:
            peak = max(peak, v)
            dd = max(dd, 1 - v / peak)
        funding = sum(r["funding"] for r in closed) + sum(p["funding"] for p in self.open_positions())
        return {
            "costs": self.costs, "initial": self.initial, "cash": self.cash,
            "equity": eq[-1] if eq else self.initial, "hours": len(curve),
            "open": len(self.open_positions()), "closed": len(closed),
            "funding": funding, "fees": sum(r["fees"] for r in closed) + sum(p["fees"] for p in self.open_positions()),
            "basis": sum(r["basis"] for r in closed), "max_dd": dd,
            "pnl": (eq[-1] if eq else self.initial) - self.initial,
            "first_ts": curve[0]["ts"] if curve else None, "last_ts": curve[-1]["ts"] if curve else None,
        }


# ------------------------------------------------------------------ live data
MAX_BACKFILL_H = 72        # how far back a restarted loop catches up
PUBLISH_GRACE_S = 1200     # wait this long for a lagging coin before booking an hour without it


def settled_hours(coins: List[str], since_ts: Optional[int] = None, lookback_h: int = carry.LOOKBACK_H,
                  fetch=None, spot_fetch: Optional[Callable[[str], pd.DataFrame]] = None,
                  pause: float = 0.3, sleep=time.sleep, now: Optional[float] = None,
                  max_backfill_h: int = MAX_BACKFILL_H,
                  grace_s: int = PUBLISH_GRACE_S) -> List[tuple[int, Dict[str, Row]]]:
    """Every settled hour after `since_ts`, oldest first, as `(ts, rows)`.

    With `since_ts=None` (a new book) only the latest settled hour comes back.
    Otherwise every hour the loop missed (the Mac slept, the loop restarted, a
    fetch failed) is rebuilt from history, up to `max_backfill_h` back, so the
    book credits the same funding `carry.simulate` would.

    Per coin and hour: funding from `fundingHistory` (the row for hour T exists
    once T has settled), `f_ann` the mean of the `lookback_h` rates up to T, the
    perp close of the 1h candle opening at T, Coinbase's spot close at T. A coin
    missing any of them, or with a non-finite value, is left out of that hour.

    The newest hour is held back while any coin has not published it (or its
    fetch failed), for up to `grace_s` after settlement, so one slow or
    rate-limited coin does not lose its funding for good."""
    from .data import recent_closed_bars
    post = fetch or (lambda body: hl.post(body, hl.info_url(testnet=False)))
    now_s = int(time.time() if now is None else now)
    floor = now_s - max_backfill_h * 3600
    first = now_s - 2 * 3600 if since_ts is None else max(since_ts + 3600, floor)
    start_ms = (first - (lookback_h + 4) * 3600) * 1000
    pages = (now_s - start_ms // 1000) // (500 * 3600) + 2
    raw: Dict[str, dict] = {}
    for coin in coins:
        try:
            f = hl.funding_history(coin, start_ms, fetch=post, pages=pages, sleep=sleep)
            if len(f) < lookback_h:
                continue        # too new to rank; not a lagging coin, so no grace wait
            p = hl.candles(coin, "1h", (first - 6 * 3600) * 1000, now_s * 1000, fetch=post, sleep=sleep)
            s = spot_fetch(f"{coin}-USD") if spot_fetch else recent_closed_bars(f"{coin}-USD", 3600, 300)
            raw[coin] = {"f": f, "p": p, "s": s}
        except Exception as exc:  # noqa: BLE001 - one coin's outage is not the book's
            raw[coin] = {"error": f"{type(exc).__name__}: {exc}"}
        sleep(pause)
    fetched = {c: v for c, v in raw.items() if "f" in v}
    if not fetched:
        return []
    latest = max(int(v["f"]["ts"].iloc[-1]) for v in fetched.values())
    if since_ts is None:
        hours = [latest]
    else:
        hours = sorted({int(t) for v in fetched.values() for t in v["f"]["ts"]
                        if since_ts < int(t) <= latest and int(t) >= floor})
    complete = len(fetched) == len(raw) and all(int(v["f"]["ts"].iloc[-1]) == latest for v in fetched.values())
    if hours and hours[-1] == latest and not complete and now_s - latest < grace_s:
        hours = hours[:-1]
    out: List[tuple[int, Dict[str, Row]]] = []
    for ts in hours:
        rows: Dict[str, Row] = {}
        for coin, v in fetched.items():
            f = v["f"]
            upto = f[f["ts"] <= ts]
            if not len(upto) or int(upto["ts"].iloc[-1]) != ts:
                continue
            f_ann = (float(upto["funding"].tail(lookback_h).mean() * carry.HOURS_PER_YEAR)
                     if len(upto) >= lookback_h else float("nan"))
            r = Row(funding=float(upto["funding"].iloc[-1]), f_ann=f_ann,
                    perp=_close_at(v["p"], ts), spot=_close_at(v["s"], ts))
            if usable(r):
                rows[coin] = r
        if rows:
            out.append((ts, rows))
    return out


def settled_rows(coins: List[str], lookback_h: int = carry.LOOKBACK_H, fetch=None,
                 spot_fetch: Optional[Callable[[str], pd.DataFrame]] = None,
                 pause: float = 0.3, sleep=time.sleep) -> tuple[Optional[int], Dict[str, Row]]:
    """The latest settled hour and its rows, or (None, {}). Kept for callers
    that want one hour; the loop uses `settled_hours`."""
    hours = settled_hours(coins, None, lookback_h, fetch, spot_fetch, pause, sleep, grace_s=0)
    return hours[-1] if hours else (None, {})


def _close_at(df: pd.DataFrame, ts: int) -> float:
    """Close of the bar that opens at `ts` (the hour that just settled); the
    latest earlier close if that bar is not published yet; NaN if nothing."""
    if df is None or len(df) == 0:
        return float("nan")
    if "ts" in df.columns:
        t = df["ts"].astype(int)
    else:
        t = pd.to_datetime(df["time"], utc=True).astype("int64") // 10**9
    ok = df[t <= ts]
    return float(ok["close"].iloc[-1]) if len(ok) else float("nan")


def universe(top: int = 20, fetch=None, products: Optional[set] = None) -> List[str]:
    """Top perps by open interest that have a Coinbase USD spot pair."""
    from .data import list_products
    post = fetch or (lambda body: hl.post(body, hl.info_url(testnet=False)))
    ctxs = hl.asset_contexts(fetch=post)
    spot = products if products is not None else set(list_products(exclude=()))
    return [c for c in hl.top_by_open_interest(top, ctxs) if f"{c}-USD" in spot]


def stamp(ts: int) -> str:
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%d %H:%M")
