"""Liquidations as a breakout filter (#18, research/PREREGISTRATION_LIQ.md).

A breakout made of liquidations is forced: the liquidated traders did not choose
to buy the high or sell the low, and are gone once liquidated. The test asks
whether such breaks fade relative to organic ones. These are its frozen pieces,
pure and without I/O (research/liq.py downloads):

* `bars_5m`: Binance's 1-minute futures bars combined into UTC 5-minute bars
* `liquidations`: Tardis rows in dollars; `buy` is a short liquidated, a forced buy
* `triggers` / `events`: #10's breakout trigger (`degen.features`, unchanged) and
  its mirror, one event per coin per direction per hour, with the forced share
  of the hour before the break and the return over the hour after it
* `tag`, `day_diff`, `leg`, `criteria`: the within-day grouping and the four
  pre-registered criteria, every day counted once
"""
from __future__ import annotations

import math
from typing import Dict, List

import numpy as np
import pandas as pd

from . import degen

BAR_S = 300
WINDOW_BARS = 12              # the hour before the break, ending at its close
SHORT_WINDOW_BARS = 3         # information: the 15 minutes before
HORIZONS = {"y15": 3, "y60": 12, "y240": 48}
HOLD_BARS = HORIZONS["y60"]   # also the gap before the same coin and direction counts again
DAY_FROM_S = 3600             # breaks closing from 01:00 UTC: the hour before is in the file's day
DAY_S = 86400
MIN_DAY_EVENTS = 6
T_HURDLE = -3.0
LEG_HURDLE = 0.0018           # two Hyperliquid taker round trips
LEG_T = 2.0
SPLIT = "2023-06-01"          # the second half of the 82 days starts here
VENUES = ("binance-futures", "bybit")
SYMBOLS = {"binance-futures": {"SHIB": "1000SHIBUSDT"}, "bybit": {"SHIB": "SHIB1000USDT"}}
FORCED_SIDE = {1: "buy", -1: "sell"}    # an up-break's forced flow is shorts bought back


def symbol(venue: str, coin: str) -> str:
    """The USDT perpetual's name on a venue (Binance's archive uses binance-futures')."""
    return SYMBOLS.get(venue, {}).get(coin, f"{coin}USDT")


# ------------------------------------------------------------------- inputs
def bars_5m(k1: pd.DataFrame) -> pd.DataFrame:
    """Binance 1-minute bars (archive columns) -> UTC 5-minute bars indexed by their
    open in unix seconds: first open, highest high, lowest low, last close, summed
    volumes. A bar is built from the minutes the archive has; with none, it does not
    exist. The archive's times are milliseconds; microseconds are recognised too."""
    k = k1.sort_values("open_time")
    t = k["open_time"].astype("int64")
    if len(t) and t.max() > 10**14:
        t = t // 1000
    ts = (t // 1000) // BAR_S * BAR_S
    g = k.groupby(ts.to_numpy())
    out = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
                        "close": g["close"].last(), "volume": g["volume"].sum(),
                        "quote_volume": g["quote_volume"].sum(),
                        "taker_buy_quote": g["taker_buy_quote_volume"].sum()}).astype(float)
    out.index.name = "ts"
    return out


def liquidations(rows: pd.DataFrame, venue: str) -> pd.DataFrame:
    """Tardis liquidation rows -> ts (unix seconds), side (`buy`: a short was
    liquidated; `sell`: a long), usd = price x amount, venue. `unknown` is dropped."""
    r = rows[rows["side"].isin(("buy", "sell"))]
    return pd.DataFrame({"ts": r["timestamp"].astype("int64").to_numpy() / 1e6,
                         "side": r["side"].to_numpy(),
                         "usd": r["price"].astype(float).to_numpy() * r["amount"].astype(float).to_numpy(),
                         "venue": venue})


# ------------------------------------------------------------------- events
def triggers(bars: pd.DataFrame) -> pd.DataFrame:
    """`degen.features` plus `up` (exactly `degen.is_candidate`) and `down`, its
    mirror: a close below the lowest low of the previous 48 bars on a volume z of
    2 or more, the last hour down, a positive ATR."""
    f = degen.features(bars)
    prior_low = f["low"].shift(1).rolling(degen.HIGH_WINDOW).min()
    ok = (f["vol_z"] >= degen.VOL_Z_MIN) & (f["atr"] > 0)
    f["up"] = f["breakout"] & ok & (f["burst"] > 0)
    f["down"] = (f["close"] < prior_low) & prior_low.notna() & ok & (f["burst"] < 0)
    return f


