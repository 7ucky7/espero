"""Stop runs at yesterday's low reverse (#35, research/PREREGISTRATION_SWEEPS.md).

The frozen rule and its four criteria, pure. Each UTC day, the first time a coin trades
10 bps through yesterday's low, the sweep is "reclaimed" if a bar closes back above
the low within 15 minutes (the stops below it fired and are spent) and "failed"
otherwise. The long return after each is measured from the next bar's open.
research/sweeps.py loads the cached bars and prints the tables.
"""
from __future__ import annotations

from typing import List, Optional

import numpy as np
import pandas as pd

from .levetf import welch
from .liq import clustered, verdict  # noqa: F401 - verdict is part of this module's API

BAR_S = 300
DAY_BARS = 288
THROUGH = 0.001               # 10 bps through the level
RECLAIM = 3                   # bars after the sweep bar to close back inside (15 minutes)
HOLD, HOLD4 = 12, 48
FIRST, LAST = "2020-01-02", "2026-10-27"
HALF = "2023-05-01"
T_HURDLE = 3.0
LEG_HURDLE = 0.0018
COLUMNS = ["ts", "day", "side", "kind", "level", "r60", "r240"]


def _ret(ts, o, c, entry: int, hold: int, sign: float) -> float:
    end = entry + hold - 1
    if entry >= len(ts) or end >= len(ts) or ts[end] != ts[entry] + (hold - 1) * BAR_S:
        return np.nan
    return sign * float(c[end] / o[entry] - 1)


def events(b: pd.DataFrame, first: str = FIRST, last: str = LAST, side: str = "low",
           step: Optional[float] = None) -> pd.DataFrame:
    """The first sweep of the level on each day: yesterday's low (side 'low', a long after it) or
    high ('high', a paper short), or with `step` the round number below (above) the day's open."""
    ts = b.index.to_numpy(dtype="int64")
    o, h, lo, c = (b[x].to_numpy(dtype=float) for x in ("open", "high", "low", "close"))
    day = ts // 86400
    starts = np.flatnonzero(np.r_[True, day[1:] != day[:-1]])
    ends = np.r_[starts[1:], len(ts)]
    first_d = pd.Timestamp(first, tz="UTC").value // 10**9 // 86400
    last_d = pd.Timestamp(last, tz="UTC").value // 10**9 // 86400
    sign = 1.0 if side == "low" else -1.0
    rows: List[dict] = []
    for n in range(1, len(starts)):
        s, e = starts[n], ends[n]
        d = int(day[s])
        if not (first_d <= d <= last_d):
            continue
        if step is None:
            ps, pe = starts[n - 1], ends[n - 1]
            if day[ps] != d - 1 or pe - ps != DAY_BARS:
                continue
            level = float(lo[ps:pe].min()) if side == "low" else float(h[ps:pe].max())
        else:
            level = (np.floor(o[s] / step) if side == "low" else np.ceil(o[s] / step)) * step
            if level <= 0:
                continue
        if side == "low":
            hit = np.flatnonzero(lo[s:e] < level * (1 - THROUGH))
        else:
            hit = np.flatnonzero(h[s:e] > level * (1 + THROUGH))
        if not len(hit):
            continue
        j = s + int(hit[0])
        k = None
        for m in range(j, min(j + RECLAIM + 1, len(ts))):
            if ts[m] != ts[j] + (m - j) * BAR_S:
                break
            if (c[m] > level) if side == "low" else (c[m] < level):
                k = m
                break
        entry = (k + 1) if k is not None else (j + RECLAIM + 1)
        ok_entry = entry < len(ts) and ts[entry] == ts[j] + (entry - j) * BAR_S
        rows.append({"ts": int(ts[k if k is not None else j]) + BAR_S,
                     "day": pd.Timestamp(d * 86400, unit="s", tz="UTC").strftime("%Y-%m-%d"),
                     "side": side, "kind": "reclaimed" if k is not None else "failed", "level": level,
                     "r60": _ret(ts, o, c, entry, HOLD, sign) if ok_entry else np.nan,
                     "r240": _ret(ts, o, c, entry, HOLD4, sign) if ok_entry else np.nan})
    return pd.DataFrame(rows, columns=COLUMNS).astype({"ts": "int64", "level": float, "r60": float, "r240": float})


def by_day(ev: pd.DataFrame, col: str = "r60") -> pd.Series:
    return ev.dropna(subset=[col]).groupby("day")[col].mean()


def criteria(ev: pd.DataFrame) -> List[dict]:
    ev = ev[ev["side"] == "low"]
    rec, fail = ev[ev["kind"] == "reclaimed"], ev[ev["kind"] == "failed"]
    c1 = clustered(by_day(rec))
    c2 = welch(by_day(rec), by_day(fail))
    h1, h2 = clustered(by_day(rec[rec["day"] < HALF])), clustered(by_day(rec[rec["day"] >= HALF]))
    bps = lambda x: f"{1e4 * x:+.1f} bps"  # noqa: E731
    return [
        {"criterion": "the reversal: reclaimed sweeps' long 1h > 0, t >= 3",
         "actual": f"{bps(c1['mean'])}, t {c1['t']:.2f}, {c1['n']} days, {len(rec)} sweeps",
         "met": c1["mean"] > 0 and c1["t"] >= T_HURDLE},
        {"criterion": "the reclaim matters: reclaimed minus failed > 0, t >= 2",
         "actual": f"{bps(c2['diff'])}, t {c2['t']:.2f} ({len(fail)} failed)",
         "met": c2["diff"] > 0 and c2["t"] >= 2},
        {"criterion": "not one era: > 0 in both halves",
         "actual": f"{bps(h1['mean'])} (2020 -> Apr 2023), {bps(h2['mean'])} (May 2023 -> 2026)",
         "met": h1["mean"] > 0 and h2["mean"] > 0},
        {"criterion": "it pays: > 18 bps, t > 2",
         "actual": f"{bps(c1['mean'])}, t {c1['t']:.2f}",
         "met": c1["mean"] > LEG_HURDLE and c1["t"] > 2},
    ]
