"""Resting bids catch forced sellers (#30, research/PREREGISTRATION_BIDS.md).

The frozen rule and its four criteria, pure. After #20's breakdown (a new 4-hour low
on a volume spike, one event per coin per hour) a bid rests one ATR below the trigger
close for an hour. It fills at its own price only when the market trades 1 bp through
it. A resting sell at the trigger close takes the profit; otherwise the position is
sold at the close 12 bars after the fill. #20's own trade, taken at the market, is the
baseline. research/bids.py loads the bars and prints the tables.
"""
from __future__ import annotations

from typing import List, Optional, Set

import numpy as np
import pandas as pd

from . import liq, lows
from .liq import clustered

BAR_S = 300
FIRST_DAY, LAST_DAY = "2026-04-01", "2026-10-26"
HALF = "2026-07-01"
K_ATR = 1.0                   # the bid's depth below the trigger close, in ATRs
LIFE = 12                     # bars the bid rests
HOLD = 12                     # bars a filled position is held at most
EPS = 0.0001                  # a resting order fills only when the price trades 1 bp through it
MAKER = 0.00015               # Hyperliquid's base fees
TAKER = 0.00045
SLIP = 0.0002                 # per taker fill
FLOOR = 0.0005                # criterion 1: at least 5 bps a fill
T_HURDLE = 3.0
D_T = 2.0
MIN_FILLS = 20
COLUMNS = ["ts", "day", "complete", "filled", "exit", "depth", "gross", "net", "r60", "taker_net", "value"]


def events(b: pd.DataFrame, skip: Optional[Set[str]] = None, first: str = FIRST_DAY, last: str = LAST_DAY,
           k: float = K_ATR, life: int = LIFE, hold: int = HOLD, eps: float = EPS,
           target: str = "close", taker_bars: int = lows.HOLD) -> pd.DataFrame:
    """Every #20 breakdown on a day from `first` to `last` not in `skip`, one per coin per hour,
    with the resting bid's fate. `target` is 'close' (sell back at the trigger close) or 'atr'
    (the entry plus one ATR). The taker baseline holds `taker_bars`: #20's hour by default,
    #24's four hours for #31. An event whose bars after the trigger are not all present is kept
    with complete=False and no numbers."""
    f = liq.triggers(b)
    ts = f.index.to_numpy(dtype="int64")
    o, h, lo, c = (f[x].to_numpy(dtype=float) for x in ("open", "high", "low", "close"))
    atr = f["atr"].to_numpy(dtype=float)
    hit = np.flatnonzero(f["down"].to_numpy(dtype=bool))
    days = pd.to_datetime(ts[hit], unit="s", utc=True).strftime("%Y-%m-%d") if len(hit) else []
    span = life + hold
    rows: List[dict] = []
    last_ts = None
    for i, day in zip(hit, days):
        if not (first <= day <= last) or (skip is not None and day in skip):
            continue
        if last_ts is not None and ts[i] - last_ts <= lows.HOLD * BAR_S:
            continue                                  # the same move, its hour not over (#20)
        last_ts = ts[i]
        r = {"ts": int(ts[i]) + BAR_S, "day": day, "complete": False, "filled": False, "exit": "",
             "depth": k * atr[i] / c[i], "gross": np.nan, "net": np.nan, "r60": np.nan,
             "taker_net": np.nan, "value": np.nan}
        n = max(span, taker_bars, lows.HOLD)
        if not (i + n < len(ts) and ts[i + n] == ts[i] + n * BAR_S):
            rows.append(r)
            continue
        r["complete"] = True
        r["r60"] = float(c[i + lows.HOLD] / o[i + 1] - 1)
        r["taker_net"] = float(c[i + taker_bars] / o[i + 1] - 1) - 2 * (TAKER + SLIP)
        bid = c[i] - k * atr[i]
        sell = c[i] if target == "close" else bid + atr[i]
        fill = next((j for j in range(i + 1, i + life + 1) if lo[j] < bid * (1 - eps)), None)
        if fill is None or bid <= 0:
            r["value"] = 0.0
            rows.append(r)
            continue
        hit_sell = next((m for m in range(fill + 1, fill + hold + 1) if h[m] > sell * (1 + eps)), None)
        if hit_sell is not None:
            exit_px, cost, r["exit"] = sell, MAKER + MAKER, "target"
        else:
            exit_px, cost, r["exit"] = c[fill + hold], MAKER + TAKER + SLIP, "timeout"
        r["filled"] = True
        r["gross"] = float(exit_px / bid - 1)
        r["net"] = r["gross"] - cost
        r["value"] = r["net"]
        rows.append(r)
    # typed even when empty: an empty object frame turns every number column to object on concat
    return pd.DataFrame(rows, columns=COLUMNS).astype(
        {"ts": "int64", "complete": bool, "filled": bool, "depth": float, "gross": float, "net": float,
         "r60": float, "taker_net": float, "value": float})


def criteria(ev: pd.DataFrame, half: str = HALF, names=("Apr-Jun", "Jul-Oct")) -> List[dict]:
    """The four pre-registered criteria, each with its actual value and whether it is met.
    `half` starts the second half, `names` labels the two (#31 passes its own)."""
    ev = ev[ev["complete"].astype(bool)]
    fills = ev[ev["filled"].astype(bool)]
    c1 = clustered(lows.by_day(fills["net"], fills["day"]))
    c2 = clustered(lows.by_day(ev["value"] - ev["taker_net"], ev["day"]))
    first, second = fills[fills["day"] < half], fills[fills["day"] >= half]
    h1 = clustered(lows.by_day(first["net"], first["day"]))
    h2 = clustered(lows.by_day(second["net"], second["day"]))
    per = fills.groupby("coin")["net"].agg(["size", "mean"])
    per = per[per["size"] >= MIN_FILLS]
    share = float((per["mean"] > 0).mean()) if len(per) else float("nan")
    bps = lambda x: f"{1e4 * x:+.1f} bps"  # noqa: E731
    return [
        {"criterion": "it pays: filled trades' mean net >= 5 bps, t >= 3",
         "actual": f"{bps(c1['mean'])}, t {c1['t']:.2f}, {c1['n']} days, {len(fills)} fills",
         "met": c1["mean"] >= FLOOR and c1["t"] >= T_HURDLE},
        {"criterion": "the bid beats taking: per event, bid minus taker > 0, t >= 2",
         "actual": f"{bps(c2['mean'])}, t {c2['t']:.2f}, {c2['n']} days, {len(ev)} events",
         "met": c2["mean"] > 0 and c2["t"] >= D_T},
        {"criterion": "not one stretch: mean net > 0 in each half",
         "actual": f"{bps(h1['mean'])} ({names[0]}), {bps(h2['mean'])} ({names[1]})",
         "met": h1["mean"] > 0 and h2["mean"] > 0},
        {"criterion": "not one coin: more than half of coins with >= 20 fills net > 0",
         "actual": f"{int((per['mean'] > 0).sum())} of {len(per)} coins",
         "met": share > 0.5},
    ]


def verdict(rows: List[dict]) -> str:
    """PASS needs all four; anything else fails, named when only the comparison with taking fails."""
    met = [r["met"] for r in rows]
    if all(met):
        return "PASS"
    if met[0] and met[2] and met[3]:
        return "FAIL (it pays, but no better than taking)"
    return "FAIL"
