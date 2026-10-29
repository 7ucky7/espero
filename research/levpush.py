"""Hypothesis #34, part A — the placebo: no push into the US close where 2x funds are tiny.

    python research/levpush.py       # cached bars only; downloads nothing

Frozen in research/PREREGISTRATION_LEVPUSH.md. Part B (SOL and XRP forward) is read from
#29's ledger after 2027-03-31.
"""
from __future__ import annotations

import gzip
import io
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research"))
import fillcost as loader  # noqa: E402  (the cached-bar reader of #33)

from espero import levetf as lv  # noqa: E402
from espero import levpush as lp  # noqa: E402
from espero import liq as lq  # noqa: E402
from espero import lows as lw  # noqa: E402
from espero.liq import clustered  # noqa: E402

ROWS = ROOT / "research" / "levpush_days.csv.gz"
INFO = {"DOGE": "2025-11-20"}


def bars(coin: str) -> pd.DataFrame:
    sym = lq.symbol("binance-futures", coin)
    frames = []
    for m in loader.MONTHS:
        blob = loader.first_file(*(loader.DATA / d / sym / f"{m}.zip" for d in ("lows", "levetf", "bids")))
        if blob:
            frames.append(loader.frame(blob))
    for d in loader.DAYS:
        blob = loader.first_file(*(loader.DATA / x / sym / "daily" / f"{d}.zip" for x in ("levetf", "bids")))
        if blob:
            frames.append(loader.frame(blob))
    return lw.bars(pd.concat(frames, ignore_index=True))


def bps(x: float) -> str:
    return f"{1e4 * x:+.2f} bps"


def main() -> int:
    out = []
    for coin, first in {**lp.PLACEBO, **INFO}.items():
        b = bars(coin)
        out.append(lv.rows(b, coin, first, lp.PLACEBO_LAST))
        print(f"{coin}: {len(b)} bars, rows {first} -> {lp.PLACEBO_LAST}", flush=True)
    rows = pd.concat(out, ignore_index=True)
    buf = io.StringIO()
    rows.to_csv(buf, index=False, float_format="%.6g")
    ROWS.write_bytes(gzip.compress(buf.getvalue().encode(), mtime=0))
    placebo = lp.placebo_rows(rows)
    crit = lp.criteria(placebo)
    print("\n## criteria\n")
    print("| # | criterion | actual | met |")
    print("|---|---|---|---|")
    for i, r in enumerate(crit, 1):
        print(f"| {i} | {r['criterion']} | {r['actual']} | {'yes' if r['met'] else '**no**' if i == 1 else 'after 2027-03-31'} |")
    print(f"\nplacebo: {'flat, the test goes on forward' if crit[0]['met'] else 'NOT flat: FAIL now'}")
    print("\n## information only\n")
    print("| set | trading days | t | closed days | t | after the close (16:00 -> 16:15) | t |")
    print("|---|---|---|---|---|---|---|")
    for coin, first in {**lp.PLACEBO, **INFO}.items():
        g = rows[(rows["coin"] == coin) & (rows["date"] >= first)]
        a = clustered(lv.per_date(g[g["kind"] == "trading"]))
        c = clustered(lv.per_date(g[g["kind"] == "closed"]))
        p = clustered(lv.per_date(g[g["kind"] == "trading"], "post15"))
        print(f"| {coin} since {first} | {bps(a['mean'])} | {a['t']:.2f} | {bps(c['mean'])} | {c['t']:.2f} | "
              f"{bps(p['mean'])} | {p['t']:.2f} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
