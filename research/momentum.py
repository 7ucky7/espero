"""Cross-sectional momentum — implemented exactly as research/PREREGISTRATION.md says.

Run once. The rule is not adjusted afterwards; a failure means the hypothesis is dead.

    python research/momentum.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from espero import data  # noqa: E402

COINS = ["BTC", "ETH", "SOL", "LINK", "ADA", "XRP", "DOGE", "LTC", "AVAX"]
DATA = ROOT / "research" / "data"
COST_PER_LEG = 0.0005      # 5 bps a side -> 10 bps round trip
LOOKBACK = 30              # calendar days
MIN_HISTORY = 365          # daily closes required for eligibility
DESIGN = ("2020-01-01", "2023-12-31")
HOLDOUT = ("2024-01-01", "2026-10-27")


def load() -> dict[str, pd.DataFrame]:
    out = {}
    for c in COINS:
        df = data.load(DATA / f"{c}USD.csv")
        df = df.set_index("dt")[["open", "close"]].sort_index()
        out[c] = df
    return out


def build(panel: dict[str, pd.DataFrame]) -> tuple[pd.DatetimeIndex, dict, dict]:
    idx = sorted(set().union(*[set(df.index) for df in panel.values()]))
    idx = pd.DatetimeIndex(idx)
    opens = pd.DataFrame({c: panel[c]["open"].reindex(idx).ffill() for c in COINS})
    closes = pd.DataFrame({c: panel[c]["close"].reindex(idx).ffill() for c in COINS})
    return idx, opens, closes


def simulate(idx, opens, closes, start, end) -> tuple[pd.Series, list]:
    start, end = pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC")
    days = idx[(idx >= start) & (idx <= end)]
    mondays = {d for d in days if d.dayofweek == 0}

    coin, units, cash = None, 0.0, 1.0
    equity, trades = [], []

    for d in days:
        if d in mondays:
            pos = idx.get_loc(d)
            if pos >= LOOKBACK:
                history = closes.iloc[: pos]           # strictly before today
                # Kept as run (research/ERRATA.md, 2026-10-28): iloc[-LOOKBACK] is LOOKBACK - 1 bars
                # back, one short of the pre-registered window. Changing it would change a published result.
                ret30 = history.iloc[-1] / history.iloc[max(0, len(history) - LOOKBACK)] - 1
                counts = history.notna().sum()
                eligible = counts[counts >= MIN_HISTORY]
                ret30 = ret30[eligible.index]
                target = ret30.idxmax() if len(ret30) and ret30.max() > 0 else None
            else:
                target = None

            if target != coin:
                price_today = opens.loc[d]
                if coin is not None:
                    px = price_today[coin]
                    if np.isfinite(px):
                        cash = units * px
                        cash *= 1 - COST_PER_LEG
                        units = 0.0
                if target is not None:
                    px = price_today[target]
                    if np.isfinite(px) and cash > 0:
                        units = cash * (1 - COST_PER_LEG) / px
                        cash = 0.0
                        coin = target
                    else:
                        coin = None
                else:
                    coin = None
                mark = float(cash + units * opens.loc[d][coin]) if coin else float(cash)
                trades.append((d.date().isoformat(), target, mark))

        px = closes.loc[d][coin] if coin else np.nan
        eq = cash + units * px if coin and np.isfinite(px) else cash
        equity.append(eq)

    return pd.Series(equity, index=days), trades


def metrics(eq: pd.Series) -> dict:
    r = eq.pct_change().dropna()
    years = len(eq) / 365.25
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1 if years > 0 else 0
    dd = (eq / eq.cummax() - 1).min()
    sharpe = np.sqrt(365) * r.mean() / r.std() if r.std() > 0 else 0
    return {"cagr": 100 * cagr, "sharpe": sharpe, "maxdd": 100 * dd,
            "calmar": (100 * cagr) / abs(100 * dd) if dd else float("inf"),
            "total": 100 * (eq.iloc[-1] / eq.iloc[0] - 1)}


def benchmark(idx, closes, start, end) -> dict:
    s = closes["BTC"][(closes.index >= pd.Timestamp(start, tz="UTC")) & (closes.index <= pd.Timestamp(end, tz="UTC"))]
    eq = (1 - COST_PER_LEG) * s / s.iloc[0]
    return metrics(eq)


def main() -> int:
    panel = load()
    idx, opens, closes = build(panel)
    print(f"panel: {len(COINS)} coins, {len(idx)} days  {idx[0].date()} .. {idx[-1].date()}\n")

    results = {}
    for label, (start, end) in (("design", DESIGN), ("holdout", HOLDOUT), ("full", ("2020-01-01", end_of := "2026-10-27"))):
        eq, trades = simulate(idx, opens, closes, start, end)
        m = metrics(eq)
        m["switches"] = len(trades)
        m["switches_per_year"] = len(trades) / max(len(eq) / 365.25, 1e-9)
        m["in_market"] = 100 * (eq.pct_change().fillna(0) != 0).mean()
        b = benchmark(idx, closes, start, end)
        results[label] = (m, b)
        print(f"{label:8s} {start} .. {end}")
        print(f"  strategy cagr={m['cagr']:+7.2f}%  sharpe={m['sharpe']:5.2f}  maxdd={m['maxdd']:7.2f}%  "
              f"total={m['total']:+8.2f}%  switches={m['switches']:3d} ({m['switches_per_year']:.1f}/yr)")
        print(f"  BTC B&H  cagr={b['cagr']:+7.2f}%  sharpe={b['sharpe']:5.2f}  maxdd={b['maxdd']:7.2f}%  "
              f"total={b['total']:+8.2f}%\n")

    m, b = results["holdout"]
    passed = (m["sharpe"] > b["sharpe"]) and (m["maxdd"] > b["maxdd"]) and (m["cagr"] > 0)
    print("PASS criteria on holdout: sharpe>BTC, maxdd shallower than BTC, cagr>0")
    print(f"  sharpe {m['sharpe']:.2f} vs {b['sharpe']:.2f} -> {'yes' if m['sharpe'] > b['sharpe'] else 'NO'}")
    print(f"  maxdd {m['maxdd']:.2f}% vs {b['maxdd']:.2f}% -> {'yes' if m['maxdd'] > b['maxdd'] else 'NO'}")
    print(f"  cagr {m['cagr']:+.2f}% -> {'yes' if m['cagr'] > 0 else 'NO'}")
    print(f"\nVERDICT: {'PASS' if passed else 'FAIL'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
