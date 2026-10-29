"""Leveraged ETFs push crypto into the US close (#28, research/PREREGISTRATION_LEVETF.md).

The frozen rule and its four criteria, pure. A fund promising L times the daily
return must trade about A*L*(L-1)*r after a move r, in the direction of r, to its
4 p.m. ET valuation. So on NYSE days since the 2x crypto ETFs exist, BTC and ETH
should drift with the day's move in the last 15 minutes before 16:00 ET, and not
at the same clock on weekends and holidays. research/levetf.py loads the bars.
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Callable, Dict, List, Optional

import numpy as np
import pandas as pd

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python < 3.9
    from backports.zoneinfo import ZoneInfo  # type: ignore

from .liq import clustered

ET = ZoneInfo("America/New_York")
BAR_S = 300
FIRST, LAST = "2020-01-01", "2026-10-28"
ERAS = {"before": ("2020-01-01", "2023-06-26"), "ramp": ("2023-06-27", "2024-06-03"),
        "with": ("2024-06-04", "2026-10-28")}
PRIMARY = ("BTC", "ETH")
T_HURDLE = 3.0
DIFF_T = 2.0
BIG_R = 0.02
LEG_HURDLE = 0.0018
LEG_T = 2.0

# NYSE full closures and 13:00 early closes, 2019-12 -> 2026.
HOLIDAYS = {
    "2019-12-25",
    "2020-01-01", "2020-01-20", "2020-02-17", "2020-04-10", "2020-05-25", "2020-07-03", "2020-09-07",
    "2020-11-26", "2020-12-25",
    "2021-01-01", "2021-01-18", "2021-02-15", "2021-04-02", "2021-05-31", "2021-07-05", "2021-09-06",
    "2021-11-25", "2021-12-24",
    "2022-01-17", "2022-02-21", "2022-04-15", "2022-05-30", "2022-06-20", "2022-07-04", "2022-09-05",
    "2022-11-24", "2022-12-26",
    "2023-01-02", "2023-01-16", "2023-02-20", "2023-04-07", "2023-05-29", "2023-06-19", "2023-07-04",
    "2023-09-04", "2023-11-23", "2023-12-25",
    "2024-01-01", "2024-01-15", "2024-02-19", "2024-03-29", "2024-05-27", "2024-06-19", "2024-07-04",
    "2024-09-02", "2024-11-28", "2024-12-25",
    "2025-01-01", "2025-01-09", "2025-01-20", "2025-02-17", "2025-04-18", "2025-05-26", "2025-06-19",
    "2025-07-04", "2025-09-01", "2025-11-27", "2025-12-25",
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19", "2026-07-03",
    "2026-09-07", "2026-11-26", "2026-12-25",
}
EARLY = {
    "2019-12-24", "2020-11-27", "2020-12-24", "2021-11-26", "2022-11-25", "2023-07-03", "2023-11-24",
    "2024-07-03", "2024-11-29", "2024-12-24", "2025-07-03", "2025-11-28", "2025-12-24", "2026-11-27",
    "2026-12-24",
}


def kind(d: dt.date) -> str:
    """'trading' (a full NYSE session), 'early' (13:00 close) or 'closed'."""
    s = d.isoformat()
    if d.weekday() >= 5 or s in HOLIDAYS:
        return "closed"
    return "early" if s in EARLY else "trading"


def at(d: dt.date, hh: int, mm: int, tz=ET) -> int:
    """Unix seconds of hh:mm on date d in `tz` (Eastern by default, daylight saving included)."""
    return int(dt.datetime(d.year, d.month, d.day, hh, mm, tzinfo=tz).timestamp())


def session_close(d: dt.date) -> int:
    return at(d, 13, 0) if kind(d) == "early" else at(d, 16, 0)


def reference(d: dt.date) -> int:
    """R(d): the previous NYSE close on a trading day; 16:00 ET the day before on a closed day."""
    if kind(d) == "closed":
        return at(d - dt.timedelta(days=1), 16, 0)
    p = d - dt.timedelta(days=1)
    while kind(p) == "closed":
        p -= dt.timedelta(days=1)
    return session_close(p)


def calendar_mismatches(sessions, first: str = FIRST, last: str = LAST) -> List[str]:
    """Dates where the hard-coded calendar and real sessions (SPY's bars) disagree."""
    have = set(sessions)
    return [d.isoformat() for d in days(first, last) if (kind(d) != "closed") != (d.isoformat() in have)]


def era(day: str) -> Optional[str]:
    for name, (a, b) in ERAS.items():
        if a <= day <= b:
            return name
    return None


def days(first: str = FIRST, last: str = LAST) -> List[dt.date]:
    return [x.date() for x in pd.date_range(first, last, freq="D")]


class Prices:
    """P(t), the open of the 5-minute bar opening at t, and P-(t), the close of the bar ending at t."""

    def __init__(self, b: pd.DataFrame):
        self.o = b["open"].astype(float).to_dict()
        self.c = b["close"].astype(float).to_dict()

    def open(self, t: int) -> float:
        return self.o.get(int(t), math.nan)

    def before(self, t: int) -> float:
        return self.c.get(int(t) - BAR_S, math.nan)


def signed(px: Prices, ref: int, sig: int, end: int) -> Dict[str, float]:
    """r = P-(sig)/P(ref) - 1 and y = sign(r) * (P(end)/P(sig) - 1); NaN when a bar is missing or r = 0."""
    p0, ps, pe0, pe = px.open(ref), px.before(sig), px.open(sig), px.open(end)
    r = ps / p0 - 1
    if not np.isfinite(r) or r == 0 or not np.isfinite(pe / pe0):
        return {"r": r if np.isfinite(r) else math.nan, "y": math.nan}
    return {"r": r, "y": float(np.sign(r)) * (pe / pe0 - 1)}


WindowFn = Callable[[dt.date], Optional[tuple]]


def close_window(d: dt.date, sig=(15, 45), end=(16, 0)):
    """The primary: signal at 15:45 ET, exit 16:00 ET, from R(d). Early days are never targets."""
    if kind(d) == "early":
        return None
    return reference(d), at(d, *sig), at(d, *end)


def after_window(d: dt.date, minutes: int):
    """After the close: signed by r up to 16:00, from 16:00 to 16:00 + minutes."""
    if kind(d) == "early":
        return None
    t = at(d, 16, 0)
    return reference(d), t, t + 60 * minutes


def midday_window(d: dt.date):
    if kind(d) != "trading":
        return None
    return reference(d), at(d, 11, 45), at(d, 12, 0)


def utc_window(d: dt.date):
    """Crypto's own daily close: 23:45 -> 00:00 UTC, signed by r from the previous 00:00 UTC."""
    utc = dt.timezone.utc
    return at(d, 0, 0, utc), at(d, 23, 45, utc), at(d + dt.timedelta(days=1), 0, 0, utc)


WINDOWS: Dict[str, WindowFn] = {
    "y": close_window,
    "y30": lambda d: close_window(d, sig=(15, 30)),
    "y5": lambda d: close_window(d, sig=(15, 55)),
    "post15": lambda d: after_window(d, 15),
    "post60": lambda d: after_window(d, 60),
    "midday": midday_window,
    "utc": utc_window,
}


def rows(b: pd.DataFrame, coin: str, first: str = FIRST, last: str = LAST) -> pd.DataFrame:
    """One row per date: kind, era, and r/y for every window (`r` and `y` are the primary's)."""
    px = Prices(b)
    out = []
    for d in days(first, last):
        rec = {"date": d.isoformat(), "kind": kind(d), "era": era(d.isoformat()), "coin": coin}
        for name, fn in WINDOWS.items():
            w = fn(d)
            v = signed(px, *w) if w else {"r": math.nan, "y": math.nan}
            rec["r" if name == "y" else f"r_{name}"] = v["r"]
            rec[name] = v["y"]
        out.append(rec)
    return pd.DataFrame(out)


def per_date(df: pd.DataFrame, col: str = "y") -> pd.Series:
    """Each date's mean over coins: the observation."""
    return df.dropna(subset=[col]).groupby("date")[col].mean()


def welch(a: pd.Series, b: pd.Series) -> dict:
    a, b = pd.Series(a, dtype=float).dropna(), pd.Series(b, dtype=float).dropna()
    if len(a) < 2 or len(b) < 2:
        return {"diff": math.nan, "t": math.nan}
    d = float(a.mean() - b.mean())
    se = math.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))
    return {"diff": d, "t": d / se if se > 0 else math.nan}