def _sum(liq: pd.DataFrame, start: float, end: float, side: str = None, venue: str = None) -> float:
    m = (liq["ts"] >= start) & (liq["ts"] < end)
    if side is not None:
        m &= liq["side"] == side
    if venue is not None:
        m &= liq["venue"] == venue
    return float(liq.loc[m, "usd"].sum())


def events(bars: pd.DataFrame, liq: pd.DataFrame, day_start: int) -> pd.DataFrame:
    """Every break on one coin-day with its measures. `bars` are 5-minute bars indexed
    by open time, `liq` the day's liquidations from any venues, `day_start` the
    test day's 00:00 UTC in seconds. A missing bar inside a window leaves that
    measure NaN; nothing is filled."""
    if liq is None or liq.empty:
        liq = pd.DataFrame({"ts": [], "side": [], "usd": [], "venue": []})
    f = triggers(bars)
    ts = f.index.to_numpy(dtype="int64")
    at = {int(t): i for i, t in enumerate(ts)}
    last: Dict[int, int] = {}
    rows: List[dict] = []
    for i in range(len(f)):
        for d, flag in ((1, bool(f["up"].iat[i])), (-1, bool(f["down"].iat[i]))):
            close_t = int(ts[i]) + BAR_S
            if not flag or not (day_start + DAY_FROM_S <= close_t <= day_start + DAY_S):
                continue
            if d in last and ts[i] - last[d] <= HOLD_BARS * BAR_S:
                continue                          # the same move, an hour not yet over
            last[d] = int(ts[i])
            rows.append(_measure(bars, liq, at, int(ts[i]), d))
    cols = ["ts", "direction", "forced", "forced_binance", "forced_bybit", "forced15", "liq_total",
            "volume", "volume15", "s", "s_binance", "s_bybit", "s15", "agree", *HORIZONS]
    return pd.DataFrame(rows, columns=cols)


def _window(bars: pd.DataFrame, at: Dict[int, int], t: int, n: int):
    """Sums of quote and taker-buy volume over the n bars ending with bar t; NaN when
    one is missing."""
    idx = [at.get(t - k * BAR_S) for k in range(n)]
    if any(i is None for i in idx):
        return float("nan"), float("nan")
    w = bars.iloc[idx]
    return float(w["quote_volume"].sum()), float(w["taker_buy_quote"].sum())


def _measure(bars: pd.DataFrame, liq: pd.DataFrame, at: Dict[int, int], t: int, d: int) -> dict:
    close_t = t + BAR_S
    start = t - (WINDOW_BARS - 1) * BAR_S
    start15 = t - (SHORT_WINDOW_BARS - 1) * BAR_S
    side = FORCED_SIDE[d]
    forced = _sum(liq, start, close_t, side)
    by_venue = {v: _sum(liq, start, close_t, side, v) for v in VENUES}
    forced15 = _sum(liq, start15, close_t, side)
    vol, taker = _window(bars, at, t, WINDOW_BARS)
    vol15, _ = _window(bars, at, t, SHORT_WINDOW_BARS)

    def share(x, v):
        return x / v if v and v > 0 else float("nan")

    out = {"ts": close_t, "direction": d, "forced": forced, "forced_binance": by_venue["binance-futures"],
           "forced_bybit": by_venue["bybit"], "forced15": forced15, "liq_total": _sum(liq, start, close_t),
           "volume": vol, "volume15": vol15, "s": share(forced, vol),
           "s_binance": share(by_venue["binance-futures"], vol), "s_bybit": share(by_venue["bybit"], vol),
           "s15": share(forced15, vol15),
           "agree": d * (2 * taker - vol) / vol if vol and vol > 0 else float("nan")}
    entry_i = at.get(t + BAR_S)
    entry = float(bars["open"].iat[entry_i]) if entry_i is not None else float("nan")
    for name, k in HORIZONS.items():
        exit_i = at.get(t + k * BAR_S)
        exit_px = float(bars["close"].iat[exit_i]) if exit_i is not None else float("nan")
        out[name] = d * (exit_px / entry - 1) if entry > 0 else float("nan")
    return out


