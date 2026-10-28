"""Hypothesis #11 — perp funding carry, as pre-registered.

    python research/carry.py fetch     # universe, funding, perp and spot candles -> research/data/carry
    python research/carry.py run       # one replay, prints the table and the verdict

Rule and criteria: research/PREREGISTRATION_CARRY.md. Engine: espero/carry.py.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from espero import carry, data  # noqa: E402
from espero import hyperliquid as hl  # noqa: E402

DATA = ROOT / "research" / "data" / "carry"
TOP = 20
HL_START_MS = 1_683_000_000_000      # May 2023, when Hyperliquid funding history begins


def fetch() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    ctxs = hl.asset_contexts()
    spot_products = set(data.list_products(exclude=()))
    universe = []
    for coin in hl.top_by_open_interest(TOP, ctxs):
        product = f"{coin}-USD"
        if product in spot_products:
            universe.append(coin)
        else:
            print(f"{coin}: no Coinbase spot pair, dropped")
    (DATA / "universe.json").write_text(json.dumps(
        {"fetched": dt.datetime.now(dt.timezone.utc).isoformat(), "coins": universe,
         "contexts": [c for c in ctxs if c["coin"] in universe]}, indent=2))
    print(f"universe: {len(universe)} coins: {' '.join(universe)}")

    now = dt.datetime.now(dt.timezone.utc)
    for coin in universe:
        t0 = time.time()
        f = hl.funding_history(coin, HL_START_MS)
        f.to_csv(DATA / f"funding_{coin}.csv", index=False)
        if f.empty:
            print(f"{coin}: no funding history")
            continue
        start_ms = int(f["ts"].iloc[0]) * 1000
        p = hl.candles(coin, "1h", start_ms)
        p.to_csv(DATA / f"perp_{coin}.csv", index=False)
        days = (now - dt.datetime.fromtimestamp(start_ms // 1000, dt.timezone.utc)).days + 1
        s = data.fetch(f"{coin}-USD", days, 3600)
        s.to_csv(DATA / f"spot_{coin}.csv", index=False)
        print(f"{coin}: funding {len(f)}h  perp {len(p)}h  spot {len(s)}h  ({time.time() - t0:.0f}s)")


def load() -> dict:
    uni = json.loads((DATA / "universe.json").read_text())["coins"]
    coins = {}
    for coin in uni:
        try:
            cd = carry.from_frames(pd.read_csv(DATA / f"funding_{coin}.csv"),
                                   pd.read_csv(DATA / f"perp_{coin}.csv"),
                                   pd.read_csv(DATA / f"spot_{coin}.csv"))
        except FileNotFoundError:
            cd = None
        if cd is None:
            print(f"{coin}: excluded (history)")
            continue
        coins[coin] = cd
    return coins


def run() -> None:
    coins = load()
    m = carry.evaluate(coins, initial=1.0)
    res = m["result"]
    idx = res.equity.dropna().index
    print(f"\n{len(coins)} coins, {idx[0]:%Y-%m-%d} -> {idx[-1]:%Y-%m-%d}, {m['hours']} hours")
    print(f"trades {m['trades']}  hours in position {m['hours_in_position']}  "
          f"funding received {m['funding_received']:+.4f}  paid {m['funding_paid']:.4f}  "
          f"fees {m['fees']:.4f}  final equity {m['final']:.4f}")
    print(f"\n{'criterion':<42}{'required':>10}{'actual':>10}  met")
    actual = [m["ann_return"], m["max_dd"], m["sharpe"], m["paid_ratio"], m["ann_return_kraken"]]
    fmt = ["{:+.1%}", "{:.1%}", "{:.2f}", "{:.0%}", "{:+.1%}"]
    rows = carry.verdict(m)
    for r, a, f in zip(rows, actual, fmt):
        print(f"{r['criterion']:<42}{r['required']:>10}{f.format(a):>10}  {'yes' if r['met'] else 'NO'}")
    print(f"\nVerdict: {'PASS' if all(r['met'] for r in rows) else 'FAIL'}")

    if res.trades:
        t = pd.DataFrame(res.trades)
        print("\nper coin:")
        g = t.groupby("coin").agg(trades=("pnl", "size"), hours=("hours", "sum"),
                                  funding=("funding", "sum"), basis=("basis", "sum"),
                                  fees=("fees", "sum"), pnl=("pnl", "sum")).sort_values("pnl")
        print(g.to_string(float_format=lambda x: f"{x:+.4f}"))
        print("\nexit reasons:", t["reason"].value_counts().to_dict())
        print(f"funding / basis / fees over all trades: {t['funding'].sum():+.4f} / "
              f"{t['basis'].sum():+.4f} / {t['fees'].sum():.4f}")
    # yearly, for the write-up
    eq = res.equity.dropna()
    yearly = eq.groupby(eq.index.year).agg(["first", "last"])
    yearly["return"] = yearly["last"] / yearly["first"] - 1
    print("\nby year:\n" + yearly["return"].to_string(float_format=lambda x: f"{x:+.1%}"))


if __name__ == "__main__":
    {"fetch": fetch, "run": run}[sys.argv[1]]()
