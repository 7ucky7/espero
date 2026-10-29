"""New 4-hour lows on volume bounce (#20, research/PREREGISTRATION_LOWS.md).

The frozen rule and its four criteria, pure: #18's `down` trigger (`liq.triggers`,
on #10's `degen.features`) on 5-minute bars, one event per coin per hour, a long
bought at the next bar's open. research/lows.py downloads Binance's archive.
"""
from __future__ import annotations

import datetime as dt
from typing import List, Optional, Set

import numpy as np
import pandas as pd

from . import liq
from .liq import clustered, verdict  # noqa: F401 - verdict is part of this module's API

BAR_S = 300
HOLD = 12                     # one event per coin per hour
HORIZONS = {"r15": 3, "r60": 12, "r240": 48}
FIRST_DAY = "2020-01-01"
LAST_DAY = "2026-03-31"
SPLIT = "2023-02-01"
T_HURDLE = 3.0
LEG_HURDLE = 0.0018
LEG_T = 2.0


def excluded_days(first: str = "2019-12-01", last: str = "2026-04-01") -> Set[str]:
    """#18's days: the first of every month, with the day before and the day after."""
    out: Set[str] = set()
    for m in pd.date_range(first, last, freq="MS"):
        for k in (-1, 0, 1):
            out.add((m + pd.Timedelta(days=k)).strftime("%Y-%m-%d"))
    return out


def bars(k: pd.DataFrame) -> pd.DataFrame:
    """Archive klines -> 5-minute bars indexed by their open in seconds (ms or µs in)."""
    t = k["open_time"].astype("int64").to_numpy()
    t = np.where(t > 10**14, t // 1000, t) // 1000
    out = pd.DataFrame({c: k[c].astype(float).to_numpy() for c in ("open", "high", "low", "close", "volume")},
                       index=pd.Index(t, name="ts"))
    return out[~out.index.duplicated(keep="last")].sort_index()


def events(b: pd.DataFrame, direction: str = "down", skip: Optional[Set[str]] = None,
           first: str = FIRST_DAY, last: str = LAST_DAY) -> pd.DataFrame:
    """Every trigger on `direction` ('down', or 'up' for #10's breakout) on a day from `first`
    to `last` not in `skip`, one per coin per hour (as #18: the hour after a counted event),
    with simple long returns from the next bar's open to the close 3, 12 and 48 bars after
    the trigger bar. A gap in the bars leaves a return empty."""
    f = liq.triggers(b)
    ts = f.index.to_numpy(dtype="int64")
    hit = np.flatnonzero(f[direction].to_numpy(dtype=bool))
    o, c = f["open"].to_numpy(), f["close"].to_numpy()
    days = pd.to_datetime(ts[hit], unit="s", utc=True).strftime("%Y-%m-%d") if len(hit) else []
    rows: List[dict] = []
    last_ts = None
    for i, day in zip(hit, days):
        if not (first <= day <= last) or (skip is not None and day in skip):
            continue
        if last_ts is not None and ts[i] - last_ts <= HOLD * BAR_S:
            continue                                  # the same move, its hour not over
        last_ts = ts[i]
        r = {"ts": int(ts[i]) + BAR_S, "day": day, "direction": direction}
        ok_entry = i + 1 < len(ts) and ts[i + 1] == ts[i] + BAR_S
        for name, k in HORIZONS.items():
            ok = ok_entry and i + k < len(ts) and ts[i + k] == ts[i] + k * BAR_S
            r[name] = float(c[i + k] / o[i + 1] - 1) if ok else np.nan
        rows.append(r)
    return pd.DataFrame(rows, columns=["ts", "day", "direction", *HORIZONS])


def by_day(x: pd.Series, day: pd.Series) -> pd.Series:
    ok = np.isfinite(x)
    return x[ok].groupby(day[ok]).mean()


def criteria(ev: pd.DataFrame) -> List[dict]:
    d = ev[ev["direction"] == "down"]
    r60 = by_day(d["r60"], d["day"])
    c1, c2 = clustered(r60), clustered(by_day(d["r15"], d["day"]))
    h1, h2 = clustered(r60[r60.index < SPLIT]), clustered(r60[r60.index >= SPLIT])

    def bps(v):
        return f"{1e4 * v:+.1f} bps"

    return [
        {"criterion": "the bounce: mean 1h long return > 0, t >= 3",
         "actual": f"{bps(c1['mean'])}, t {c1['t']:.2f}, {c1['n']} days",
         "met": c1["mean"] > 0 and c1["t"] >= T_HURDLE},
        {"criterion": "it starts at once: mean 15-minute return > 0",
         "actual": f"{bps(c2['mean'])} (t {c2['t']:.2f})", "met": c2["mean"] > 0},
        {"criterion": "not one era: 1h > 0 in both halves",
         "actual": f"{bps(h1['mean'])} ({h1['n']} days), {bps(h2['mean'])} ({h2['n']} days)",
         "met": h1["mean"] > 0 and h2["mean"] > 0},
        {"criterion": "it pays: mean 1h > 18 bps, t > 2",
         "actual": f"{bps(c1['mean'])}, t {c1['t']:.2f}", "met": c1["mean"] > LEG_HURDLE and c1["t"] > LEG_T},
    ]


def day_of(ts: int) -> str:
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%d")
