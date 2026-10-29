"""Polymarket's hourly bitcoin crowd against a random walk (#37, research/PREREGISTRATION_POLYHOUR.md).

Pure. Each hourly "Bitcoin Up or Down" market resolves Up if Binance's 1-hour candle closes
at or above its open. At minute 30 the crowd's price of Up is set against a random-walk
binary option: Phi(ln(P30/P0) / (sigma * sqrt(30))), sigma per minute from the day before.
When they differ by 5 points the model's side is bought at the crowd's price, 1 cent a
share in costs. research/polyhour.py fetches the markets and prints the tables.
"""
from __future__ import annotations

import datetime as dt
import math
from typing import List, Optional

import numpy as np
import pandas as pd

from .levetf import ET
from .liq import clustered

FIRST, LAST = "2026-05-01", "2026-10-27"
HALF = "2026-08-01"
BAR_S = 300
THRESHOLD = 0.05
COST = 0.01
STALE_S = 120


def slug(d: dt.date, hour: int) -> str:
    """The event's slug for the hour starting at `hour`:00 ET on date d."""
    h12 = hour % 12 or 12
    return f"bitcoin-up-or-down-{d.strftime('%B').lower()}-{d.day}-{d.year}-{h12}{'am' if hour < 12 else 'pm'}-et"


def hour_start(d: dt.date, hour: int) -> int:
    return int(dt.datetime(d.year, d.month, d.day, hour, tzinfo=ET).timestamp())


def crowd(history: List[dict], at: int, stale: int = STALE_S) -> float:
    """The last price at or before `at`, if it is no older than `stale` seconds."""
    pts = [(int(h["t"]), float(h["p"])) for h in history if int(h["t"]) <= at]
    if not pts:
        return math.nan
    t, p = max(pts)
    return p if at - t <= stale else math.nan


def model(b: pd.DataFrame, t0: int, minute: int = 30) -> float:
    """The random walk's chance that the hour from t0 closes at or above its open, at t0 + minute."""
    o = b["open"]
    p0, pm = o.get(t0, math.nan), o.get(t0 + minute * 60, math.nan)
    past = b["open"].reindex(np.arange(t0 - 288 * BAR_S, t0 + BAR_S, BAR_S))
    if past.isna().any() or not (p0 > 0 and pm > 0):
        return math.nan
    sigma = float(np.log(past).diff().dropna().std(ddof=1)) / math.sqrt(5)
    left = 60 - minute
    if sigma <= 0:
        return math.nan
    z = math.log(pm / p0) / (sigma * math.sqrt(left))
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def bet(p: float, q: float, outcome: float, threshold: float = THRESHOLD, cost: float = COST) -> float:
    """Profit per $1 share of buying the model's side at the crowd's price; NaN if no bet."""
    if not (np.isfinite(p) and np.isfinite(q)) or abs(q - p) < threshold:
        return math.nan
    return (outcome - p if q > p else p - outcome) - cost


def brier(x: pd.Series, outcome: pd.Series) -> float:
    return float(((x - outcome) ** 2).mean())


def criteria(df: pd.DataFrame) -> List[dict]:
    bets = df.dropna(subset=["profit"])
    c1 = clustered(bets.groupby("day")["profit"].mean())
    h1 = clustered(bets[bets["day"] < HALF].groupby("day")["profit"].mean())
    h2 = clustered(bets[bets["day"] >= HALF].groupby("day")["profit"].mean())
    both = df.dropna(subset=["p", "q"])
    bq, bp = brier(both["q"], both["outcome"]), brier(both["p"], both["outcome"])
    return [
        {"criterion": "it pays: mean profit per bet > 0, t >= 3",
         "actual": f"{100 * c1['mean']:+.2f} cents a share, t {c1['t']:.2f}, {len(bets)} bets on {c1['n']} days",
         "met": c1["mean"] > 0 and c1["t"] >= 3},
        {"criterion": "not one stretch: > 0 in each half",
         "actual": f"{100 * h1['mean']:+.2f} (May-Jul), {100 * h2['mean']:+.2f} (Aug-Oct) cents",
         "met": h1["mean"] > 0 and h2["mean"] > 0},
        {"criterion": "the model is the better forecaster: Brier(q) < Brier(p)",
         "actual": f"Brier model {bq:.4f}, crowd {bp:.4f}, {len(both)} markets",
         "met": bq < bp},
    ]


def verdict(rows: List[dict]) -> str:
    return "PASS" if all(r["met"] for r in rows) else "FAIL"


def market_row(m: dict, b: pd.DataFrame, minute: int = 30, threshold: float = THRESHOLD,
               cost: float = COST) -> Optional[dict]:
    """One cached market (slug, start, outcome, history, volume) -> its row; None if unresolved."""
    if m.get("outcome") is None:
        return None
    t0 = int(m["start"])
    p = crowd(m.get("history") or [], t0 + minute * 60)
    q = model(b, t0, minute)
    p0 = crowd(m.get("history") or [], t0)
    o = b["open"]
    prev = o.get(t0, math.nan) / o.get(t0 - 3600, math.nan) - 1
    return {"slug": m["slug"], "day": pd.Timestamp(t0, unit="s", tz="UTC").strftime("%Y-%m-%d"),
            "hour_et": int(m["hour"]), "p": p, "q": q, "outcome": float(m["outcome"]),
            "profit": bet(p, q, float(m["outcome"]), threshold, cost), "p0": p0, "prev_ret": prev,
            "volume": float(m.get("volume") or 0)}
