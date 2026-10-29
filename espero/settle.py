"""The funding settlement as a price event (#19, research/PREREGISTRATION_SETTLE.md).

Binance's perpetuals settle funding every 8 hours. When the rate is high, longs
who will not pay close before the instant and reopen after it, and arbitrageurs
open a short just before it and close it just after: both sell into the
settlement and buy after it. These are the test's frozen pieces, pure and
without I/O (research/settle.py downloads):

* `settlements`: Binance funding rows -> 8-hour settlements with the previous rate
* `hourly`: archive klines -> hourly bars indexed by their open, in seconds
* `events`: every settlement's windows: the hour before and after it, and the
  same around the placebo 4 hours later, on perpetual and spot bars
* `excess`, `criteria`: against the same hour's baseline coins, settlement minus
  placebo, and the four pre-registered criteria, every UTC day counted once
"""
from __future__ import annotations

from typing import List, Optional

import numpy as np
import pandas as pd

from .liq import clustered, verdict  # noqa: F401 - verdict is part of this module's API

HOUR = 3600
INTERVAL_S = 8 * HOUR
PLACEBO_S = 4 * HOUR
HIGH = 0.0005                 # |previous rate| at or above this: avoiding or collecting it pays
BASE = 0.000125               # at or below: the default 0.01% and near zero
MIN_BASELINE = 3
T_HURDLE = 3.0
LEG_HURDLE = 0.0018           # two Hyperliquid taker round trips
LEG_T = 2.0
SPLIT = "2023-05-01"


def spot_symbol(coin: str) -> str:
    return f"{coin}USDT"         # SHIBUSDT on spot; the perpetual is 1000SHIBUSDT (liq.symbol)


# ------------------------------------------------------------------- inputs
def settlements(rows: List[dict]) -> pd.DataFrame:
    """Binance funding rows -> one row per 8-hour settlement: ts (seconds, on the hour),
    rate (settling now), prev (settled 8 hours earlier) and placebo_ok (the next
    settlement is 8 hours later, so nothing settles at ts + 4h). Settlements after a
    4-hour or 1-hour interval are dropped."""
    if not rows:
        return pd.DataFrame(columns=["ts", "rate", "prev", "placebo_ok"])
    df = pd.DataFrame({"ts": [int(round(int(r["fundingTime"]) / 1000 / HOUR)) * HOUR for r in rows],
                       "rate": [float(r["fundingRate"]) for r in rows]})
    df = df.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
    gap_before, gap_after = df["ts"].diff(), df["ts"].shift(-1) - df["ts"]
    df["prev"] = df["rate"].shift(1)
    df["placebo_ok"] = gap_after == INTERVAL_S
    return df[gap_before == INTERVAL_S].reset_index(drop=True)


