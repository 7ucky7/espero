"""Hypothesis #15: multi-asset trend, sized by volatility. The rule and the book, no I/O.

Frozen in research/PREREGISTRATION_TREND.md. Everything that carries the rule
lives here, as pure functions and one in-memory `Book`, so the research
simulator (research/trend.py), the board and any live account run the same
code; each owns only its loop.

    f      = share of the 28/91/364-day lookbacks over which the last close rose
    weight = f x budget x min(0.20 / vol, 2.0), gross <= 100%, the rest in cash
    budget = 1/4 per class, split equally among its eligible members;
             ALTS is one crypto member, split equally among the eligible alts

Dates are UTC calendar dates (tz-naive). A run on date D reads only bars dated
D - 1 or earlier: crypto bars close at 00:00 UTC of the next day and US ETF
sessions at 16:00 New York, both before 00:00 UTC of D. Decisions are made at
Monday's cutoff and filled after the 07:30 New York run that sends them: ETFs
at the next session's open, crypto at Monday's close.
"""
from __future__ import annotations

import datetime as dt
import itertools
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .xs import UNIVERSE as XS_UNIVERSE

# --------------------------------------------------------------- frozen rule
ALTS = "ALTS"
MAJORS = ("BTC-USD", "ETH-USD", "SOL-USD")
ALT_COINS = tuple(f"{c}-USD" for c in XS_UNIVERSE if f"{c}-USD" not in MAJORS)
CLASSES: Dict[str, Tuple[str, ...]] = {
    "equity": ("SPY", "QQQ", "IWM", "EFA", "EEM"),
    "bonds": ("TLT", "IEF"),
    "commodities": ("GLD", "SLV", "USO", "UNG", "DBA", "CPER"),
    "crypto": MAJORS + (ALTS,),
}
HORIZONS = (28, 91, 364)          # calendar days: 4, 13 and 52 weeks
HISTORY_DAYS = 364                # every lookback must exist
VOL_DAYS = 60
MIN_VOL_RETURNS = 20
TARGET_VOL = 0.20                 # #8's constants, reused
MAX_SCALE = 2.0
BAND = 0.01                       # trade only moves above 1% of equity, or entries and exits
COSTS = {"etf": 0.0005, "crypto": 0.0010}
DUST = 1e-12                      # share of equity below which a position or a buy is zero: float residue
ALT_MIN_CLOSES = 365              # #8's eligibility
ALT_MIN_DOLLAR_VOLUME = 1e6
ALT_VOLUME_DAYS = 30
ETF_FRESH_DAYS = 5
SIXTY_FORTY = {"SPY": 0.6, "TLT": 0.4}
CASH_PROXY = "BIL"                # information only
MODES = ("trend", "volonly", "static", "6040")

NEW_YORK = ZoneInfo("America/New_York")
RUN_TIME = dt.time(7, 30)         # the launchd job sends the decision
ETF_OPEN = dt.time(9, 30)

START = pd.Timestamp("2018-01-01")    # first decision cutoff (a Monday)
END = pd.Timestamp("2026-10-26")      # last decision cutoff (a Monday)


def kind(symbol: str) -> str:
    return "crypto" if symbol.endswith("-USD") else "etf"


def symbols(classes: Dict[str, Sequence[str]] = CLASSES) -> List[str]:
    """Every tradable symbol `classes` can hold, ALTS expanded."""
    out: List[str] = []
    for members in classes.values():
        for m in members:
            out.extend(ALT_COINS if m == ALTS else (m,))
    return list(dict.fromkeys(out))


def to_frame(df: pd.DataFrame) -> pd.DataFrame:
    """A yahoo_daily(adjusted=True) frame (or its CSV) indexed by UTC date. ETF bars
    are stamped at the session open (13:30 or 14:30 UTC), crypto at 00:00 UTC; both
    normalise to the trading date. A repeated date keeps the last row."""
    out = df.copy()
    when = pd.to_datetime(out["dt"], utc=True).dt.tz_localize(None).dt.normalize()
    out.index = pd.DatetimeIndex(when, name="date")
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return out[["ts", "open", "high", "low", "close", "adj_close", "volume"]].astype(float)


