"""What the accounts' 00:00 UTC fills cost (#33, research/PREREGISTRATION_FILLCOST.md).

The frozen measure and its criteria, pure: for each coin's Monday 00:00 UTC funding
settlement, the price drift in the 15, 30 and 60 minutes after the fill price P(00:00),
bucketed by the funding rate settled then (scaled to 8 hours). research/fillcost.py
loads the cached bars and funding and prints the tables.
"""
from __future__ import annotations

from typing import List

import numpy as np
import pandas as pd

from .liq import clustered

BAR_S = 300
FIRST, LAST = "2020-01-06", "2026-10-26"
HALF = "2023-06-01"
HARD = 0.0005                 # #19's 0.05%, per 8 hours
FLOOR = 0.0005                # criterion 2: at least 5 bps
HORIZONS = {"m15": 900, "m30": 1800, "m60": 3600}
COLUMNS = ["ts", "day", "rate8", "bucket", *HORIZONS]


def settlements(rows: List[dict]) -> pd.DataFrame:
    """Binance funding rows -> `ts` (the settlement's minute, seconds) and `rate8` (the rate
    scaled to 8 hours by the time since the coin's previous settlement)."""
    if not rows:
        return pd.DataFrame(columns=["ts", "rate8"])
    t = np.array([int(r["fundingTime"]) // 1000 for r in rows], dtype="int64")
    rate = np.array([float(r["fundingRate"]) for r in rows])
    order = np.argsort(t)
    t, rate = t[order] // 60 * 60, rate[order]
    hours = np.diff(t, prepend=t[0] - 8 * 3600) / 3600
    hours = np.where((hours >= 1) & (hours <= 8), np.round(hours), 8.0)
    return pd.DataFrame({"ts": t, "rate8": rate * 8 / hours}).drop_duplicates("ts")


def bucket(rate8: float) -> str:
    if rate8 >= HARD:
        return "longs pay"
    if rate8 <= -HARD:
        return "shorts pay"
    return "normal"


def events(b: pd.DataFrame, fund: pd.DataFrame, first: str = FIRST, last: str = LAST, hour: int = 0,
           mondays: bool = True) -> pd.DataFrame:
    """Every settlement at `hour`:00 UTC (Mondays only by default) from `first` to `last` with the
    price drift after it. A missing bar leaves that drift empty."""
    s = fund[(fund["ts"] % 86400) == hour * 3600]
    days = pd.to_datetime(s["ts"], unit="s", utc=True)
    keep = (days.dt.strftime("%Y-%m-%d") >= first) & (days.dt.strftime("%Y-%m-%d") <= last)
    if mondays:
        keep &= days.dt.weekday == 0
    s = s[keep.to_numpy()]
    opens = b["open"]
    p0 = opens.reindex(s["ts"].to_numpy()).to_numpy(dtype=float)
    out = pd.DataFrame({"ts": s["ts"].to_numpy(), "day": pd.to_datetime(s["ts"], unit="s", utc=True)
                        .dt.strftime("%Y-%m-%d").to_numpy(), "rate8": s["rate8"].to_numpy()})
    out["bucket"] = [bucket(r) for r in out["rate8"]]
    for name, h in HORIZONS.items():
        out[name] = opens.reindex(s["ts"].to_numpy() + h).to_numpy(dtype=float) / p0 - 1
    return out[COLUMNS]


def by_day(ev: pd.DataFrame, col: str = "m30") -> pd.Series:
    return ev.dropna(subset=[col]).groupby("day")[col].mean()


def criteria(ev: pd.DataFrame) -> List[dict]:
    longs, shorts = ev[ev["bucket"] == "longs pay"], ev[ev["bucket"] == "shorts pay"]
    c1 = clustered(by_day(longs))
    c3 = clustered(by_day(shorts))
    h1 = clustered(by_day(longs[longs["day"] < HALF]))
    h2 = clustered(by_day(longs[longs["day"] >= HALF]))
    bps = lambda x: f"{1e4 * x:+.1f} bps"  # noqa: E731
    return [
        {"criterion": "longs paying: the price recovers after 00:00, mean m30 > 0, t >= 3",
         "actual": f"{bps(c1['mean'])}, t {c1['t']:.2f}, {c1['n']} Mondays, {len(longs)} coin-Mondays",
         "met": c1["mean"] > 0 and c1["t"] >= 3},
        {"criterion": "big enough to move a fill: >= 5 bps",
         "actual": bps(c1["mean"]), "met": c1["mean"] >= FLOOR},
        {"criterion": "shorts paying: the mirror, mean m30 < 0",
         "actual": f"{bps(c3['mean'])}, t {c3['t']:.2f}, {c3['n']} Mondays, {len(shorts)} coin-Mondays",
         "met": c3["mean"] < 0},
        {"criterion": "not one era: criterion 1's mean > 0 in both halves",
         "actual": f"{bps(h1['mean'])} (2020 -> May 2023), {bps(h2['mean'])} (Jun 2023 -> 2026)",
         "met": h1["mean"] > 0 and h2["mean"] > 0},
    ]


def verdict(rows: List[dict]) -> str:
    return "PASS" if all(r["met"] for r in rows) else "FAIL"
