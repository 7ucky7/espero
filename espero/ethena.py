"""Ethena's USDe flows forecast funding (#36, research/PREREGISTRATION_ETHENA.md).

Pure: weekly USDe supply and funding, and a least-squares regression of next week's
change in funding on this week's supply flow, controlling for funding's level and last
change, with Newey-West standard errors. research/ethena.py fetches and prints.
"""
from __future__ import annotations

from typing import Dict, List

import numpy as np
import pandas as pd

FIRST_WEEK, LAST_WEEK = "2024-03-04", "2026-10-19"     # week starts; the last ends 2026-10-26
LAGS = 4


def week_of(ts) -> pd.DatetimeIndex:
    """The Monday 00:00 UTC that starts each timestamp's week."""
    t = pd.to_datetime(pd.Series(ts), unit="s", utc=True).dt.tz_localize(None)     # naive UTC
    return pd.DatetimeIndex(t.dt.normalize() - pd.to_timedelta(t.dt.weekday, unit="D"))


def weekly_supply(tokens: List[dict]) -> pd.Series:
    """DefiLlama's daily rows -> the last supply of each week."""
    ts = [int(r["date"]) for r in tokens]
    v = [float((r.get("circulating") or {}).get("peggedUSD") or np.nan) for r in tokens]
    s = pd.Series(v, index=week_of(ts)).dropna()
    return s.groupby(level=0).last()


def weekly_funding(ts, annual) -> pd.Series:
    """Funding (already annualized) -> each week's mean."""
    s = pd.Series(np.asarray(annual, dtype=float), index=week_of(ts))
    return s.groupby(level=0).mean()


def ols_nw(y: np.ndarray, x: np.ndarray, lags: int = LAGS) -> Dict[str, np.ndarray]:
    """Least squares with an intercept added, and Newey-West (Bartlett) standard errors."""
    X = np.column_stack([np.ones(len(y)), x])
    xtx_inv = np.linalg.inv(X.T @ X)
    beta = xtx_inv @ X.T @ y
    u = y - X @ beta
    xu = X * u[:, None]
    s = xu.T @ xu
    for k in range(1, lags + 1):
        w = 1 - k / (lags + 1)
        g = xu[k:].T @ xu[:-k]
        s += w * (g + g.T)
    cov = xtx_inv @ s @ xtx_inv
    se = np.sqrt(np.diag(cov))
    return {"beta": beta, "se": se, "t": beta / se, "n": len(y)}


def design(flow: pd.Series, f: pd.Series, horizon: int = 1, controls: bool = True) -> pd.DataFrame:
    """y = F(t+h) - F(t) against flow(t), F(t) and dF(t), on weeks with all of them."""
    df = pd.DataFrame({"flow": flow, "F": f}).sort_index()
    df["dF"] = df["F"].diff()
    df["y"] = df["F"].shift(-horizon) - df["F"]
    df = df.loc[FIRST_WEEK:LAST_WEEK]
    cols = ["y", "flow", "F", "dF"] if controls else ["y", "flow"]
    return df[cols].dropna()


def fit(d: pd.DataFrame) -> dict:
    """b (the flow's coefficient) and its t."""
    x = d.drop(columns="y").to_numpy(dtype=float)
    r = ols_nw(d["y"].to_numpy(dtype=float), x)
    return {"b": float(r["beta"][1]), "t": float(r["t"][1]), "n": int(r["n"])}


def criteria(flow: pd.Series, binance: pd.Series, hyperliquid: pd.Series) -> List[dict]:
    d = design(flow, binance)
    full = fit(d)
    mid = len(d) // 2
    h1, h2 = fit(d.iloc[:mid]), fit(d.iloc[mid:])
    hl = fit(design(flow, hyperliquid))
    return [
        {"criterion": "Binance: next week's funding change on this week's USDe flow, b < 0, t <= -2",
         "actual": f"b {full['b']:+.3f}, t {full['t']:.2f}, {full['n']} weeks", "met": full["b"] < 0 and full["t"] <= -2},
        {"criterion": "not one stretch: b < 0 in each half",
         "actual": f"b {h1['b']:+.3f} (t {h1['t']:.2f}), {h2['b']:+.3f} (t {h2['t']:.2f})",
         "met": h1["b"] < 0 and h2["b"] < 0},
        {"criterion": "a second venue: b < 0 on Hyperliquid",
         "actual": f"b {hl['b']:+.3f}, t {hl['t']:.2f}, {hl['n']} weeks", "met": hl["b"] < 0},
    ]


def verdict(rows: List[dict]) -> str:
    return "PASS" if all(r["met"] for r in rows) else "FAIL"
