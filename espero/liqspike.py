"""Liquidation spikes reverse (#21, research/PREREGISTRATION_LIQSPIKE.md).

The frozen rule, causal, and the four criteria; pure, no I/O.
research/liqspike.py reads aggr's sealed months and builds the exploration's
hourly panel (`research/aggr_explore.py::panel`, unchanged).

* `spikes`: an hour whose liquidation share on one side is above the 98th
  percentile of the coin's previous 720 hours, the first of its cascade
* `events`: every spike in the test window with the returns from its close
* `baseline`: the mean return of every coin-hour in the window, per horizon
* `criteria`: reversal on both sides, each side's sign, both halves, the long leg
"""
from __future__ import annotations

from typing import Dict, List

import numpy as np
import pandas as pd

from .liq import clustered, verdict  # noqa: F401 - verdict is part of this module's API

TRAIL_H = 720
MIN_TRAIL = 600
Q = 0.98
GAP_H = 6
HORIZONS = (1, 4, 24)
TEST_FROM = pd.Timestamp("2026-07-01 00:00", tz="UTC")
TEST_TO = pd.Timestamp("2026-10-27 23:00", tz="UTC")      # the last spike hour with 24 hours after it
SPLIT = "2026-09-01"
T_HURDLE = 3.0
LEG_HURDLE = 0.0018
LEG_T = 2.0


def spikes(df: pd.DataFrame, side: str, start=TEST_FROM, end=TEST_TO) -> pd.DatetimeIndex:
    """Spike hours on `side` ('long' or 'short' liquidated) from `start` to `end`. The
    threshold is the 98th percentile of the share over the previous 720 hours (at least
    600 present), so an hour is judged on the past only. A qualifying hour within 6 hours
    of the previous qualifying hour belongs to that cascade, wherever the previous one
    fell."""
    share = df[side] / df["volume"]
    thr = share.shift(1).rolling(TRAIL_H, min_periods=MIN_TRAIL).quantile(Q)
    hot = share[(share > thr) & (df[side] > 0)].index
    keep, last = [], None
    for t in hot:
        if last is None or (t - last) > pd.Timedelta(hours=GAP_H):
            keep.append(t)
        last = t
    out = pd.DatetimeIndex(keep) if keep else df.index[:0]       # empty keeps the index's timezone
    return out[(out >= start) & (out <= end)]


def events(p: Dict[str, pd.DataFrame], start=TEST_FROM, end=TEST_TO) -> pd.DataFrame:
    """Every spike with log returns from its hour's close (r1, r4, r24) and, for
    information, from the next hour's open (r24_open)."""
    rows: List[dict] = []
    for c, df in p.items():
        lc, lo = np.log(df["close"].to_numpy()), np.log(df["open"].to_numpy())
        n = len(df)
        for side in ("long", "short"):
            for t in spikes(df, side, start, end):
                i = df.index.get_loc(t)
                r = {"coin": c, "side": side, "t": t, "day": t.strftime("%Y-%m-%d"),
                     "usd": float(df[side].iat[i]), "share": float(df[side].iat[i] / df["volume"].iat[i]),
                     "r0": float(lc[i] - lo[i])}
                for k in HORIZONS:
                    r[f"r{k}"] = float(lc[i + k] - lc[i]) if i + k < n else np.nan
                r["r24_open"] = float(lc[i + 24] - lo[i + 1]) if i + 24 < n else np.nan
                rows.append(r)
    cols = ["coin", "side", "t", "day", "usd", "share", "r0", *[f"r{k}" for k in HORIZONS], "r24_open"]
    return pd.DataFrame(rows, columns=cols)


def baseline(p: Dict[str, pd.DataFrame], start=TEST_FROM, end=TEST_TO) -> Dict[int, float]:
    """The mean k-hour log return from the close of every coin-hour from `start` to `end`."""
    out = {}
    for k in HORIZONS:
        vals = []
        for df in p.values():
            lc = np.log(df["close"])
            fwd = (lc.shift(-k) - lc)[(df.index >= start) & (df.index <= end)]
            vals.append(fwd.to_numpy())
        out[k] = float(np.nanmean(np.concatenate(vals)))
    return out


def by_day(x: pd.Series, day: pd.Series) -> pd.Series:
    ok = np.isfinite(x)
    return x[ok].groupby(day[ok]).mean()


def reversal(ev: pd.DataFrame, base: Dict[int, float], k: int = 24) -> pd.Series:
    """R: the excess k-hour return, signed so the forced move coming back is positive."""
    x = ev[f"r{k}"] - base[k]
    return x.where(ev["side"] == "long", -x)


def criteria(ev: pd.DataFrame, base: Dict[int, float]) -> List[dict]:
    r = by_day(reversal(ev, base), ev["day"])
    c1 = clustered(r)
    longs, shorts = ev[ev["side"] == "long"], ev[ev["side"] == "short"]
    lx = clustered(by_day(longs["r24"] - base[24], longs["day"]))
    sx = clustered(by_day(shorts["r24"] - base[24], shorts["day"]))
    h1, h2 = clustered(r[r.index < SPLIT]), clustered(r[r.index >= SPLIT])
    leg = clustered(by_day(np.expm1(longs["r24"]), longs["day"]))

    def bps(v):
        return f"{1e4 * v:+.1f} bps"

    return [
        {"criterion": "forced flow reverts: mean R > 0, t >= 3",
         "actual": f"R {bps(c1['mean'])}, t {c1['t']:.2f}, {c1['n']} days",
         "met": c1["mean"] > 0 and c1["t"] >= T_HURDLE},
        {"criterion": "each side: excess 24h > 0 after long spikes, < 0 after short spikes",
         "actual": f"longs {bps(lx['mean'])} (t {lx['t']:.2f}), shorts {bps(sx['mean'])} (t {sx['t']:.2f})",
         "met": lx["mean"] > 0 and sx["mean"] < 0},
        {"criterion": "not one stretch: R > 0 in both halves",
         "actual": f"{bps(h1['mean'])} ({h1['n']} days), {bps(h2['mean'])} ({h2['n']} days)",
         "met": h1["mean"] > 0 and h2["mean"] > 0},
        {"criterion": "a long-only trade pays: raw 24h after long spikes > 18 bps, t > 2",
         "actual": f"{bps(leg['mean'])}, t {leg['t']:.2f}, {leg['n']} days",
         "met": leg["mean"] > LEG_HURDLE and leg["t"] > LEG_T},
    ]
