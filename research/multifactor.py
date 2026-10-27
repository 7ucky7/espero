"""Hypothesis #8 — multi-factor cross-sectional crypto, vol-targeted, turnover-buffered.

    python research/multifactor.py                # fetches the panel (or reuses data/panel)
    python research/multifactor.py --refresh      # re-download

The rule is frozen in research/PREREGISTRATION_MF.md. This script implements it
and prints the pre-registered metrics for the design and holdout windows, the
benchmarks, the information-only variants, and the factor IC table. It does
not decide; the verdict is written by hand into RESULTS_MF.md.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from espero import factor_eval as fe  # noqa: E402
from espero import factors, ops, panel  # noqa: E402
from espero import portfolio as pf  # noqa: E402

FACTORS = ["mom_30", "rev_3", "lowvol_30"]
TOP = 10
BUFFER = 2.0
TARGET_VOL = 0.20
MAX_SCALE = 2.0
COST = 0.0010
DESIGN = ("2021-10-01", "2024-06-30")
HOLDOUT = ("2024-07-01", "2026-10-27")
PANEL_DIR = ROOT / "data" / "panel"


def simulate(p: panel.MarketPanel, score: pd.DataFrame, mask: pd.DataFrame, start: str, end: str,
             cost: float = COST, vol_target: bool = True, buffer: float = BUFFER,
             top: int = TOP) -> tuple[pd.Series, int, float]:
    """Decide at Sunday's close, fill at Monday's open, mark at every close.

    Returns (equity curve indexed by date, rebalances, dollar turnover / equity summed).
    """
    vol = pf.realized_vol(p.close, 30)
    days = p.index[(p.index >= pd.Timestamp(start)) & (p.index <= pd.Timestamp(end))]
    coins = p.coins
    units = pd.Series(0.0, index=coins)
    cash, equity, n_reb, turn = 1.0, [], 0, 0.0
    pending: pd.Series | None = None

    for d in days:
        op, cl = p.open.loc[d], p.close.loc[d]
        # 1. fill the weights decided at the previous close, at today's open
        if pending is not None:
            px = op.where(op.notna(), cl)                 # a missing open falls back to the close
            value = cash + float((units * px).fillna(0).sum())
            target = pending * value
            cur = (units * px).fillna(0.0)
            tradable = px.notna()
            traded = float((target[tradable] - cur[tradable]).abs().sum())
            units[tradable] = (target[tradable] / px[tradable]).fillna(0.0)
            cash = value - float((units * px).fillna(0).sum()) - traded * cost
            turn += traded / value if value else 0.0
            n_reb += 1
            pending = None
        # 2. mark
        equity.append(cash + float((units * cl).fillna(0).sum()))
        # 3. decide at Sunday's close for Monday's open
        if d.weekday() == 6:
            s = score.loc[d].where(mask.loc[d])
            held = [c for c in coins if units[c] > 0]
            picks = pf.turnover_buffer(s, held, top, buffer) if buffer else \
                list(s.dropna().sort_values(ascending=False).index[:top])
            w = pf.equal_weight(picks, coins)
            if vol_target:
                w = pf.vol_scaled(w, vol.loc[d], TARGET_VOL, 1.0, MAX_SCALE)
            pending = w
    return pd.Series(equity, index=days), n_reb, turn


def metrics(eq: pd.Series) -> dict:
    r = eq.pct_change().dropna()
    years = len(eq) / 365.25
    return {
        "cagr": 100 * ((eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1),
        "sharpe": float(np.sqrt(365) * r.mean() / r.std()) if r.std() > 0 else 0.0,
        "maxdd": 100 * float((eq / eq.cummax() - 1).min()),
        "total": 100 * (eq.iloc[-1] / eq.iloc[0] - 1),
    }


def fmt(name: str, m: dict, extra: str = "") -> str:
    return (f"| {name} | {m['cagr']:+.2f}% | {m['sharpe']:.2f} | {m['maxdd']:.2f}% | "
            f"{m['total']:+.2f}% | {extra} |")


def benchmarks(p: panel.MarketPanel, mask: pd.DataFrame, start: str, end: str) -> dict:
    btc = p.close["BTC"].loc[start:end].dropna()
    ew_score = mask.astype(float).where(mask)         # every eligible coin scores 1
    ew, n, t = simulate(p, ew_score, mask, start, end, vol_target=False, buffer=0.0, top=10_000)
    return {"BTC": metrics(btc / btc.iloc[0]), "EW": (metrics(ew), n, t)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--span", default="5y")
    args = ap.parse_args()

    if PANEL_DIR.exists() and not args.refresh:
        p = panel.MarketPanel.load(PANEL_DIR)
        print(f"panel from {PANEL_DIR}: {len(p.coins)} coins, {len(p.index)} days")
    else:
        print("fetching panel ...")
        p = panel.build(span=args.span)
        p.save(PANEL_DIR)
        print(f"{len(p.coins)} coins, {len(p.index)} days; failed: {sorted(p.errors) or 'none'}")

    mask = panel.eligible(p, min_history=365, min_dollar_volume=1e6)
    score = factors.composite(p, FACTORS, mask)
    print(f"eligible on the last day: {int(mask.iloc[-1].sum())} / {len(p.coins)}")

    for label, (start, end) in (("design", DESIGN), ("holdout", HOLDOUT)):
        print(f"\n## {label} {start} → {end}\n")
        print("| book | CAGR | Sharpe | max DD | total | turnover/yr · rebalances |")
        print("|---|---|---|---|---|---|")
        eq, n, t = simulate(p, score, mask, start, end)
        yrs = len(eq) / 365.25
        print(fmt("**MF** (vol-targeted, buffered, 10 bps)", metrics(eq), f"{t / yrs:.1f}x · {n}"))
        eq30, n30, t30 = simulate(p, score, mask, start, end, cost=0.0030)
        print(fmt("MF at 30 bps", metrics(eq30), f"{t30 / yrs:.1f}x · {n30}"))
        eqp, np_, tp = simulate(p, score, mask, start, end, vol_target=False, buffer=0.0)
        print(fmt("MF plain (equal weight, no buffer)", metrics(eqp), f"{tp / yrs:.1f}x · {np_}"))
        b = benchmarks(p, mask, start, end)
        print(fmt("BTC buy & hold", b["BTC"]))
        ewm, ewn, ewt = b["EW"]
        print(fmt("Equal-weight eligible, weekly", ewm, f"{ewt / yrs:.1f}x · {ewn}"))
        if label == "holdout":
            m, bm = metrics(eq), b["BTC"]
            print("\n| criterion | required | actual | met |")
            print("|---|---|---|---|")
            print(f"| Sharpe > BTC | > {bm['sharpe']:.2f} | {m['sharpe']:.2f} | "
                  f"{'yes' if m['sharpe'] > bm['sharpe'] else '**no**'} |")
            print(f"| max DD shallower than BTC | > {bm['maxdd']:.2f}% | {m['maxdd']:.2f}% | "
                  f"{'yes' if m['maxdd'] > bm['maxdd'] else '**no**'} |")
            print(f"| CAGR > 0 | > 0 | {m['cagr']:+.2f}% | {'yes' if m['cagr'] > 0 else '**no**'} |")

    print("\n## factor IC table (full window, horizon 5d, purged 4-block walk-forward)\n")
    zoo = dict(factors.ZOO)
    zoo["composite"] = lambda q: factors.composite(q, FACTORS, mask)
    table = fe.evaluate(p, names=list(factors.ZOO) + ["composite"], horizon=5, mask=mask,
                        n_splits=4, embargo=5, factors=zoo)
    print("```")
    print(fe.format_table(table))
    print("```")
    t_comp = float(table.loc["composite", "t_oos"])
    print(f"\n| composite OOS IC t > 3 | > 3 | {t_comp:.2f} | {'yes' if t_comp > 3 else '**no**'} |")
    print("\nIC decay of the composite (mean IC by horizon):")
    print(fe.ic_decay(ops.where_valid(score, mask), p.close).round(4).to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
