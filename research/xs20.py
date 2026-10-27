"""Top-5-of-21 cross-sectional crypto momentum — exploratory evaluation.

    python research/xs20.py

The rule is frozen in research/PREREGISTRATION_XS20.md. This run is explicitly
*not* evidence (the window is contaminated); it exists to show the shape before
the forward paper trade starts.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from espero import data  # noqa: E402

COINS = ["BTC", "ETH", "LTC", "XRP", "BCH", "ADA", "LINK", "XLM", "ETC", "ZEC", "DASH",
         "EOS", "XTZ", "ATOM", "ALGO", "FIL", "AAVE", "MKR", "DOGE", "SOL", "AVAX"]
TOP = 5
LOOKBACK = 30
MIN_HISTORY = 365
COST = 0.0010
WINDOW = ("2023-01-01", "2026-10-27")


def load() -> pd.DataFrame:
    frames = {}
    for c in COINS:
        try:
            df = data.yahoo_daily(f"{c}-USD", "5y")
        except Exception:
            continue
        df["dt"] = pd.to_datetime(df["dt"], utc=True).dt.tz_localize(None)
        frames[c] = df.set_index("dt").sort_index()[["open", "close"]]
    return frames


def month_starts(cal: pd.DatetimeIndex) -> list[pd.Timestamp]:
    s = pd.Series(cal, index=cal)
    return list(s.groupby([cal.year, cal.month]).first().values)


def run(frames: dict, start: str, end: str, cost: float = COST):
    cal = pd.DatetimeIndex(sorted(set().union(*[set(f.index) for f in frames.values()])))
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    days = cal[(cal >= start) & (cal <= end)]
    firsts = [d for d in month_starts(cal) if d >= start]

    units, cash, equity, trades = {c: 0.0 for c in frames}, 1.0, [], 0
    for d in days:
        if d in firsts:
            prev = cal[cal < d]
            if len(prev) >= LOOKBACK + 1:
                hist = {c: f.loc[:prev[-1], "close"] for c, f in frames.items()}
                ret = {}
                for c, s in hist.items():
                    if len(s) > LOOKBACK and len(s) >= MIN_HISTORY:
                        ret[c] = s.iloc[-1] / s.iloc[-LOOKBACK] - 1
                if len(ret) >= TOP:
                    picks = sorted(ret, key=ret.get, reverse=True)[:TOP]
                    port = cash + sum(units[c] * frames[c]["open"].asof(d) for c in frames)
                    target = {c: (port / TOP if c in picks else 0.0) for c in frames}
                    traded = 0.0
                    for c in frames:
                        px = frames[c]["open"].asof(d)
                        if not np.isfinite(px):
                            continue
                        cur = units[c] * px
                        traded += abs(target[c] - cur)
                        units[c] = target[c] / px
                    cash = port - sum(units[c] * frames[c]["open"].asof(d) for c in frames)
                    cash -= traded * cost
                    trades += 1
        px = sum(units[c] * frames[c]["close"].asof(d) for c in frames)
        equity.append(cash + px)

    return pd.Series(equity, index=days), trades


def metrics(eq: pd.Series):
    r = eq.pct_change().dropna()
    years = len(eq) / 365.25
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1
    dd = (eq / eq.cummax() - 1).min()
    return cagr * 100, (np.sqrt(365) * r.mean() / r.std() if r.std() else 0), dd * 100


def main() -> int:
    frames = load()
    print(f"universe: {len(frames)} coins")
    eq, n = run(frames, *WINDOW)
    c, s, d = metrics(eq)
    print(f"XS20  {WINDOW[0]}..{WINDOW[1]}  rebalances={n}  cagr={c:+.2f}%  sharpe={s:.2f}  maxdd={d:.2f}%")

    b = data.yahoo_daily("BTC-USD", "5y")
    b["dt"] = pd.to_datetime(b["dt"], utc=True).dt.tz_localize(None)
    btc = b.set_index("dt")["close"]
    b = btc.loc[pd.Timestamp(WINDOW[0]):pd.Timestamp(WINDOW[1])]
    bc, bs, bd = metrics(b / b.iloc[0])
    print(f"BTC   {WINDOW[0]}..{WINDOW[1]}                    cagr={bc:+.2f}%  sharpe={bs:.2f}  maxdd={bd:.2f}%")

    # equal-weight universe benchmark
    join = pd.DataFrame({c: f["close"] for c, f in frames.items()}).sort_index()
    join = join.loc[pd.Timestamp(WINDOW[0]):pd.Timestamp(WINDOW[1])].ffill()
    ew = (join / join.iloc[0]).mean(axis=1)
    ec, es, ed = metrics(ew)
    print(f"EQW   {WINDOW[0]}..{WINDOW[1]}                    cagr={ec:+.2f}%  sharpe={es:.2f}  maxdd={ed:.2f}%")

    # cost sensitivity
    for c_bps in (30,):
        eq2, _ = run(frames, *WINDOW, cost=c_bps / 1e4)
        c2, s2, d2 = metrics(eq2)
        print(f"XS20 @ {c_bps}bps  cagr={c2:+.2f}%  sharpe={s2:.2f}  maxdd={d2:.2f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