# ------------------------------------------------------------------- calendar
def cutoff(day) -> pd.Timestamp:
    return pd.Timestamp(day).normalize()


def complete(df: pd.DataFrame, asof) -> pd.DataFrame:
    """The rows a run on `asof`'s date may read: bars dated before it."""
    return df.iloc[: df.index.searchsorted(cutoff(asof), side="left")]


def last_adj(df: pd.DataFrame, asof) -> Optional[float]:
    i = df.index.searchsorted(cutoff(asof), side="left")
    return float(df["adj_close"].iat[i - 1]) if i else None


def fresh(df: pd.DataFrame, asof, kind_: str) -> bool:
    """`df` is complete as of `asof`. Crypto needs yesterday's bar (Yahoo sometimes
    drops the bar that has just closed); an ETF needs a session in the last 5 days."""
    if df.empty:
        return False
    last, a = df.index[-1], cutoff(asof)
    if kind_ == "crypto":
        return last == a - pd.Timedelta(days=1)
    return last >= a - pd.Timedelta(days=ETF_FRESH_DAYS)


def _utc(day, at: dt.time) -> pd.Timestamp:
    local = dt.datetime.combine(cutoff(day).date(), at, tzinfo=NEW_YORK)
    return pd.Timestamp(local.astimezone(dt.timezone.utc).replace(tzinfo=None))


def run_moment(day) -> pd.Timestamp:
    """07:30 New York on `day`, in UTC: when the scheduled run sends a decision."""
    return _utc(day, RUN_TIME)


def fill_moment(date, kind_: str) -> pd.Timestamp:
    """When a bar dated `date` can fill an order: an ETF at its 09:30 New York open,
    a coin at its close, 00:00 UTC of the next day."""
    if kind_ == "etf":
        return _utc(date, ETF_OPEN)
    return cutoff(date) + pd.Timedelta(days=1)


def fill_bar(df: pd.DataFrame, kind_: str, after: pd.Timestamp) -> Optional[pd.Timestamp]:
    """The first bar in `df` whose fill moment is strictly after `after`, else None."""
    i = df.index.searchsorted(cutoff(after) - pd.Timedelta(days=1), side="left")
    for date in df.index[i:]:
        if fill_moment(date, kind_) > after:
            return date
    return None


def adj_open(df: pd.DataFrame, date) -> float:
    """The open on the adjusted scale: Yahoo adjusts a whole day by one factor."""
    row = df.loc[date]
    return float(row["open"] * row["adj_close"] / row["close"])


# --------------------------------------------------------------------- signal
def has_history(px: pd.Series, days: int = HISTORY_DAYS) -> bool:
    return len(px) > 0 and px.index[0] <= px.index[-1] - pd.Timedelta(days=days)


def fraction(px: pd.Series, horizons: Sequence[int] = HORIZONS) -> Tuple[Optional[float], Dict[int, float]]:
    """Share of `horizons` (calendar days) over which the last close rose, and the
    references used: the last close on or before t - h. None if any is missing."""
    if px.empty:
        return None, {}
    t, last = px.index[-1], float(px.iloc[-1])
    refs: Dict[int, float] = {}
    for h in horizons:
        i = px.index.searchsorted(t - pd.Timedelta(days=h), side="right")
        if i == 0:
            return None, {}
        refs[h] = float(px.iloc[i - 1])
    return sum(last > r for r in refs.values()) / len(horizons), refs


def ann_vol(px: pd.Series, days: int = VOL_DAYS) -> Optional[float]:
    """Std of the daily log returns ending in the last `days` calendar days, annualised
    by the series' own number of closes in the last 364 days (about 252 for an ETF,
    364 for a coin). Fewer than MIN_VOL_RETURNS returns: None, and no position."""
    if len(px) < 2:
        return None
    t = px.index[-1]
    tail = px.iloc[px.index.searchsorted(t - pd.Timedelta(days=HISTORY_DAYS), side="right"):]
    if len(tail) < 2:
        return None
    with np.errstate(divide="ignore", invalid="ignore"):     # Yahoo prints SHIB's 2020 prices as 0
        rets = np.diff(np.log(tail.to_numpy(dtype=float)))
    window = rets[tail.index[1:] > t - pd.Timedelta(days=days)]
    if window.size < MIN_VOL_RETURNS:
        return None
    vol = float(np.std(window, ddof=1) * math.sqrt(len(tail)))
    return vol if math.isfinite(vol) else None              # NaN would slip past `if vol`