def hourly(k: pd.DataFrame) -> pd.DataFrame:
    """Archive klines -> open and close indexed by the bar's open in seconds. The
    archive's times are milliseconds (spot switched to microseconds in 2025)."""
    t = k["open_time"].astype("int64")
    t = np.where(t > 10**14, t // 1000, t) // 1000
    out = pd.DataFrame({"open": k["open"].astype(float).to_numpy(), "close": k["close"].astype(float).to_numpy()},
                       index=pd.Index(t // HOUR * HOUR, name="ts"))
    return out[~out.index.duplicated(keep="last")].sort_index()


# ------------------------------------------------------------------- events
def _bar(bars: Optional[pd.DataFrame], start: np.ndarray, end: np.ndarray) -> np.ndarray:
    """log(close of the bar opening at `end` / open of the bar opening at `start`); NaN
    where either bar is missing."""
    if bars is None or bars.empty:
        return np.full(len(start), np.nan)
    o = bars["open"].reindex(start).to_numpy()
    c = bars["close"].reindex(end).to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.log(c / o)


def events(setl: pd.DataFrame, perp: pd.DataFrame, spot: Optional[pd.DataFrame], start: int,
           end: int) -> pd.DataFrame:
    """Every settlement from `start` to `end` (seconds, inclusive) with its windows:
    pre/post = the hour before and after it on perpetual bars; *_p the same around the
    placebo at +4h (NaN unless placebo_ok); spot_* on spot bars; *2 two-hour windows."""
    s = setl[(setl["ts"] >= start) & (setl["ts"] <= end)].reset_index(drop=True)
    t = s["ts"].to_numpy(dtype="int64")
    ok = s["placebo_ok"].to_numpy(dtype=bool)
    out = pd.DataFrame({"ts": t, "day": pd.to_datetime(t, unit="s", utc=True).strftime("%Y-%m-%d"),
                        "f_prev": s["prev"].to_numpy(), "f_now": s["rate"].to_numpy()})

    def placebo(x):
        return np.where(ok, x, np.nan)

    for name, bars in (("", perp), ("spot_", spot)):
        out[f"{name}pre"] = _bar(bars, t - HOUR, t - HOUR)
        out[f"{name}post"] = _bar(bars, t, t)
        out[f"{name}pre_p"] = placebo(_bar(bars, t + 3 * HOUR, t + 3 * HOUR))
        out[f"{name}post_p"] = placebo(_bar(bars, t + 4 * HOUR, t + 4 * HOUR))
    out["pre2"] = _bar(perp, t - 2 * HOUR, t - HOUR)
    out["post2"] = _bar(perp, t, t + HOUR)
    out["pre2_p"] = placebo(_bar(perp, t + 2 * HOUR, t + 3 * HOUR))
    out["post2_p"] = placebo(_bar(perp, t + 4 * HOUR, t + 5 * HOUR))
    return out


# --------------------------------------------------------------- statistics
def group(rate: pd.Series) -> pd.Series:
    a = rate.abs()
    return pd.Series(np.where(a >= HIGH, "high", np.where(a <= BASE, "base", "")), index=rate.index)


def excess(ev: pd.DataFrame, rate: str = "f_prev", pre: str = "pre", post: str = "post",
           pre_p: str = "pre_p", post_p: str = "post_p") -> pd.DataFrame:
    """The high events, each against the baseline coins of its own settlement hour:
    e_pre and e_post are the excess moves before and after it in the paying side's
    direction (d = sign of `rate`), e = e_post - e_pre, ep the same around the placebo
    with the same baseline coins, g = e - ep. NaN where fewer than 3 baseline coins
    have the bars."""
    ev = ev.assign(grp=group(ev[rate]), d=np.sign(ev[rate]))
    base = ev[ev["grp"] == "base"]
    b = base[np.isfinite(base[pre]) & np.isfinite(base[post])].groupby("ts").agg(
        n_b=(pre, "size"), b_pre=(pre, "mean"), b_post=(post, "mean"))
    bp = base[np.isfinite(base[pre_p]) & np.isfinite(base[post_p])].groupby("ts").agg(
        n_bp=(pre_p, "size"), bp_pre=(pre_p, "mean"), bp_post=(post_p, "mean"))
    hi = ev[ev["grp"] == "high"].join(b, on="ts").join(bp, on="ts")
    d = hi["d"]
    ok = hi["n_b"] >= MIN_BASELINE
    okp = hi["n_bp"] >= MIN_BASELINE
    hi["e_pre"] = (d * (hi[pre] - hi["b_pre"])).where(ok)
    hi["e_post"] = (d * (hi[post] - hi["b_post"])).where(ok)
    hi["e"] = hi["e_post"] - hi["e_pre"]
    hi["ep"] = (d * ((hi[post_p] - hi[pre_p]) - (hi["bp_post"] - hi["bp_pre"]))).where(okp)
    hi["g"] = hi["e"] - hi["ep"]
    return hi


def by_day(x: pd.Series, day: pd.Series) -> pd.Series:
    """Each UTC day's mean: one observation per day."""
    ok = np.isfinite(x)
    return x[ok].groupby(day[ok]).mean()


def leg(ev: pd.DataFrame, sign: int, col: str) -> pd.Series:
    """Per-day mean simple return of buying spot over `col`'s window, on settlements whose
    previous rate is at or beyond the high bar in direction `sign`."""
    sel = ev[ev["f_prev"] >= HIGH] if sign > 0 else ev[ev["f_prev"] <= -HIGH]
    return by_day(np.expm1(sel[col]), sel["day"])


def criteria(ev: pd.DataFrame) -> List[dict]:
    x = excess(ev)
    g = by_day(x["g"], x["day"])
    c1 = clustered(g)
    e_pre, e_post = clustered(by_day(x["e_pre"], x["day"])), clustered(by_day(x["e_post"], x["day"]))
    h1, h2 = clustered(g[g.index < SPLIT]), clustered(g[g.index >= SPLIT])
    legs = {"a: buy after the longs paid": clustered(leg(ev, 1, "spot_post")),
            "b: buy into the short cover": clustered(leg(ev, -1, "spot_pre"))}

    def bps(v):
        return f"{1e4 * v:+.1f} bps"

    return [
        {"criterion": "the settlement moves prices: mean g > 0, t >= 3",
         "actual": f"g {bps(c1['mean'])}, t {c1['t']:.2f}, {c1['n']} days",
         "met": c1["mean"] > 0 and c1["t"] >= T_HURDLE},
        {"criterion": "the predicted shape: excess pre < 0, excess post > 0",
         "actual": f"pre {bps(e_pre['mean'])} (t {e_pre['t']:.2f}), post {bps(e_post['mean'])} (t {e_post['t']:.2f})",
         "met": e_pre["mean"] < 0 and e_post["mean"] > 0},
        {"criterion": "not one era: g > 0 in both halves",
         "actual": f"{bps(h1['mean'])} ({h1['n']} days), {bps(h2['mean'])} ({h2['n']} days)",
         "met": h1["mean"] > 0 and h2["mean"] > 0},
        {"criterion": "a long-only spot leg earns > 18 bps with t > 2",
         "actual": "; ".join(f"{k} {bps(v['mean'])}, t {v['t']:.2f}, {v['n']} days" for k, v in legs.items()),
         "met": any(v["mean"] > LEG_HURDLE and v["t"] > LEG_T for v in legs.values())},
    ]