# --------------------------------------------------------------- statistics
def usable(ev: pd.DataFrame, col: str = "s", y: str = "y60") -> pd.DataFrame:
    """Events with the measure and the outcome both present, on days with enough of them."""
    ev = ev[np.isfinite(ev[col]) & np.isfinite(ev[y])]
    return ev[ev.groupby("day")[col].transform("size") >= MIN_DAY_EVENTS]


def tag(ev: pd.DataFrame, col: str = "s", within_day: bool = True) -> pd.Series:
    """'forced' (percentile rank above 2/3), 'organic' (1/3 or below) or 'middle', ranked
    within each day (or over everything), ties sharing their average rank."""
    pct = ev.groupby("day")[col].rank(pct=True) if within_day else ev[col].rank(pct=True)
    return pd.Series(np.where(pct > 2 / 3, "forced", np.where(pct <= 1 / 3, "organic", "middle")),
                     index=ev.index)


def day_diff(ev: pd.DataFrame, col: str = "s", y: str = "y60", within_day: bool = True) -> pd.Series:
    """D(day): mean outcome of the day's forced events minus its organic ones'. A day
    without both groups has no D."""
    ev = usable(ev, col, y)
    g = ev.assign(tag=tag(ev, col, within_day)).groupby(["day", "tag"])[y].mean().unstack()
    if "forced" not in g or "organic" not in g:
        return pd.Series(dtype=float)
    return (g["forced"] - g["organic"]).dropna()


def leg(ev: pd.DataFrame, direction: int, group: str, y: str = "y60", col: str = "s") -> pd.Series:
    """Per-day mean long return of one leg: the day's events in `direction` and `group`
    (the same within-day grouping as D). Long = y on an up-break, -y on a down-break."""
    ev = usable(ev, col, y)
    ev = ev.assign(tag=tag(ev, col))
    sel = ev[(ev["direction"] == direction) & (ev["tag"] == group)]
    return (sel[y] * direction).groupby(sel["day"]).mean()


def clustered(x: pd.Series) -> dict:
    """Mean and t of per-day values, each day one observation."""
    x = pd.Series(x, dtype=float).dropna()
    n = int(x.size)
    m = float(x.mean()) if n else float("nan")
    sd = float(x.std(ddof=1)) if n > 1 else float("nan")
    t = m / (sd / math.sqrt(n)) if n > 1 and sd > 0 else float("nan")
    return {"mean": m, "t": t, "n": n}


def criteria(ev: pd.DataFrame) -> List[dict]:
    """The four pre-registered criteria, each with its actual value and whether it is met."""
    d = day_diff(ev)
    c1 = clustered(d)
    centred = ev.assign(s_coin=ev["s"] - ev.groupby("coin")["s"].transform("mean"))
    c2 = clustered(day_diff(centred, "s_coin"))
    h1, h2 = clustered(d[d.index < SPLIT]), clustered(d[d.index >= SPLIT])
    legs = {"a: buy forced down-breaks": clustered(leg(ev, -1, "forced")),
            "b: buy organic up-breaks": clustered(leg(ev, 1, "organic"))}
    leg_ok = {k: v["mean"] > LEG_HURDLE and v["t"] > LEG_T for k, v in legs.items()}
    return [
        {"criterion": "forced breaks fade relative to organic: mean D < 0, t <= -3",
         "actual": f"D {1e4 * c1['mean']:+.1f} bps, t {c1['t']:.2f}, {c1['n']} days",
         "met": c1["mean"] < 0 and c1["t"] <= T_HURDLE},
        {"criterion": "not the coin mix: D on coin-centred s < 0",
         "actual": f"D {1e4 * c2['mean']:+.1f} bps, t {c2['t']:.2f}, {c2['n']} days", "met": c2["mean"] < 0},
        {"criterion": "not one era: D < 0 in both halves",
         "actual": f"{1e4 * h1['mean']:+.1f} bps ({h1['n']} days), {1e4 * h2['mean']:+.1f} bps ({h2['n']} days)",
         "met": h1["mean"] < 0 and h2["mean"] < 0},
        {"criterion": "a long leg earns > 18 bps an hour with t > 2",
         "actual": "; ".join(f"{k} {1e4 * v['mean']:+.1f} bps, t {v['t']:.2f}, {v['n']} days"
                             for k, v in legs.items()),
         "met": any(leg_ok.values())},
    ]


def verdict(rows: List[dict]) -> str:
    met = [r["met"] for r in rows]
    if all(met):
        return "PASS"
    if all(met[:3]):
        return "real, not tradable after costs"
    return "FAIL"
