"""Does the funding-extreme factor survive out of sample?

Frozen before the holdout was looked at:
  signal : funding z-score (90-settlement causal window) < -2.0 on Hyperliquid perps
  entry  : next bar's open
  exit   : close of the bar `hold` days later
  costs  : 2 x 4 bps
  holdout: 2025-01-01 .. 2026-10-27  (train was 2023-05 .. 2024-12)
  assets : BTC (selection), ETH (never used for selection)

Run: python research/funding_edge.py [--db features.db]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # so `python research/...` works without installing

from espero import data, features  # noqa: E402
HOLDOUT = "2025-01-01"
TRAIN = "2023-05-12"
THRESHOLD = -2.0
FEE = 0.0004


def load(product: str, coin: str, db: Path) -> pd.DataFrame:
    key = f"hl_funding_{coin.lower()}"
    feats = features.load(db, key).rename(columns={"value": "funding"})
    if feats.empty:
        print(f"fetching {coin} funding ...")
        raw = features.hyperliquid_funding(pages=70, coin=coin)
        features.save(db, key, raw, "funding")
        feats = features.load(db, key).rename(columns={"value": "funding"})
    z = features.zscore(feats, "funding", window=90)[["ts", "funding_z"]].dropna()
    bars = data.load(ROOT / f"data/{product}USD_86400s.csv")
    merged = features.attach(bars, z, "funding_z", "funding_z", lag_seconds=3600)
    merged["dt"] = pd.to_datetime(merged["dt"], utc=True)
    return merged


def event_stats(df: pd.DataFrame, hold: int = 1) -> dict:
    df = df.reset_index(drop=True).copy()
    df["next_open"] = df["open"].shift(-1)
    rets, i = [], 0
    while i < len(df) - hold - 1:
        if (np.isfinite(df.funding_z.iloc[i]) and df.funding_z.iloc[i] < THRESHOLD
                and np.isfinite(df.next_open.iloc[i])):
            rets.append(df.close.iloc[i + hold] / df.next_open.iloc[i] - 1 - 2 * FEE)
            i += hold + 1
        else:
            i += 1
    r = np.array(rets)
    if not len(r):
        return {}
    eq = np.cumprod(1 + r)
    wins, losses = r[r > 0], r[r < 0]
    return {
        "n": len(r), "total": 100 * (eq[-1] - 1),
        "maxdd": 100 * (eq / np.maximum.accumulate(eq) - 1).min(),
        "avg": 100 * r.mean(), "win": 100 * (r > 0).mean(),
        "worst": 100 * r.min(), "t": r.mean() / (r.std() / np.sqrt(len(r))),
        "pf": abs(wins.sum() / losses.sum()) if losses.sum() else float("inf"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "features.db"))
    args = ap.parse_args()
    db = Path(args.db)

    for product, coin in (("BTC", "BTC"), ("ETH", "ETH")):
        m = load(product, coin, db)
        print(f"\n=== {product} ===")
        for name, start in (("train", TRAIN), ("holdout", HOLDOUT)):
            sub = m[m.dt >= start] if name == "holdout" else m[(m.dt >= TRAIN) & (m.dt < HOLDOUT)]
            for hold in (1, 3):
                s = event_stats(sub, hold)
                if s:
                    print(f"  {name:7s} hold={hold}d  n={s['n']:3d}  total={s['total']:+7.2f}%  "
                          f"maxdd={s['maxdd']:6.2f}%  avg={s['avg']:+.3f}%  win={s['win']:.0f}%  "
                          f"worst={s['worst']:+.2f}%  PF={s['pf']:.2f}  t={s['t']:.2f}")
        sub = m[m.dt >= HOLDOUT]
        bh = 100 * (sub.close.iloc[-1] / sub.close.iloc[0] - 1)
        print(f"  buy & hold over the holdout: {bh:+.2f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