def alt_liquid(df: pd.DataFrame) -> bool:
    """#8's rule as panel.eligible computes it: 365 closes so far, and a mean of
    close x volume of at least $1M over the last 30 calendar days, all 30 present."""
    if len(df) < ALT_MIN_CLOSES:
        return False
    t = df.index[-1]
    win = df.iloc[df.index.searchsorted(t - pd.Timedelta(days=ALT_VOLUME_DAYS), side="right"):]
    if len(win) < ALT_VOLUME_DAYS:
        return False
    return float((win["close"] * win["volume"]).mean()) >= ALT_MIN_DOLLAR_VOLUME


# ------------------------------------------------------------------- decision
@dataclass
class View:
    """One asset at one cutoff: what the board shows and the book trades."""
    symbol: str
    cls: str
    member: str
    eligible: bool = False
    stale: bool = False               # no fresh bar: not traded this week
    why: str = ""                     # why not eligible
    f: Optional[float] = None
    refs: Dict[int, float] = field(default_factory=dict)
    vol: Optional[float] = None
    budget: float = 0.0
    weight: float = 0.0
    last: Optional[float] = None      # adjusted close
    last_raw: Optional[float] = None
    last_date: Optional[pd.Timestamp] = None


@dataclass
class Decision:
    asof: pd.Timestamp
    mode: str
    views: Dict[str, View]
    targets: Dict[str, float]         # weight per eligible symbol, zeros included
    stale: List[str]
    gross: float


def _view(frames: Dict[str, pd.DataFrame], sym: str, cls: str, member: str, a: pd.Timestamp,
          horizons: Sequence[int]) -> View:
    v = View(sym, cls, member)
    df = frames.get(sym)
    comp = complete(df, a) if df is not None else None
    if comp is None or comp.empty:
        v.stale, v.why = True, "no data"
        return v
    px = comp["adj_close"]
    v.last, v.last_raw, v.last_date = float(px.iat[-1]), float(comp["close"].iat[-1]), comp.index[-1]
    v.f, v.refs = fraction(px, horizons)
    v.vol = ann_vol(px)
    if not fresh(comp, a, kind(sym)):
        v.stale, v.why = True, "stale"
    elif not has_history(px):
        v.why = "history"
    elif member == ALTS and not alt_liquid(comp):
        v.why = "liquidity"
    else:
        v.eligible = True
    return v


def decide(frames: Dict[str, pd.DataFrame], asof, mode: str = "trend",
           horizons: Sequence[int] = HORIZONS,
           classes: Dict[str, Sequence[str]] = CLASSES) -> Decision:
    """Target weights at `asof`'s cutoff, from complete bars only.

    trend: the rule. volonly: f = 1 (vol-sized, always invested). static: f = 1
    and no vol scaling. 6040: SPY 60% / TLT 40%.
    """
    if mode not in MODES:
        raise ValueError(f"mode {mode!r} not in {MODES}")
    a = cutoff(asof)
    if mode == "6040":
        views = {s: _view(frames, s, "benchmark", s, a, horizons) for s in SIXTY_FORTY}
        for s, v in views.items():
            v.weight = SIXTY_FORTY[s] if v.eligible else 0.0
        return Decision(a, mode, views, {s: v.weight for s, v in views.items() if v.eligible},
                        [s for s, v in views.items() if v.stale], sum(v.weight for v in views.values()))

    views: Dict[str, View] = {}
    per_class = 1.0 / len(classes)
    for cls, members in classes.items():
        groups: List[List[View]] = []                 # one list per eligible member
        for m in members:
            group = []
            for sym in (ALT_COINS if m == ALTS else (m,)):
                v = _view(frames, sym, cls, m, a, horizons)
                views[sym] = v
                if v.eligible:
                    group.append(v)
            if group:
                groups.append(group)
        for group in groups:                          # a member with f = 0 keeps its share in cash
            for v in group:
                v.budget = per_class / len(groups) / len(group)

    for v in views.values():
        if not v.eligible:
            continue
        f = 1.0 if mode in ("volonly", "static") else (v.f or 0.0)
        if mode == "static":
            scale = 1.0
        else:
            scale = min(TARGET_VOL / v.vol, MAX_SCALE) if v.vol else 0.0
        v.weight = f * v.budget * scale
    gross = sum(v.weight for v in views.values())
    if gross > 1.0:
        for v in views.values():
            v.weight /= gross
        gross = 1.0
    return Decision(a, mode, views, {s: v.weight for s, v in views.items() if v.eligible},
                    [s for s, v in views.items() if v.stale], gross)


