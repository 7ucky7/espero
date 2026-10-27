"""Cross-asset time-series momentum, implemented exactly as pre-registered.

    python research/tsmom.py

Rule (frozen in research/PREREGISTRATION_TSMOM.md): at each month-end close,
hold equal weight in every eligible asset whose 252-day return is positive,
capped at 1/6 each, remainder in cash. Execute at the next month's first open.
10 bps per side.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "research" / "data"
ASSETS = ["SPY", "TLT", "GLD", "USO", "BTC", "ETH"]
COST = 0.0010
LOOKBACK = 252
MAX_WEIGHT = 1 / 6
DESIGN = ("2010-01-01", "2020-12-31")
HOLDOUT = ("2021-01-01", "2026-10-27")


def load() -> dict[str, pd.DataFrame]:
    out = {}
    for a in ASSETS:
        df = pd.read_csv(DATA / f"{a}.csv", parse_dates=["dt"])
        df["dt"] = pd.to_datetime(df["dt"], utc=True).dt.tz_convert(None)
        out[a] = df.set_index("dt")[["open", "close"]].sort_index()
    return out


def panel(assets: dict[str, pd.DataFrame]):
    cal = assets["SPY"].index                      # ETF trading calendar
    closes = pd.DataFrame({a: assets[a]["close"].reindex(cal).ffill() for a in ASSETS})
    opens = pd.DataFrame({a: assets[a]["open"].reindex(cal).ffill() for a in ASSETS})
    return cal, opens, closes


def month_starts(cal: pd.DatetimeIndex) -> list[pd.Timestamp]:
    s = pd.Series(cal, index=cal)
    firsts = s.groupby([cal.year, cal.month]).first()
    return list(firsts.values)


def simulate(cal, opens, closes, start, end, use_signal: bool = True,
             only: tuple[str, ...] | None = None):
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    days = cal[(cal >= start) & (cal <= end)]
    firsts = [d for d in month_starts(cal) if d >= start]

    units = {a: 0.0 for a in ASSETS}
    cash = 1.0
    equity, weights_used, traded = [], [], []

    for i, d in enumerate(days):
        if d in firsts:
            prev = cal[cal < d]
            if len(prev) >= LOOKBACK + 1:
                decision = prev[-1]
                hist = closes.loc[:decision]
                ret = hist.iloc[-1] / hist.iloc[-LOOKBACK] - 1
                available = hist.notna().sum()
                eligible = [a for a in ASSETS if available[a] >= LOOKBACK]
                if only:
                    eligible = [a for a in eligible if a in only]
                if use_signal:
                    picks = [a for a in eligible if ret[a] > 0]
                else:
                    picks = eligible
                w = min(1.0 / len(picks), MAX_WEIGHT) if picks else 0.0

                port = cash + sum(units[a] * opens.loc[d][a] for a in ASSETS
                                  if np.isfinite(opens.loc[d][a]))
                target_value = {a: (port * w if a in picks else 0.0) for a in ASSETS}
                traded_notional = 0.0
                for a in ASSETS:
                    px = opens.loc[d][a]
                    if not np.isfinite(px):
                        continue
                    current = units[a] * px
                    delta = target_value[a] - current
                    if abs(delta) < 1e-9:
                        continue
                    traded_notional += abs(delta)
                    units[a] = target_value[a] / px
                cash = port - sum(units[a] * opens.loc[d][a] for a in ASSETS
                                  if np.isfinite(opens.loc[d][a]))
                cash -= traded_notional * COST
                weights_used.append((d.date().isoformat(), len(picks), round(w, 3)))
                traded.append((d.date().isoformat(), round(traded_notional, 4)))

        px = closes.loc[d]
        equity.append(cash + sum(units[a] * px[a] for a in ASSETS if np.isfinite(px[a])))

    return pd.Series(equity, index=days), weights_used, traded


def metrics(eq: pd.Series) -> dict:
    r = eq.pct_change().dropna()
    years = len(eq) / 252
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1
    dd = (eq / eq.cummax() - 1).min()
    return {"cagr": 100 * cagr, "sharpe": float(np.sqrt(252) * r.mean() / r.std()) if r.std() else 0,
            "maxdd": 100 * dd, "calmar": (100 * cagr) / abs(100 * dd) if dd else float("inf"),
            "total": 100 * (eq.iloc[-1] / eq.iloc[0] - 1)}


def main() -> int:
    assets = load()
    cal, opens, closes = panel(assets)

    print(f"{'period':10s} {'strategy':34s} {'cagr':>8s} {'sharpe':>7s} {'maxdd':>8s} {'total':>9s}")
    results = {}
    for label, (start, end) in (("design", DESIGN), ("holdout", HOLDOUT), ("full", ("2010-01-01", "2026-10-27"))):
        eq, _, _ = simulate(cal, opens, closes, start, end, use_signal=True)
        bm, _, _ = simulate(cal, opens, closes, start, end, use_signal=False)
        ms, mb = metrics(eq), metrics(bm)
        results[label] = (ms, mb, eq)
        print(f"{label:10s} {'TSMOM':34s} {ms['cagr']:+8.2f} {ms['sharpe']:7.2f} {ms['maxdd']:8.2f} {ms['total']:+9.2f}")
        print(f"{'':10s} {'equal-weight benchmark':34s} {mb['cagr']:+8.2f} {mb['sharpe']:7.2f} {mb['maxdd']:8.2f} {mb['total']:+9.2f}")

    ms, mb, _ = results["holdout"]
    passed = ms["sharpe"] > mb["sharpe"] and ms["maxdd"] > mb["maxdd"] and ms["cagr"] > 0
    print("\nPASS criteria on holdout (sharpe>benchmark, drawdown shallower, cagr>0):")
    print(f"  sharpe  {ms['sharpe']:.2f} vs {mb['sharpe']:.2f} -> {'yes' if ms['sharpe'] > mb['sharpe'] else 'NO'}")
    print(f"  maxdd   {ms['maxdd']:.2f}% vs {mb['maxdd']:.2f}% -> {'yes' if ms['maxdd'] > mb['maxdd'] else 'NO'}")
    print(f"  cagr    {ms['cagr']:+.2f}% -> {'yes' if ms['cagr'] > 0 else 'NO'}")
    print(f"\nVERDICT: {'PASS' if passed else 'FAIL'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