def sample(df: pd.DataFrame, era_: str, kind_: str) -> pd.DataFrame:
    return df[(df["era"] == era_) & (df["kind"] == kind_)]


def criteria(df: pd.DataFrame, coins=PRIMARY) -> List[dict]:
    df = df[df["coin"].isin(coins)]
    w = per_date(sample(df, "with", "trading"))
    c1 = clustered(w)
    c2 = welch(w, per_date(sample(df, "with", "closed")))
    c3 = welch(w, per_date(sample(df, "before", "trading")))
    big = sample(df, "with", "trading")
    c4 = clustered(per_date(big[big["r"].abs() >= BIG_R]))
    bps = lambda x: f"{1e4 * x:+.1f} bps"  # noqa: E731
    return [
        {"criterion": "the push: with-era trading days, mean y > 0, t >= 3",
         "actual": f"{bps(c1['mean'])}, t {c1['t']:.2f}, {c1['n']} days",
         "met": c1["mean"] > 0 and c1["t"] >= T_HURDLE},
        {"criterion": "only when the ETFs trade: minus closed days > 0, t >= 2",
         "actual": f"{bps(c2['diff'])}, t {c2['t']:.2f}",
         "met": c2["diff"] > 0 and c2["t"] >= DIFF_T},
        {"criterion": "only since the ETFs exist: minus before-era trading days > 0",
         "actual": f"{bps(c3['diff'])}, t {c3['t']:.2f}",
         "met": c3["diff"] > 0},
        {"criterion": "it pays: |r| >= 2% days, mean y > 18 bps, t > 2",
         "actual": f"{bps(c4['mean'])}, t {c4['t']:.2f}, {c4['n']} days",
         "met": c4["mean"] > LEG_HURDLE and c4["t"] > LEG_T},
    ]


def verdict(crit: List[dict]) -> str:
    met = [c["met"] for c in crit]
    if all(met):
        return "PASS"
    if all(met[:3]):
        return "real, not tradable after costs"
    return "FAIL"