def expected_last(next_asof, kind_: str) -> pd.Timestamp:
    """The bar the next decision will read last, assuming no holiday."""
    d = cutoff(next_asof) - pd.Timedelta(days=1)
    while kind_ == "etf" and d.weekday() >= 5:
        d -= pd.Timedelta(days=1)
    return d


def flip_levels(df: pd.DataFrame, asof, next_asof, kind_: str,
                horizons: Sequence[int] = HORIZONS) -> Dict[int, float]:
    """For each horizon, the price the asset must close above at the next decision for
    that lookback to count as up: the next decision's reference close, put on today's
    raw scale (adjusted reference x raw last / adjusted last), so a dividend paid in
    between does not move the line."""
    comp = complete(df, asof)
    if comp.empty:
        return {}
    ratio = float(comp["close"].iat[-1] / comp["adj_close"].iat[-1])
    t_next = expected_last(next_asof, kind_)
    out = {}
    for h in horizons:
        i = comp.index.searchsorted(t_next - pd.Timedelta(days=h), side="right")
        if i:
            out[h] = float(comp["adj_close"].iat[i - 1]) * ratio
    return out


# ----------------------------------------------------------------------- book
@dataclass
class Order:
    symbol: str
    kind: str
    delta: float              # dollars at the decision mark
    px: float                 # the adjusted price `delta` was computed at
    decided: pd.Timestamp     # the Monday cutoff
    after: pd.Timestamp       # the run that placed it: fills strictly after this moment
    exit: bool = False        # sell everything, whatever the drift


@dataclass
class Fill:
    symbol: str
    date: pd.Timestamp
    amount: float             # dollars bought (+) or sold (-) at the fill price
    cost: float
    late: bool


