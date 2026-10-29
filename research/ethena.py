"""Hypothesis #36 — Ethena's USDe flows forecast funding.

    python research/ethena.py        # fetches USDe's history (saved) and Hyperliquid funding

Frozen in research/PREREGISTRATION_ETHENA.md; the verdict is written by hand into RESULTS_ETHENA.md.
"""
from __future__ import annotations

import gzip
import json
import sys
import urllib.request
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from espero import ethena as et  # noqa: E402
from espero import fillcost as fc  # noqa: E402
from espero import hyperliquid as hl  # noqa: E402

USDE = ROOT / "research" / "ethena_usde.json.gz"
URL = "https://stablecoins.llama.fi/stablecoin/146"


def usde() -> list:
    if not USDE.exists():
        raw = urllib.request.urlopen(urllib.request.Request(URL, headers={"User-Agent": "espero"}), timeout=60).read()
        USDE.write_bytes(gzip.compress(raw, mtime=0))
    return json.loads(gzip.decompress(USDE.read_bytes()))["tokens"]


def binance(sym: str) -> pd.Series:
    s = fc.settlements(json.loads((ROOT / "data" / "settle" / "funding" / f"{sym}.json").read_text()))
    return et.weekly_funding(s["ts"], s["rate8"] * 1095)


def hyper(coin: str) -> pd.Series:
    start = int(pd.Timestamp("2024-02-01", tz="UTC").timestamp() * 1000)
    end = int(pd.Timestamp("2026-10-27", tz="UTC").timestamp() * 1000)
    df = hl.funding_history(coin, start, end)
    return et.weekly_funding(df["ts"], df["funding"] * 8760)


def main() -> int:
    flow = et.weekly_supply(usde()).pct_change()
    bn = {c: binance(f"{c}USDT") for c in ("BTC", "ETH")}
    hy = {c: hyper(c) for c in ("BTC", "ETH")}
    b_avg = (bn["BTC"] + bn["ETH"]) / 2
    h_avg = (hy["BTC"] + hy["ETH"]) / 2
    d = et.design(flow, b_avg)
    print(f"weeks {d.index.min().date()} -> {d.index.max().date()}: {len(d)}; "
          f"weekly USDe flow sd {100 * d['flow'].std():.1f}%, Binance funding mean {100 * d['F'].mean():.1f}% a year")
    crit = et.criteria(flow, b_avg, h_avg)
    print("\n## criteria\n")
    print("| # | criterion | actual | met |")
    print("|---|---|---|---|")
    for i, r in enumerate(crit, 1):
        print(f"| {i} | {r['criterion']} | {r['actual']} | {'yes' if r['met'] else '**no**'} |")
    print(f"\nverdict: {et.verdict(crit)}")
    print("\n## information only\n")
    rows = [("no controls", et.fit(et.design(flow, b_avg, controls=False))),
            ("BTC alone", et.fit(et.design(flow, bn["BTC"]))), ("ETH alone", et.fit(et.design(flow, bn["ETH"]))),
            ("2-week horizon", et.fit(et.design(flow, b_avg, horizon=2)))]
    for name, r in rows:
        print(f"{name:16s} b {r['b']:+.3f}  t {r['t']:.2f}  ({r['n']} weeks)")
    full = et.fit(d)
    print(f"\nsize: a one-sd weekly flow ({100 * d['flow'].std():.1f}%) moves next week's funding by "
          f"{100 * full['b'] * d['flow'].std():+.2f} percentage points a year")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
