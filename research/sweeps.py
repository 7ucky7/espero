"""Hypothesis #35 — stop runs at yesterday's low reverse.

    python research/sweeps.py        # cached bars only; downloads nothing

Frozen in research/PREREGISTRATION_SWEEPS.md; the verdict is written by hand into RESULTS_SWEEPS.md.
"""
from __future__ import annotations

import gzip
import io
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research"))
from levpush import bars  # noqa: E402  (the cached-bar reader)

from espero import liq as lq  # noqa: E402
from espero import sweeps as sw  # noqa: E402
from espero.liq import clustered  # noqa: E402
from espero.xs import UNIVERSE  # noqa: E402

EVENTS = ROOT / "research" / "sweeps_events.csv.gz"
ROUND = {"BTC": 1000.0, "ETH": 100.0}
COST = 0.0013                      # one Hyperliquid taker round trip with slippage


def bps(x: float) -> str:
    return f"{1e4 * x:+.1f} bps"


def line(name: str, ev: pd.DataFrame, col: str = "r60") -> str:
    c = clustered(sw.by_day(ev, col))
    return f"| {name} | {bps(c['mean'])} | {c['t']:.2f} | {c['n']} | {int(ev[col].notna().sum())} |"


def main() -> int:
    low, high, rnd = [], [], []
    for c in UNIVERSE:
        try:
            b = bars(c)
        except ValueError:
            print(f"{c}: no bars", flush=True)
            continue
        ev = sw.events(b)
        down = lq.triggers(b)
        dts = np.asarray(down.index[down["down"].to_numpy(dtype=bool)], dtype="int64") + sw.BAR_S
        ev["with_20"] = [bool(((dts > t - 3600) & (dts <= t)).any()) for t in ev["ts"]]
        low.append(ev.assign(coin=c))
        high.append(sw.events(b, side="high").assign(coin=c))
        if c in ROUND:
            rnd.append(sw.events(b, step=ROUND[c]).assign(coin=c))
        print(f"{c}: {len(ev)} low sweeps", flush=True)
    ev = pd.concat(low, ignore_index=True)
    buf = io.StringIO()
    ev.to_csv(buf, index=False, float_format="%.6g")
    EVENTS.write_bytes(gzip.compress(buf.getvalue().encode(), mtime=0))
    rec, fail = ev[ev["kind"] == "reclaimed"], ev[ev["kind"] == "failed"]
    print(f"\nsweeps of yesterday's low: {len(ev)} ({len(rec)} reclaimed, {len(fail)} failed) on "
          f"{ev['day'].nunique()} days -> {EVENTS.relative_to(ROOT)}")

    crit = sw.criteria(ev)
    print("\n## criteria (each UTC day's mean one observation)\n")
    print("| # | criterion | actual | met |")
    print("|---|---|---|---|")
    for i, r in enumerate(crit, 1):
        print(f"| {i} | {r['criterion']} | {r['actual']} | {'yes' if r['met'] else '**no**'} |")
    print(f"\nverdict: {sw.verdict(crit)}")

    print("\n## information only\n")
    print("| set | mean | t | days | events |")
    print("|---|---|---|---|---|")
    print(line("reclaimed, 4 hours", rec, "r240"))
    print(line("failed, 1 hour", fail))
    print(line("failed, 4 hours", fail, "r240"))
    print(line("reclaimed, not near a #20 trigger", rec[~rec["with_20"]]))
    print(line("reclaimed, with a #20 trigger in the hour", rec[rec["with_20"]]))
    hi = pd.concat(high, ignore_index=True)
    print(line("short side (yesterday's high), reclaimed, paper short", hi[hi["kind"] == "reclaimed"]))
    print(line("short side, failed", hi[hi["kind"] == "failed"]))
    r = pd.concat(rnd, ignore_index=True)
    print(line("round numbers (BTC $1,000, ETH $100), reclaimed", r[r["kind"] == "reclaimed"]))
    print(line("round numbers, failed", r[r["kind"] == "failed"]))
    print(f"\nshare of reclaimed sweeps with a #20 trigger in the hour: {rec['with_20'].mean():.0%}")
    c = clustered(sw.by_day(rec))
    print(f"reclaimed, 1 hour, net of one taker round trip with slippage (13 bps): {bps(c['mean'] - COST)}")
    print("\nby year, 1 hour:\n")
    print("| year | reclaimed | failed |")
    print("|---|---|---|")
    for y, g in ev.assign(year=ev["day"].str[:4]).groupby("year"):
        a = clustered(sw.by_day(g[g["kind"] == "reclaimed"]))["mean"]
        f = clustered(sw.by_day(g[g["kind"] == "failed"]))["mean"]
        print(f"| {y} | {bps(a)} | {bps(f)} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
