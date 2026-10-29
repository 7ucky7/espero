"""Breakdowns made of closing positions bounce more (#25, research/PREREGISTRATION_OI.md).

Pure pieces: the open-interest series from Binance's `metrics` files, each
breakdown's open-interest drop over the hour before its close, and the four
criteria. The within-day grouping is #18's (`liq.tag`, `liq.day_diff`), unchanged.
"""
from __future__ import annotations

from typing import List

import numpy as np
import pandas as pd

from . import data, liq
from .liq import clustered, verdict  # noqa: F401 - verdict is part of this module's API

FIRST_DAY = "2021-01-01"
LAST_DAY = "2026-03-31"
SPLIT = "2023-09-01"
T_HURDLE = 3.0
LEG_HURDLE = 0.0018
LEG_T = 2.0


def series(metrics: pd.DataFrame) -> pd.Series:
    """`sum_open_interest` indexed by `create_time` in unix seconds (UTC), sorted, one per time."""
    # data.unix_seconds: right at any resolution pandas parses to (research/ERRATA.md, 2026-10-28)
    t = data.unix_seconds(pd.to_datetime(metrics["create_time"], utc=True)).to_numpy(dtype="int64")
    s = pd.Series(metrics["sum_open_interest"].astype(float).to_numpy(), index=t)
    return s[~s.index.duplicated(keep="last")].sort_index()


def at_or_before(oi: pd.Series, t: np.ndarray) -> np.ndarray:
    """The last snapshot at or before each time; NaN where there is none."""
    if oi.empty:
        return np.full(len(t), np.nan)
    i = np.searchsorted(oi.index.to_numpy(), t, side="right") - 1
    out = oi.to_numpy()[np.clip(i, 0, None)].astype(float)
    out[i < 0] = np.nan
    return out


def drop(ev: pd.DataFrame, oi: pd.Series) -> np.ndarray:
    """(OI an hour before the trigger bar's close - OI at it) / OI an hour before."""
    close_t = ev["ts"].to_numpy(dtype="int64")          # lows.events stamps the trigger bar's close
    before, now = at_or_before(oi, close_t - 3600), at_or_before(oi, close_t)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(before > 0, (before - now) / before, np.nan)


def criteria(ev: pd.DataFrame) -> List[dict]:
    """`ev`: down-breaks with day, coin, oi_drop and r60."""
    d = clustered(liq.day_diff(ev, "oi_drop", "r60"))
    centred = ev.assign(oi_coin=ev["oi_drop"] - ev.groupby("coin")["oi_drop"].transform("mean"))
    c2 = clustered(liq.day_diff(centred, "oi_coin", "r60"))
    per_day = liq.day_diff(ev, "oi_drop", "r60")
    h1, h2 = clustered(per_day[per_day.index < SPLIT]), clustered(per_day[per_day.index >= SPLIT])
    use = liq.usable(ev, "oi_drop", "r60")
    forced = use[liq.tag(use, "oi_drop") == "forced"]
    leg = clustered(forced["r60"].groupby(forced["day"]).mean())

    def bps(v):
        return f"{1e4 * v:+.1f} bps"

    return [
        {"criterion": "forced breakdowns bounce more: mean D > 0, t >= 3",
         "actual": f"D {bps(d['mean'])}, t {d['t']:.2f}, {d['n']} days", "met": d["mean"] > 0 and d["t"] >= T_HURDLE},
        {"criterion": "not the coin mix: D on coin-centred oi_drop > 0",
         "actual": f"D {bps(c2['mean'])}, t {c2['t']:.2f}", "met": c2["mean"] > 0},
        {"criterion": "not one era: D > 0 in both halves",
         "actual": f"{bps(h1['mean'])} ({h1['n']} days), {bps(h2['mean'])} ({h2['n']} days)",
         "met": h1["mean"] > 0 and h2["mean"] > 0},
        {"criterion": "it pays: forced breakdowns' 1h > 18 bps, t > 2",
         "actual": f"{bps(leg['mean'])}, t {leg['t']:.2f}, {leg['n']} days",
         "met": leg["mean"] > LEG_HURDLE and leg["t"] > LEG_T},
    ]