@dataclass
class Book:
    """Dollar positions marked by adjusted-price ratios, so dividends accrue and a split
    restated into the history cannot break a share count. The research simulator and a
    live account drive this same object; they differ only in when they call it."""
    cash: float
    values: Dict[str, float] = field(default_factory=dict)
    marks: Dict[str, float] = field(default_factory=dict)
    pending: List[Order] = field(default_factory=list)
    pnl: Dict[str, float] = field(default_factory=dict)
    costs: float = 0.0
    traded: float = 0.0
    trades: int = 0
    late: int = 0
    cash_mark: Optional[float] = None

    def equity(self) -> float:
        return self.cash + sum(self.values.values())

    def _grow(self, sym: str, px: float) -> None:
        old = self.marks.get(sym)
        if sym in self.values and old:
            new = self.values[sym] * px / old
            self.pnl[sym] = self.pnl.get(sym, 0.0) + new - self.values[sym]
            self.values[sym] = new
        self.marks[sym] = px

    def mark(self, frames: Dict[str, pd.DataFrame], asof,
             cash_frame: Optional[pd.DataFrame] = None) -> float:
        """Mark every position at its last complete adjusted close; one with no newer
        price keeps its value. `cash_frame` (information only) grows idle cash with it."""
        for sym in list(self.values):
            df = frames.get(sym)
            px = last_adj(df, asof) if df is not None else None
            if px is not None:
                self._grow(sym, px)
        if cash_frame is not None:
            px = last_adj(cash_frame, asof)
            if px is not None:
                if self.cash_mark:
                    self.cash *= px / self.cash_mark
                self.cash_mark = px
        return self.equity()

    def fill(self, frames: Dict[str, pd.DataFrame], asof, cost_mult: float = 1.0) -> List[Fill]:
        """Execute every pending order whose fill bar has closed by `asof`, in time order.
        At each moment sells come first; buys and their costs are scaled down pro rata
        if they would take cash below zero."""
        ready, keep = [], []
        for o in self.pending:
            df = frames.get(o.symbol)
            bar = fill_bar(complete(df, asof), o.kind, o.after) if df is not None else None
            if bar is None:
                keep.append(o)
                continue
            px = adj_open(df, bar) if o.kind == "etf" else float(df["adj_close"].loc[bar])
            on_time = fill_bar(df, o.kind, run_moment(o.decided))
            ready.append((fill_moment(bar, o.kind), o, bar, px, bar != on_time))
        self.pending = keep
        fills: List[Fill] = []
        ready.sort(key=lambda r: (r[0], r[1].symbol))
        for _, group in itertools.groupby(ready, key=lambda r: r[0]):
            group = list(group)
            buys = []
            for _, o, bar, px, late in group:
                self._grow(o.symbol, px)
                c = COSTS[o.kind] * cost_mult
                held = self.values.get(o.symbol, 0.0)
                amount = -held if o.exit else o.delta * px / o.px
                if amount < 0 and held > 0:
                    sold = min(-amount, held)
                    self.values[o.symbol] = held - sold
                    if o.exit or self.values[o.symbol] <= DUST * self.equity():
                        self.values.pop(o.symbol, None)
                    self._book(o.symbol, -sold, sold * c, bar, late, fills)
                    self.cash += sold - sold * c
                elif amount > 0:
                    buys.append((o, bar, amount, c, late))
            need = sum(amount * (1 + c) for _, _, amount, c, _ in buys)
            scale = min(1.0, self.cash / need) if need > 0 else 1.0
            for o, bar, amount, c, late in buys:
                bought = amount * max(scale, 0.0)
                if bought <= DUST * self.equity():     # cash spent to the last 1e-17: buy nothing
                    continue
                self.values[o.symbol] = self.values.get(o.symbol, 0.0) + bought
                self._book(o.symbol, bought, bought * c, bar, late, fills)
                self.cash -= bought + bought * c
        return fills

    def _book(self, sym: str, amount: float, cost: float, bar, late: bool, fills: List[Fill]) -> None:
        self.costs += cost
        self.traded += abs(amount)
        self.trades += 1
        self.late += int(late)
        self.pnl[sym] = self.pnl.get(sym, 0.0) - cost
        fills.append(Fill(sym, bar, amount, cost, late))

    def rebalance(self, decision: Decision, frames: Dict[str, pd.DataFrame], after: pd.Timestamp,
                  band: float = BAND) -> List[Order]:
        """This week's orders, from values marked at the decision's cutoff. An order still
        pending from an earlier week is replaced. Stale assets are not traded."""
        equity = self.equity()
        dust = DUST * equity
        orders: List[Order] = []
        for sym in sorted(set(decision.targets) | {s for s, v in self.values.items() if v > dust}):
            if sym in decision.stale:
                continue
            target = decision.targets.get(sym, 0.0) * equity
            cur = self.values.get(sym, 0.0)
            cur = cur if cur > dust else 0.0
            enter, exit_ = cur <= 0 and target > 0, cur > 0 and target <= 0
            if not (enter or exit_ or abs(target - cur) > band * equity):
                continue
            px = self.marks.get(sym) if cur > 0 else last_adj(frames[sym], decision.asof)
            if not px:
                continue
            orders.append(Order(sym, kind(sym), target - cur, px, decision.asof, after, exit_))
        self.pending = orders
        return orders
